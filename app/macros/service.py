from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.macros.models import (
    MacroExecutionLogRecord,
    MacroRecord,
    MacroScheduleRecord,
    MacroStepRecord,
)
from app.skills.computer import ApplicationLauncher
from app.skills.computer.tools.application import OpenAppTool, OpenUrlTool
from app.skills.computer.tools.keyboard import PressKeyTool, TypeTextTool
from app.skills.computer.tools.mouse import MouseClickTool, MouseScrollTool
from app.skills.computer.tools.process import CloseAppTool
from app.skills.computer.tools.screenshot import ScreenshotTool, VerifyScreenTool
from app.skills.computer.tools.uia import UiaError
from app.skills.computer.tools.uia import available as uia_available
from app.skills.computer.tools.uia import click_text as uia_click_text
from app.skills.computer.tools.uia import read_ui_text as uia_read_ui_text
from app.skills.computer.tools.window import MoveAppTool
from app.skills.files.service import FileManager
from app.tools.base import ToolResult

logger = logging.getLogger(__name__)

# Passos de macro seguros para EXECUÇÃO AGENDADA sem confirmação interativa.
# Tudo o que altera estado (teclado, mouse, apps, rede, clipboard) fora de uma
# sessão interativa é rejeitado fail-closed (Parte 16): agendamento não pode
# virar bypass do Permission Gate.
SCHEDULED_SAFE_STEPS = {"message", "wait", "screenshot", "verify_screen"}


def macro_requires_confirmation(steps: list[Any]) -> bool:
    """True se a macro possui passos que exigem confirmação por chamada."""
    for step in steps:
        step_type = getattr(step, "step_type", None) or (step or {}).get("step_type", "")
        if str(step_type) not in SCHEDULED_SAFE_STEPS:
            return True
    return False


class MacroRecorder:
    """Grava uma sequência de ações via UI Automation."""

    def __init__(self, launcher: ApplicationLauncher | None = None):
        self.launcher = launcher or ApplicationLauncher()
        self._steps: list[dict[str, Any]] = []
        self._recording = False

    def start(self) -> None:
        self._steps = []
        self._recording = True

    def stop(self) -> list[dict[str, Any]]:
        self._recording = False
        return self._steps.copy()

    @property
    def is_recording(self) -> bool:
        return self._recording

    def record_click(self, text: str, window_hint: str | None = None) -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "click",
            "params": {"text": text, "window_hint": window_hint},
            "description": f"Clicar em '{text}'",
        })

    def record_type(self, text: str, app: str | None = None) -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "type",
            "params": {"text": text, "app": app},
            "description": f"Digitar '{text[:30]}...'" if len(text) > 30 else f"Digitar '{text}'",
        })

    def record_press_key(self, key: str) -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "press_key",
            "params": {"key": key},
            "description": f"Pressionar '{key}'",
        })

    def record_open_app(self, app: str, url: str | None = None) -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "open_app",
            "params": {"app": app, "url": url},
            "description": f"Abrir app '{app}'",
        })

    def record_open_url(self, url: str) -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "open_url",
            "params": {"url": url},
            "description": f"Abrir URL '{url}'",
        })

    def record_wait(
        self, seconds: float | None = None, text: str | None = None, timeout: float = 15.0
    ) -> None:
        if not self._recording:
            return
        if seconds is not None:
            params = {"seconds": seconds}
            desc = f"Esperar {seconds}s"
        else:
            params = {"text": text, "timeout": timeout}
            desc = f"Esperar texto '{text}'"
        self._steps.append({
            "step_type": "wait",
            "params": params,
            "description": desc,
        })

    def record_scroll(self, clicks: int = 3, direction: str = "down") -> None:
        if not self._recording:
            return
        self._steps.append({
            "step_type": "scroll",
            "params": {"clicks": clicks, "direction": direction},
            "description": f"Rolar {direction} {clicks} cliques",
        })

    def record_message_placeholder(self) -> None:
        """Placeholder: substitui por params['message'] na execução."""
        if not self._recording:
            return
        self._steps.append({
            "step_type": "message",
            "params": {"field": "message"},
            "description": "Campo de mensagem (placeholder)",
        })

    def get_steps(self) -> list[dict[str, Any]]:
        return self._steps.copy()


class MacroExecutor:
    """Executa uma macro passo a passo, substituindo parâmetros."""

    def __init__(
        self,
        session: AsyncSession,
        launcher: ApplicationLauncher | None = None,
        on_progress: Any = None,
    ):
        self.session = session
        self.launcher = launcher or ApplicationLauncher()
        self.on_progress = on_progress

        file_manager = FileManager()
        self._open_app = OpenAppTool(self.launcher)
        self._open_url = OpenUrlTool(self.launcher)
        self._type_text = TypeTextTool(self.launcher)
        self._press_key = PressKeyTool()
        self._mouse_click = MouseClickTool()
        self._mouse_scroll = MouseScrollTool()
        self._move_app = MoveAppTool(self.launcher)
        self._close_app = CloseAppTool(self.launcher)
        self._screenshot = ScreenshotTool(file_manager)
        self._verify_screen = VerifyScreenTool(file_manager)

    def _substitute(self, value: Any, parameters: dict[str, Any]) -> Any:
        """Substitui {{param}} por valor em strings recursivamente."""
        if isinstance(value, str):
            for k, v in parameters.items():
                value = value.replace(f"{{{{{k}}}}}", str(v))
            return value
        if isinstance(value, dict):
            return {k: self._substitute(v, parameters) for k, v in value.items()}
        if isinstance(value, list):
            return [self._substitute(v, parameters) for v in value]
        return value

    async def execute(
        self,
        macro: MacroRecord,
        parameters: dict[str, Any] | None = None,
        schedule_id: str | None = None,
    ) -> MacroExecutionLogRecord:
        parameters = parameters or {}

        log = MacroExecutionLogRecord(
            id=str(uuid4()),
            macro_id=macro.id,
            schedule_id=schedule_id,
            status="started",
            parameters=parameters,
            steps_total=len(macro.steps),
            started_at=datetime.now(UTC),
        )
        self.session.add(log)
        await self.session.flush()

        executed = 0
        last_error: str | None = None

        for step in macro.steps:
            if log.status == "failed":
                break
            try:
                params = self._substitute(step.params, parameters)
                await self._execute_step(step.step_type, params, step.wait_after)
                executed += 1
                log.steps_executed = executed
                if self.on_progress:
                    await self.on_progress(step.step_order, executed, len(macro.steps))
                await self.session.flush()
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Macro step failed: %s", exc)
                log.status = "failed"
                log.error = last_error
                break

        if executed == len(macro.steps):
            log.status = "success"
        elif executed > 0:
            log.status = "partial"
            log.error = last_error
        else:
            log.status = "failed"
            log.error = last_error or "Nenhum passo executado"

        log.finished_at = datetime.now(UTC)
        log.duration_ms = int((log.finished_at - log.started_at).total_seconds() * 1000)
        await self.session.commit()
        return log

    async def _execute_step(
        self, step_type: str, params: dict[str, Any], wait_after: float
    ) -> ToolResult:
        result: ToolResult

        if step_type == "open_app":
            result = await self._open_app.execute(app=params["app"], url=params.get("url"))
        elif step_type == "open_url":
            result = await self._open_url.execute(url=params["url"])
        elif step_type == "type":
            result = await self._type_text_with_fallback(
                params["text"], params.get("app")
            )
        elif step_type == "press_key":
            # Se é Ctrl+V e tem clipboard salvo, restaura antes de colar
            if params["key"].lower() == "ctrl+v" and "clipboard" in params:
                try:
                    import pyperclip
                    pyperclip.copy(params["clipboard"])
                except Exception:
                    pass
            result = await self._press_key.execute(key=params["key"])
        elif step_type == "click":
            result = await self._click_via_uia(
                params.get("text"), params.get("window_hint"),
                x=params.get("x"), y=params.get("y"),
            )
        elif step_type == "wait":
            result = await self._wait(params)
        elif step_type == "scroll":
            result = await self._mouse_scroll.execute(
                clicks=params.get("clicks", 3),
                direction=params.get("direction", "down"),
            )
        elif step_type == "move_window":
            result = await self._move_app.execute(app=params["app"], monitor=params.get("monitor"))
        elif step_type == "close_app":
            result = await self._close_app.execute(app=params["app"])
        elif step_type == "message":
            # Placeholder: substitui pelo texto de params.message
            text = params.get("text", "")
            # Se não há texto explícito, pega do campo 'message' dos parâmetros
            if "message" in params:
                text = params["message"]
            result = ToolResult(name="message", success=True, data={"text": text})
        elif step_type == "screenshot":
            result = await self._screenshot.execute()
        elif step_type == "verify_screen":
            result = await self._verify_screen.execute(goal=params.get("goal", ""))
        else:
            result = ToolResult(
                name=step_type, success=False, data={},
                error=f"Tipo de passo desconhecido: {step_type}",
            )

        if not result.success:
            raise RuntimeError(f"Passo {step_type} falhou: {result.error}")

        if wait_after > 0:
            await asyncio.sleep(wait_after)

        return result

    async def _click_via_uia(
        self, text: str | None, window_hint: str | None,
        x: int | None = None, y: int | None = None,
    ) -> ToolResult:
        # Se tem texto, tenta clicar no elemento UIA
        if text:
            if not uia_available():
                msg = "UI Automation indisponível"
                return ToolResult(name="click", success=False, data={}, error=msg)
            try:
                # UIA é síncrono/bloqueante — roda fora do event loop (to_thread).
                result = await asyncio.to_thread(uia_click_text, text, window_hint=window_hint)
                return ToolResult(name="click", success=True, data=result)
            except UiaError as exc:
                # Se UIA falhou e tem coordenadas, fallback
                if x is not None and y is not None:
                    return await self._click_at_coordinates(x, y)
                return ToolResult(name="click", success=False, data={}, error=str(exc))
        # Sem texto: clica nas coordenadas
        if x is not None and y is not None:
            return await self._click_at_coordinates(x, y)
        msg = "Clique sem texto nem coordenadas"
        return ToolResult(name="click", success=False, data={}, error=msg)

    async def _click_at_coordinates(self, x: int, y: int) -> ToolResult:
        """Clica nas coordenadas (x, y) usando pyautogui (off the event loop)."""
        return await asyncio.to_thread(self._click_coordinates_sync, x, y)

    def _click_coordinates_sync(self, x: int, y: int) -> ToolResult:
        try:
            import pyautogui

            pyautogui.click(x, y)
            return ToolResult(
                name="click", success=True,
                data={"x": x, "y": y, "method": "coordinates"},
            )
        except Exception as exc:
            return ToolResult(
                name="click", success=False, data={},
                error=f"Falha ao clicar em ({x}, {y}): {exc}",
            )

    async def _type_text_with_fallback(
        self, text: str, app: str | None
    ) -> ToolResult:
        """Digita texto usando keyboard/clipboard (off the event loop)."""
        await asyncio.sleep(0.1)
        return await asyncio.to_thread(self._type_text_sync, text)

    def _type_text_sync(self, text: str) -> ToolResult:
        if not text:
            return ToolResult(
                name="type_text", success=False, data={}, error="Texto vazio para digitar."
            )
        try:
            import keyboard as kb
            import pyperclip

            old_clip = pyperclip.paste()
            pyperclip.copy(text)
            kb.press_and_release("ctrl+v")
            import time
            time.sleep(0.5)
            pyperclip.copy(old_clip)

            return ToolResult(
                name="type_text", success=True,
                data={"typed_chars": len(text), "text": text, "method": "clipboard"},
            )
        except Exception:
            try:
                import keyboard as kb
                for char in text:
                    kb.press(char)
                    kb.release(char)
                    import time
                    time.sleep(0.01)
                return ToolResult(
                    name="type_text", success=True,
                    data={"typed_chars": len(text), "text": text, "method": "keys"},
                )
            except Exception as exc2:
                return ToolResult(
                    name="type_text", success=False, data={},
                    error=f"Falha ao digitar: {exc2}",
                )

    async def _wait(self, params: dict[str, Any]) -> ToolResult:
        if "seconds" in params:
            await asyncio.sleep(float(params["seconds"]))
            return ToolResult(name="wait", success=True, data={"waited_seconds": params["seconds"]})
        if "text" in params:
            timeout = float(params.get("timeout", 15.0))
            deadline = asyncio.get_event_loop().time() + timeout
            text = str(params["text"])
            while asyncio.get_event_loop().time() < deadline:
                try:
                    elements = await asyncio.to_thread(uia_read_ui_text)
                    for el in elements:
                        if text.lower() in el.get("name", "").lower():
                            return ToolResult(name="wait", success=True, data={"found": text})
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            return ToolResult(
                name="wait", success=False, data={},
                error=f"Texto '{text}' não apareceu em {timeout}s",
            )
        return ToolResult(name="wait", success=False, data={}, error="Parâmetros de wait inválidos")


class MacroService:
    """Serviço de gerenciamento de macros e agendamentos."""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._recorder: MacroRecorder | None = None

    async def start_scheduler(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Macro scheduler started")
        # Re-registra agendamentos do banco de forma confiável
        await self.reschedule_all()

    async def stop_scheduler(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Macro scheduler stopped")

    async def reschedule_all(self) -> None:
        """Re-registra todos os agendamentos ativos do banco no scheduler."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroScheduleRecord).where(MacroScheduleRecord.enabled == 1)
            )
            schedules = list(result.scalars().all())
        for schedule in schedules:
            try:
                await self._schedule_job(schedule)
            except Exception as exc:
                logger.warning("Falha ao re-agendar %s: %s", schedule.id, exc)
        if schedules:
            logger.info("Re-agendadas %d macros do banco", len(schedules))

    async def create_macro(
        self,
        name: str,
        description: str | None,
        steps: list[dict[str, Any]],
        parameters: list[str] | None = None,
        tags: list[str] | None = None,
        target_path: str | None = None,
    ) -> MacroRecord:
        async with AsyncSessionLocal() as session:
            # Verifica nome duplicado
            existing = await session.execute(
                select(MacroRecord).where(MacroRecord.name == name)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Já existe uma macro com o nome '{name}'")

            macro = MacroRecord(
                name=name,
                description=description,
                parameters=parameters or [],
                tags=tags or [],
                target_path=target_path,
            )
            session.add(macro)
            await session.flush()

            for i, step_data in enumerate(steps):
                step = MacroStepRecord(
                    macro_id=macro.id,
                    step_order=i,
                    step_type=step_data["step_type"],
                    params=step_data.get("params", {}),
                    wait_after=step_data.get("wait_after", 0.0),
                    description=step_data.get("description"),
                )
                session.add(step)

            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(
                    f"Já existe uma macro com o nome '{name}'"
                ) from exc
            await session.refresh(macro)
            return macro

    async def get_macro(self, macro_id: str) -> MacroRecord | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroRecord).where(MacroRecord.id == macro_id)
            )
            return result.scalar_one_or_none()

    async def update_macro(self, macro_id: str, **kwargs: Any) -> MacroRecord | None:
        async with AsyncSessionLocal() as session:
            macro = await session.get(MacroRecord, macro_id)
            if not macro:
                return None
            steps_data = kwargs.pop("steps", None)
            enabled = kwargs.pop("enabled", None)
            if enabled is not None:
                kwargs["enabled"] = 1 if enabled else 0
            for key, value in kwargs.items():
                if hasattr(macro, key):
                    setattr(macro, key, value)
            if steps_data is not None:
                # Remove passos antigos e insere novos
                for step in list(macro.steps):
                    await session.delete(step)
                await session.flush()
                for i, step_data in enumerate(steps_data):
                    step = MacroStepRecord(
                        macro_id=macro.id,
                        step_order=i,
                        step_type=step_data["step_type"],
                        params=step_data.get("params", {}),
                        wait_after=step_data.get("wait_after", 0.0),
                        description=step_data.get("description"),
                    )
                    session.add(step)
            await session.commit()
            await session.refresh(macro)
            return macro

    async def list_macros(self, enabled_only: bool = True) -> list[MacroRecord]:
        async with AsyncSessionLocal() as session:
            stmt = select(MacroRecord)
            if enabled_only:
                stmt = stmt.where(MacroRecord.enabled == 1)
            stmt = stmt.order_by(MacroRecord.updated_at.desc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_macro(self, macro_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            macro = await session.get(MacroRecord, macro_id)
            if not macro:
                return False
            schedule_ids = [s.id for s in macro.schedules]
            await session.delete(macro)
            await session.commit()
            # Remove os jobs dos agendamentos junto com a macro
            for schedule_id in schedule_ids:
                try:
                    self._scheduler.remove_job(f"macro_{schedule_id}")
                except Exception:
                    pass
            return True

    async def execute_macro(
        self, macro_id: str, parameters: dict[str, Any] | None = None
    ) -> MacroExecutionLogRecord:
        async with AsyncSessionLocal() as session:
            macro = await session.get(MacroRecord, macro_id)
            if not macro:
                raise ValueError(f"Macro não encontrada: {macro_id}")
            if not macro.enabled:
                raise ValueError(f"Macro desativada: {macro.name}")
            executor = MacroExecutor(session)
            return await executor.execute(macro, parameters)

    async def search_macro(self, query: str) -> MacroRecord | None:
        """Procura macro pelo nome (case-insensitive)."""
        if not query:
            return None
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroRecord).where(
                    MacroRecord.enabled == 1,
                    MacroRecord.name.ilike(f"%{query}%"),
                ).limit(1)
            )
            return result.scalar_one_or_none()

    async def schedule_macro(
        self,
        macro_id: str,
        cron_expression: str | None = None,
        run_at: datetime | None = None,
        fixed_parameters: dict[str, Any] | None = None,
        schedule_text: str | None = None,
    ) -> MacroScheduleRecord:
        # Se schedule_text foi fornecido, converte para cron ou run_at
        if schedule_text:
            from app.reminders.service import parse_schedule
            schedule_type, schedule_value = parse_schedule(schedule_text)
            if schedule_type == "cron":
                cron_expression = schedule_value
            else:
                run_at = datetime.fromisoformat(schedule_value)
        
        brasilia_tz = timezone(timedelta(hours=-3))
        if run_at and run_at.tzinfo is not None:
            run_at = run_at.astimezone(brasilia_tz).replace(tzinfo=None)
            
        if not cron_expression and not run_at:
            raise ValueError("Informe cron_expression, run_at ou schedule_text")

        # Calcula next_run_at
        from app.reminders.service import compute_next_run
        next_run = None
        if cron_expression:
            next_run = compute_next_run("cron", cron_expression)
        elif run_at:
            next_run = run_at

        # Converte para fuso de Brasília (UTC-3)
        if next_run:
            next_run = next_run.astimezone(timezone(timedelta(hours=-3))).replace(tzinfo=None)

        async with AsyncSessionLocal() as session:
            schedule = MacroScheduleRecord(
                macro_id=macro_id,
                cron_expression=cron_expression,
                run_at=run_at,
                fixed_parameters=fixed_parameters or {},
                next_run_at=next_run,
            )
            session.add(schedule)
            await session.flush()
            
            # Tenta agendar no scheduler se estiver rodando
            if self._scheduler.running:
                await self._schedule_job(schedule)
            
            await session.commit()
            await session.refresh(schedule)
            return schedule

    async def _schedule_job(self, schedule: MacroScheduleRecord) -> None:
        if not self._scheduler.running:
            return
        job_id = f"macro_{schedule.id}"
        if schedule.cron_expression:
            # As expressões cron são normalizadas em UTC (mesma regra dos
            # lembretes). Sem isso o APScheduler interpreta no fuso local e
            # dispara em horário errado.
            trigger = CronTrigger.from_crontab(schedule.cron_expression, timezone=UTC)
        elif schedule.run_at:
            brasilia_tz = timezone(timedelta(hours=-3))
            trigger = DateTrigger(run_date=schedule.run_at, timezone=brasilia_tz)
        else:
            return

        self._scheduler.add_job(
            self._run_scheduled_macro,
            trigger=trigger,
            id=job_id,
            args=[schedule.id],
            replace_existing=True,
        )
        job = self._scheduler.get_job(job_id)
        if job and job.next_run_time:
            await self._update_next_run(schedule.id, job.next_run_time)

    async def _update_next_run(self, schedule_id: str, next_run: datetime) -> None:
        brasilia_tz = timezone(timedelta(hours=-3))
        next_run = next_run.astimezone(brasilia_tz).replace(tzinfo=None) if next_run else None
        async with AsyncSessionLocal() as session:
            schedule = await session.get(MacroScheduleRecord, schedule_id)
            if schedule:
                schedule.next_run_at = next_run
                await session.commit()

    async def _run_scheduled_macro(self, schedule_id: str) -> None:
        async with AsyncSessionLocal() as session:
            schedule = await session.get(MacroScheduleRecord, schedule_id)
            if not schedule or not schedule.enabled:
                return
            macro = await session.get(MacroRecord, schedule.macro_id)
            if not macro or not macro.enabled:
                return
            # Parte 16: execução agendada reavalia segurança — passos que
            # exigem confirmação são recusados (nunca herdam autorização
            # interativa).
            if macro_requires_confirmation(macro.steps):
                logger.warning(
                    "[security] macro agendada %s recusada: passos exigem confirmação (fail-closed)",
                    macro.name,
                )
                return

            parameters = {**schedule.fixed_parameters}
            executor = MacroExecutor(session)
            log = await executor.execute(macro, parameters, schedule_id=schedule.id)

            schedule.last_run_at = log.started_at
            schedule.run_count += 1

            # Desativa one-shot schedules (run_at sem cron)
            if schedule.run_at and not schedule.cron_expression:
                schedule.enabled = 0

            await session.commit()
            logger.info("Macro %s %s", macro.name, log.status)

    async def list_scheduled(self, enabled_only: bool = True) -> list[MacroScheduleRecord]:
        async with AsyncSessionLocal() as session:
            stmt = select(MacroScheduleRecord)
            if enabled_only:
                stmt = stmt.where(MacroScheduleRecord.enabled == 1)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def cancel_scheduled(self, schedule_id: str) -> bool:
        job_id = f"macro_{schedule_id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        async with AsyncSessionLocal() as session:
            schedule = await session.get(MacroScheduleRecord, schedule_id)
            if not schedule:
                return False
            schedule.enabled = 0
            await session.commit()
            return True

    async def get_schedule(self, schedule_id: str) -> MacroScheduleRecord | None:
        async with AsyncSessionLocal() as session:
            return await session.get(MacroScheduleRecord, schedule_id)

    async def delete_scheduled(self, schedule_id: str) -> bool:
        """Remove definitivamente um agendamento (job + registro)."""
        job_id = f"macro_{schedule_id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        async with AsyncSessionLocal() as session:
            schedule = await session.get(MacroScheduleRecord, schedule_id)
            if not schedule:
                return False
            await session.delete(schedule)
            await session.commit()
            return True

    async def update_schedule(
        self,
        schedule_id: str,
        *,
        schedule_text: str | None = None,
        cron_expression: str | None = None,
        run_at: datetime | None = None,
        fixed_parameters: dict[str, Any] | None = None,
    ) -> MacroScheduleRecord:
        """Edita o horário/repetição de um agendamento existente e reagenda no APScheduler."""
        if schedule_text:
            from app.reminders.service import parse_schedule
            schedule_type, schedule_value = parse_schedule(schedule_text)
            if schedule_type == "cron":
                cron_expression = schedule_value
                run_at = None
            else:
                run_at = datetime.fromisoformat(schedule_value)
                cron_expression = None

        brasilia_tz = timezone(timedelta(hours=-3))
        if run_at and run_at.tzinfo is not None:
            run_at = run_at.astimezone(brasilia_tz).replace(tzinfo=None)
            
        if not cron_expression and not run_at:
            raise ValueError("Informe cron_expression, run_at ou schedule_text")

        from app.reminders.service import compute_next_run
        next_run = None
        if cron_expression:
            next_run = compute_next_run("cron", cron_expression)
        elif run_at:
            next_run = run_at

        brasilia_tz = timezone(timedelta(hours=-3))
        if next_run:
            next_run = next_run.astimezone(brasilia_tz).replace(tzinfo=None)

        async with AsyncSessionLocal() as session:
            schedule = await session.get(MacroScheduleRecord, schedule_id)
            if not schedule:
                raise ValueError(f"Agendamento {schedule_id} não encontrado")
            schedule.cron_expression = cron_expression
            schedule.run_at = run_at
            schedule.next_run_at = next_run
            schedule.enabled = 1
            if fixed_parameters is not None:
                schedule.fixed_parameters = fixed_parameters
            await session.commit()
            await session.refresh(schedule)

        if self._scheduler.running:
            await self._schedule_job(schedule)
        return schedule

    async def get_execution_logs(
        self, macro_id: str | None = None, limit: int = 50
    ) -> list[MacroExecutionLogRecord]:
        async with AsyncSessionLocal() as session:
            stmt = select(MacroExecutionLogRecord).order_by(
                MacroExecutionLogRecord.started_at.desc()
            )
            if macro_id:
                stmt = stmt.where(MacroExecutionLogRecord.macro_id == macro_id)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())


macro_service = MacroService()