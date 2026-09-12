from __future__ import annotations

from datetime import datetime
from typing import Any

from app.macros.service import macro_service
from app.tools.base import Tool, ToolPermission, ToolResult


class MacroListTool(Tool):
    name = "macro_list"
    description = "Lista todas as macros registradas."
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import asyncio
            macros = await asyncio.wait_for(
                macro_service.list_macros(enabled_only=True),
                timeout=10.0,
            )
            return ToolResult(
                name=self.name,
                success=True,
                data={
"macros": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "description": m.description or "",
                        "parameters": m.parameters,
                        "tags": m.tags,
                        "steps": len(m.steps),
                        "target_path": m.target_path,
                    }
                    for m in macros
                ],
                    "count": len(macros),
                },
            )
        except TimeoutError:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Timeout: listagem de macros demorou mais de 10 segundos.",
            )
        except Exception as exc:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error=f"Erro ao listar macros: {exc}",
            )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class MacroRunTool(Tool):
    name = "macro_run"
    description = (
        "Executa uma macro já cadastrada pelo nome ou ID. Aceita parâmetros como "
        "'message', 'text', 'window', 'app'. Ex.: macro_run name='whatsapp' message='Oi, Pedro'"
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        macro_id = str(kwargs.get("macro_id", "") or "")
        name = str(kwargs.get("name", "") or "")
        parameters = {k: v for k, v in kwargs.items() if k not in ("macro_id", "name")}

        try:
            if not macro_id and name:
                macro = await macro_service.search_macro(name)
                if not macro:
                    all_macros = await macro_service.list_macros(enabled_only=True)
                    available = [m.name for m in all_macros]
                    return ToolResult(
                        name=self.name,
                        success=False,
                        data={"available": available},
                        error=f"Macro '{name}' não encontrada. Disponíveis: {available}",
                    )
                macro_id = macro.id
            if not macro_id:
                msg = "Informe 'macro_id' ou 'name'"
                return ToolResult(name=self.name, success=False, data={}, error=msg)

            # Timeout de 30 segundos para execução da macro
            import asyncio
            log = await asyncio.wait_for(
                macro_service.execute_macro(macro_id, parameters),
                timeout=30.0,
            )
            return ToolResult(
                name=self.name,
                success=log.status == "success",
                data={
                    "macro": name or macro_id,
                    "status": log.status,
                    "steps_executed": log.steps_executed,
                    "steps_total": log.steps_total,
                    "error": log.error,
                },
            )
        except TimeoutError:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Timeout: macro demorou mais de 30 segundos para executar.",
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "macro_id": {"type": "string", "description": "ID da macro"},
                "name": {"type": "string", "description": "Nome da macro"},
                "message": {"type": "string", "description": "Texto da mensagem"},
                "text": {"type": "string", "description": "Texto a digitar"},
                "app": {"type": "string", "description": "Nome do aplicativo"},
                "window": {"type": "string", "description": "Janela para ativar"},
            },
        }


class MacroCreateTool(Tool):
    name = "macro_create"
    description = (
        "Registra uma nova macro (sequência de ações). Ex.: macro_create name='whatsapp' "
        "description='Enviar mensagem WhatsApp' steps[0].step_type='open_app' ... "
        "parameters=['message']. Parâmetros identificam variáveis da macro."
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name", ""))
        description = str(kwargs.get("description", "") or "") or None
        parameters = kwargs.get("parameters", [])
        tags = kwargs.get("tags", [])
        target_path = kwargs.get("target_path", None)
        steps_data = kwargs.get("steps", [])

        if not name:
            msg = "Informe o nome da macro"
            return ToolResult(name=self.name, success=False, data={}, error=msg)
        if not steps_data:
            msg = "Informe os passos (steps)"
            return ToolResult(name=self.name, success=False, data={}, error=msg)

        try:
            if isinstance(parameters, str):
                parameters = [p.strip() for p in parameters.split(",") if p.strip()]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            macro = await macro_service.create_macro(
                name=name, description=description, steps=steps_data,
                parameters=parameters, tags=tags, target_path=target_path,
            )
            return ToolResult(
                name=self.name, success=True,
                data={"id": macro.id, "name": macro.name, "steps": len(macro.steps), "target_path": macro.target_path},
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da macro"},
                "description": {"type": "string", "description": "Descrição opcional"},
                "steps": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Lista de passos: step_type, params, wait_after, description",
                },
                "parameters": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "target_path": {
                    "type": "string",
                    "description": "Caminho/arquivo/executable que este macro abrirá quando executado (opcional). Use para diferenciar macros parecidas.",
                },
            },
        }


class MacroDeleteTool(Tool):
    name = "macro_delete"
    description = (
        "Apaga/exclui/remove uma macro gravada pelo nome ou ID. "
        "Os agendamentos dela SÃO removidos junto (senão, use macro_schedule_delete "
        "antes para apagar só os agendamentos). Ex.: macro_delete name='whatsapp'"
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        macro_id = str(kwargs.get("macro_id", "") or "")
        name = str(kwargs.get("name", "") or "")
        if not macro_id and name:
            macro = await macro_service.search_macro(name)
            if macro:
                macro_id = macro.id
        if not macro_id:
            msg = "Informe macro_id ou name. Ex.: macro_delete name='whatsapp'"
            return ToolResult(name=self.name, success=False, data={}, error=msg)

        ok = await macro_service.delete_macro(macro_id)
        return ToolResult(name=self.name, success=ok, data={"deleted": ok})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "macro_id": {"type": "string"},
                "name": {"type": "string"},
            },
        }


class MacroScheduleTool(Tool):
    name = "macro_schedule"
    description = (
        "CRIA um NOVO agendamento para uma macro ser executada automaticamente. "
        "NÃO serve para editar/excluir um agendamento existente (use macro_schedule_edit "
        "para editar e macro_schedule_delete para excluir). "
        "schedule aceita horários amigáveis: '17:30', 'amanhã às 17:30', "
        "'segunda às 09:00', 'todo dia 09:00', 'todo dia 14 às 14:30', "
        "'a cada 30 minutos', 'a cada 1 hora', 'a cada 2 horas', 'em 30 minutos', "
        "ou cron de 5 campos. "
        "Ex.: macro_schedule name='whatsapp' schedule='todo dia 08:00'"
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        macro_id = str(kwargs.get("macro_id", "") or "")
        name = str(kwargs.get("name", "") or "")
        schedule_text = str(kwargs.get("schedule", "") or "")
        skip = {"macro_id", "name", "schedule", "cron", "run_at"}
        fixed_parameters = {k: v for k, v in kwargs.items() if k not in skip}

        if not macro_id and name:
            macro = await macro_service.search_macro(name)
            if not macro:
                error = f"Macro '{name}' não encontrada"
                return ToolResult(
                    name=self.name, success=False, data={}, error=error
                )
            macro_id = macro.id
        if not macro_id:
            msg = "Informe macro_id ou name"
            return ToolResult(name=self.name, success=False, data={}, error=msg)

        # Compatibilidade com formatos antigos
        cron_expression = kwargs.get("cron") or kwargs.get("cron_expression")
        run_at_str = kwargs.get("run_at")
        run_at = None

        # Se schedule_text foi fornecido, usa parse_schedule do reminders
        if schedule_text:
            try:
                from app.reminders.service import parse_schedule
                schedule_type, schedule_value = parse_schedule(schedule_text)
                if schedule_type == "cron":
                    cron_expression = schedule_value
                else:
                    run_at = datetime.fromisoformat(schedule_value)
            except ValueError as e:
                return ToolResult(name=self.name, success=False, data={}, error=str(e))
        elif run_at_str:
            try:
                run_at = datetime.fromisoformat(str(run_at_str))
            except ValueError as e:
                return ToolResult(name=self.name, success=False, data={}, error=str(e))

        if not cron_expression and not run_at:
            msg = "Informe schedule, cron_expression ou run_at"
            return ToolResult(name=self.name, success=False, data={}, error=msg)

        try:
            schedule = await macro_service.schedule_macro(
                macro_id=macro_id,
                cron_expression=cron_expression,
                run_at=run_at,
                fixed_parameters=fixed_parameters,
            )
            return ToolResult(
                name=self.name, success=True,
                data={
                    "id": schedule.id,
                    "macro_id": schedule.macro_id,
                    "cron": schedule.cron_expression,
                    "run_at": schedule.run_at.isoformat() if schedule.run_at else None,
                    "next_run": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
                },
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "macro_id": {"type": "string"},
                "name": {"type": "string", "description": "Nome da macro"},
                "schedule": {
                    "type": "string",
                    "description": (
                        "Horário amigável: '17:30', 'amanhã às 17:30', "
                        "'segunda às 09:00', 'a cada 30 minutos'"
                    ),
                },
                "cron": {
                    "type": "string",
                    "description": "Cron de 5 campos (alternativo ao schedule)",
                },
                "run_at": {
                    "type": "string",
                    "description": "Data/hora ISO: '2026-09-08T18:30' (alternativo ao schedule)",
                },
                "message": {"type": "string"},
                "text": {"type": "string"},
                "app": {"type": "string"},
            },
        }


class MacroSchedulesTool(Tool):
    name = "macro_schedules"
    description = (
        "Lista os agendamentos de macros (cada item tem um 'id'). "
        "Use esta ferramenta para descobrir o id de um agendamento antes de "
        "editá-lo (macro_schedule_edit) ou excluí-lo (macro_schedule_delete)."
    )
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        schedules = await macro_service.list_scheduled(enabled_only=True)
        result = []
        for s in schedules:
            macro = await macro_service.get_macro(s.macro_id)
            result.append({
                "id": s.id,
                "macro_id": s.macro_id,
                "macro_name": macro.name if macro else "desconhecida",
                "cron": s.cron_expression,
                "run_at": s.run_at.isoformat() if s.run_at else None,
                "next_run": s.next_run_at.isoformat() if s.next_run_at else None,
                "enabled": bool(s.enabled),
            })
        return ToolResult(
            name=self.name, success=True, data={"schedules": result, "count": len(result)}
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class MacroSchedulesEditTool(Tool):
    name = "macro_schedule_edit"
    description = (
        "Edita/alterar/modifica o horário ou a repetição de um agendamento de macro JÁ EXISTENTE. "
        "Informe o 'schedule_id' (obtido com macro_schedules) OU 'macro_name', e o novo "
        "'schedule' amigável: '17:30', 'todo dia 09:00', 'todo dia 14 às 14:30', "
        "'segunda às 09:00', 'a cada 30 minutos', 'a cada 1 hora', ou cron de 5 campos. "
        "Ex.: macro_schedule_edit macro_name='whatsapp' schedule='todo dia 08:00'. "
        "Para criar um agendamento novo use macro_schedule; para apagar use macro_schedule_delete."
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        schedule_id = str(kwargs.get("schedule_id", "") or "")
        macro_name = str(kwargs.get("macro_name", "") or "")
        schedule_text = str(kwargs.get("schedule", "") or "")
        cron_expression = str(kwargs.get("cron", "") or "")
        run_at_str = str(kwargs.get("run_at", "") or "")
        skip = {"schedule_id", "macro_name", "schedule", "cron", "run_at"}
        fixed_parameters = {k: v for k, v in kwargs.items() if k not in skip}

        if not schedule_text and not cron_expression and not run_at_str:
            return ToolResult(
                name=self.name, success=False, data={},
                error="Informe o novo 'schedule' (ex.: 'todo dia 08:00')",
            )

        try:
            schedule = None
            if schedule_id:
                schedule = await macro_service.get_schedule(schedule_id)
            elif macro_name:
                macro = await macro_service.search_macro(macro_name)
                if not macro:
                    available = [
                        m.name for m in await macro_service.list_macros(enabled_only=True)
                    ]
                    return ToolResult(
                        name=self.name, success=False, data={"available": available},
                        error=f"Macro '{macro_name}' não encontrada",
                    )
                schedules = await macro_service.list_scheduled(enabled_only=False)
                schedule = next((s for s in schedules if s.macro_id == macro.id), None)
                if schedule is None:
                    return ToolResult(
                        name=self.name, success=False, data={},
                        error=(
                            f"Macro '{macro_name}' não tem agendamento para editar. "
                            "Use macro_schedule para criar um."
                        ),
                    )
            if schedule is None:
                current = await macro_service.list_scheduled(enabled_only=False)
                return ToolResult(
                    name=self.name, success=False,
                    data={
                        "schedules": [
                            {
                                "id": s.id,
                                "macro_id": s.macro_id,
                                "cron": s.cron_expression,
                                "run_at": s.run_at.isoformat() if s.run_at else None,
                            }
                            for s in current
                        ]
                    },
                    error=(
                        "Agendamento não encontrado. Consulte macro_schedules e "
                        "informe o schedule_id."
                    ),
                )

            updated = await macro_service.update_schedule(
                schedule.id,
                schedule_text=schedule_text or None,
                cron_expression=cron_expression or None,
                run_at=(
                    datetime.fromisoformat(run_at_str)
                    if run_at_str else None
                ),
                fixed_parameters=fixed_parameters or None,
            )
            return ToolResult(
                name=self.name, success=True,
                data={
                    "id": updated.id,
                    "macro_id": updated.macro_id,
                    "cron": updated.cron_expression,
                    "run_at": updated.run_at.isoformat() if updated.run_at else None,
                    "next_run": updated.next_run_at.isoformat() if updated.next_run_at else None,
                    "enabled": bool(updated.enabled),
                },
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "ID do agendamento (de macro_schedules)",
                },
                "macro_name": {
                    "type": "string",
                    "description": "Nome da macro com agendamento",
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "Novo horário amigável: '17:30', 'todo dia 09:00', "
                        "'segunda às 09:00', 'a cada 30 minutos', 'a cada 1 hora'"
                    ),
                },
                "cron": {
                    "type": "string",
                    "description": "Cron de 5 campos (alternativo ao schedule)",
                },
                "run_at": {
                    "type": "string",
                    "description": "Data/hora ISO (alternativo ao schedule)",
                },
            },
        }


class MacroSchedulesDeleteTool(Tool):
    name = "macro_schedule_delete"
    description = (
        "Apaga/exclui/remove DEFINITIVAMENTE um agendamento de macro. "
        "Informe 'schedule_id' (obtido com macro_schedules) ou 'macro_name' "
        "(apaga todos os agendamentos da macro). O oposto de macro_schedule. "
        "Para só editar o horário use macro_schedule_edit. "
        "Ex.: macro_schedule_delete schedule_id='abc123'"
    )
    permission = ToolPermission.sensitive

    async def execute(self, **kwargs: Any) -> ToolResult:
        schedule_id = str(kwargs.get("schedule_id", "") or "")
        macro_name = str(kwargs.get("macro_name", "") or "")
        deleted: list[str] = []

        try:
            if schedule_id:
                ok = await macro_service.delete_scheduled(schedule_id)
                if not ok:
                    current = await macro_service.list_scheduled(enabled_only=False)
                    return ToolResult(
                        name=self.name, success=False,
                        data={
                            "available": [
                                {
                                    "id": s.id,
                                    "macro_id": s.macro_id,
                                    "cron": s.cron_expression,
                                    "run_at": s.run_at.isoformat() if s.run_at else None,
                                }
                                for s in current
                            ]
                        },
                        error=f"Agendamento {schedule_id} não encontrado. Consulte macro_schedules.",
                    )
                deleted.append(schedule_id)
            elif macro_name:
                macro = await macro_service.search_macro(macro_name)
                if not macro:
                    available = [
                        m.name for m in await macro_service.list_macros(enabled_only=True)
                    ]
                    return ToolResult(
                        name=self.name, success=False, data={"available": available},
                        error=f"Macro '{macro_name}' não encontrada",
                    )
                schedules = await macro_service.list_scheduled(enabled_only=False)
                for s in schedules:
                    if s.macro_id == macro.id:
                        await macro_service.delete_scheduled(s.id)
                        deleted.append(s.id)
                if not deleted:
                    return ToolResult(
                        name=self.name, success=False, data={},
                        error=f"Macro '{macro_name}' não tem agendamentos para excluir.",
                    )
            else:
                return ToolResult(
                    name=self.name, success=False, data={},
                    error="Informe 'schedule_id' ou 'macro_name'",
                )
            return ToolResult(
                name=self.name, success=True,
                data={"deleted": deleted, "count": len(deleted)},
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string", "description": "ID do agendamento (de macro_schedules)"},
                "macro_name": {"type": "string", "description": "Nome da macro (apaga os agendamentos dela)"},
            },
        }