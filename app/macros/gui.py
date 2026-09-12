from __future__ import annotations

import asyncio
import json
import re
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any

from app.macros.recorder import input_recorder
from app.macros.service import macro_service


class _AsyncRunner:
    """Roda coroutines da thread do Tkinter via asyncio."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any) -> Any:
        if self._loop is None:
            self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def in_background(self, coro: Any) -> None:
        """Agenda uma coroutine no loop sem esperar o resultado."""
        if self._loop is None:
            self.start()
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2)


_async = _AsyncRunner()


class MacroGui:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Alpha Macros")
        self.root.geometry("960x640")
        self.root.minsize(700, 400)

        style = ttk.Style()
        style.theme_use("clam")

        self._build_menu()
        self._build_notebook()
        self._refresh_macros()
        self._refresh_schedules()
        self._reminder_runner = None

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Atualizar", command=self._refresh_all, accelerator="F5"
        )
        file_menu.add_separator()
        file_menu.add_command(label="Sair", command=self.root.destroy)
        menubar.add_cascade(label="Arquivo", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Sobre", command=self._show_about)
        menubar.add_cascade(label="Ajuda", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<F5>", lambda _: self._refresh_all())

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.tab_macros = ttk.Frame(self.notebook)
        self.tab_recorder = ttk.Frame(self.notebook)
        self.tab_schedules = ttk.Frame(self.notebook)
        self.tab_logs = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_macros, text="  Macros  ")
        self.notebook.add(self.tab_recorder, text="  Gravar  ")
        self.notebook.add(self.tab_schedules, text="  Agendamentos  ")
        self.notebook.add(self.tab_logs, text="  Logs  ")

        self._build_macros_tab()
        self._build_recorder_tab()
        self._build_schedules_tab()
        self._build_logs_tab()

    # ── Macros Tab ──────────────────────────────────────────────────────

    def _build_macros_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_macros)
        toolbar.pack(fill=tk.X, padx=4, pady=4)

        for text, cmd in [
            ("Novo (manual)", self._create_macro_dialog),
            ("Editar", self._edit_macro_dialog),
            ("Executar", self._run_selected_macro),
            ("Excluir", self._delete_selected_macro),
            ("Atualizar", self._refresh_macros),
        ]:
            ttk.Button(toolbar, text=text, command=cmd).pack(
                side=tk.LEFT, padx=2
            )

        cols = ("name", "description", "steps", "tags")
        self.macro_tree = ttk.Treeview(
            self.tab_macros, columns=cols, show="headings", selectmode="browse"
        )
        self.macro_tree.heading("name", text="Nome")
        self.macro_tree.heading("description", text="Descrição")
        self.macro_tree.heading("steps", text="Passos")
        self.macro_tree.heading("tags", text="Tags")
        self.macro_tree.column("name", width=160)
        self.macro_tree.column("description", width=300)
        self.macro_tree.column("steps", width=60, anchor=tk.CENTER)
        self.macro_tree.column("tags", width=120)
        self.macro_tree.pack(fill=tk.BOTH, expand=True, padx=4)

        scrollbar = ttk.Scrollbar(
            self.tab_macros, orient=tk.VERTICAL, command=self.macro_tree.yview
        )
        self.macro_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._macro_data: dict[str, Any] = {}

    def _refresh_macros(self) -> None:
        try:
            macros = _async.run(macro_service.list_macros(enabled_only=False))
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return
        self.macro_tree.delete(*self.macro_tree.get_children())
        self._macro_data.clear()
        for m in macros:
            tags_str = ", ".join(m.tags) if m.tags else ""
            desc = (m.description or "")[:60]
            self.macro_tree.insert(
                "", tk.END, iid=m.id,
                values=(m.name, desc, len(m.steps), tags_str),
            )
            self._macro_data[m.id] = m

    def _get_selected_macro_id(self) -> str | None:
        sel = self.macro_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma macro primeiro.")
            return None
        return sel[0]

    def _run_selected_macro(self) -> None:
        macro_id = self._get_selected_macro_id()
        if not macro_id:
            return
        macro = self._macro_data.get(macro_id)
        params = self._ask_parameters(macro) if macro and macro.parameters else {}
        if params is None:
            return
        try:
            log = _async.run(macro_service.execute_macro(macro_id, params))
            if log.status == "success":
                messagebox.showinfo(
                    "Sucesso",
                    f"Macro executada com sucesso!\n{log.steps_executed} passos.",
                )
            else:
                detail = f"{log.status}\n{log.error or ''}"
                messagebox.showwarning(
                    "Aviso", f"Macro finalizou com status: {detail}"
                )
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _delete_selected_macro(self) -> None:
        macro_id = self._get_selected_macro_id()
        if not macro_id:
            return
        if not messagebox.askyesno("Confirmar", "Excluir esta macro?"):
            return
        try:
            _async.run(macro_service.delete_macro(macro_id))
            self._refresh_macros()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _ask_parameters(self, macro: Any) -> dict[str, str] | None:
        if not macro.parameters:
            return {}
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Parâmetros - {macro.name}")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()

        result: dict[str, str] = {}
        entries: dict[str, ttk.Entry] = {}

        for i, param in enumerate(macro.parameters):
            ttk.Label(dialog, text=f"{param}:").grid(
                row=i, column=0, padx=8, pady=4, sticky=tk.W
            )
            entry = ttk.Entry(dialog, width=30)
            entry.grid(row=i, column=1, padx=8, pady=4)
            entries[param] = entry

        def on_ok() -> None:
            for param, entry in entries.items():
                result[param] = entry.get()
            dialog.destroy()

        def on_cancel() -> None:
            result.clear()
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=len(macro.parameters), column=0, columnspan=2, pady=8)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancelar", command=on_cancel).pack(
            side=tk.LEFT, padx=4
        )

        self.root.wait_window(dialog)
        return result if result else None

    def _create_macro_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Nova Macro (manual)")
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()

        fields: dict[str, ttk.Entry | tk.Text] = {}

        ttk.Label(dialog, text="Nome:").grid(
            row=0, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["name"] = ttk.Entry(dialog, width=40)
        fields["name"].grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Descrição:").grid(
            row=1, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["description"] = ttk.Entry(dialog, width=40)
        fields["description"].grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Tags (vírgula):").grid(
            row=2, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["tags"] = ttk.Entry(dialog, width=40)
        fields["tags"].grid(row=2, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Parâmetros (vírgula):").grid(
            row=3, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["parameters"] = ttk.Entry(dialog, width=40)
        fields["parameters"].grid(row=3, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Passos JSON:").grid(
            row=4, column=0, padx=8, pady=4, sticky=tk.NW
        )
        steps_text = tk.Text(dialog, width=45, height=8)
        steps_text.grid(row=4, column=1, padx=8, pady=4)
        steps_text.insert(
            tk.END,
            '[{"step_type": "open_app", "params": {"app": "Calculadora"}}, '
            '{"step_type": "type", "params": {"text": "1+1"}}]',
        )

        def on_save() -> None:
            name_val = fields["name"].get().strip()
            if not name_val:
                messagebox.showwarning("Aviso", "Nome é obrigatório.", parent=dialog)
                return
            try:
                steps = json.loads(steps_text.get("1.0", tk.END))
            except json.JSONDecodeError as exc:
                messagebox.showerror("Erro", f"JSON inválido: {exc}", parent=dialog)
                return
            desc_val = fields["description"].get().strip() or None
            tags_val = [
                t.strip() for t in fields["tags"].get().split(",") if t.strip()
            ]
            params_val = [
                p.strip() for p in fields["parameters"].get().split(",") if p.strip()
            ]
            try:
                _async.run(
                    macro_service.create_macro(
                        name=name_val,
                        description=desc_val,
                        steps=steps,
                        parameters=params_val,
                        tags=tags_val,
                    )
                )
                self._refresh_macros()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Erro", str(exc), parent=dialog)

        ttk.Button(dialog, text="Salvar", command=on_save).grid(
            row=5, column=1, pady=8, sticky=tk.E
        )

    def _edit_macro_dialog(self) -> None:
        sel = self.macro_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma macro para editar.")
            return
        macro_id = sel[0]  # iid já é o ID da macro

        # Busca dados atuais
        try:
            macro = _async.run(macro_service.get_macro(macro_id))
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return

        if not macro:
            messagebox.showerror("Erro", "Macro não encontrada.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Editar Macro: {macro.name}")
        dialog.geometry("500x380")
        dialog.transient(self.root)
        dialog.grab_set()

        fields: dict[str, ttk.Entry | tk.Text] = {}

        ttk.Label(dialog, text="Nome:").grid(
            row=0, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["name"] = ttk.Entry(dialog, width=40)
        fields["name"].insert(0, macro.name)
        fields["name"].grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Descrição:").grid(
            row=1, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["description"] = ttk.Entry(dialog, width=40)
        if macro.description:
            fields["description"].insert(0, macro.description)
        fields["description"].grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Tags (vírgula):").grid(
            row=2, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["tags"] = ttk.Entry(dialog, width=40)
        fields["tags"].insert(0, ", ".join(macro.tags))
        fields["tags"].grid(row=2, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Parâmetros (vírgula):").grid(
            row=3, column=0, padx=8, pady=4, sticky=tk.W
        )
        fields["parameters"] = ttk.Entry(dialog, width=40)
        fields["parameters"].insert(0, ", ".join(macro.parameters))
        fields["parameters"].grid(row=3, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Passos JSON:").grid(
            row=4, column=0, padx=8, pady=4, sticky=tk.NW
        )
        steps_text = tk.Text(dialog, width=45, height=9)
        steps_text.grid(row=4, column=1, padx=8, pady=4)
        # Converte MacroStepRecord objects para dicts antes de json.dumps
        steps_dicts = [
            {
                "step_type": s.step_type,
                "params": s.params,
                "description": s.description or "",
            }
            for s in macro.steps
        ]
        steps_text.insert(tk.END, json.dumps(steps_dicts, indent=2, ensure_ascii=False))

        def on_save() -> None:
            name_val = fields["name"].get().strip()
            if not name_val:
                messagebox.showwarning("Aviso", "Nome é obrigatório.", parent=dialog)
                return
            try:
                steps = json.loads(steps_text.get("1.0", tk.END))
            except json.JSONDecodeError as exc:
                messagebox.showerror("Erro", f"JSON inválido: {exc}", parent=dialog)
                return
            desc_val = fields["description"].get().strip() or None
            tags_val = [
                t.strip() for t in fields["tags"].get().split(",") if t.strip()
            ]
            params_val = [
                p.strip() for p in fields["parameters"].get().split(",") if p.strip()
            ]
            try:
                _async.run(
                    macro_service.update_macro(
                        macro_id=macro_id,
                        name=name_val,
                        description=desc_val,
                        steps=steps,
                        parameters=params_val,
                        tags=tags_val,
                    )
                )
                self._refresh_macros()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Erro", str(exc), parent=dialog)

        ttk.Button(dialog, text="Salvar", command=on_save).grid(
            row=5, column=1, pady=8, sticky=tk.E
        )

    def _build_recorder_tab(self) -> None:
        # Header
        header = ttk.Frame(self.tab_recorder)
        header.pack(fill=tk.X, padx=4, pady=4)

        self._rec_status = ttk.Label(header, text="Pronto para gravar", foreground="gray")
        self._rec_status.pack(side=tk.LEFT, padx=4)

        self._rec_btn_start = ttk.Button(
            header, text="Iniciar Gravação", command=self._start_recording
        )
        self._rec_btn_start.pack(side=tk.RIGHT, padx=4)

        self._rec_btn_stop = ttk.Button(
            header, text="Parar e Salvar", command=self._stop_and_save,
            state=tk.DISABLED,
        )
        self._rec_btn_stop.pack(side=tk.RIGHT, padx=4)

        self._rec_btn_cancel = ttk.Button(
            header, text="Cancelar", command=self._cancel_recording,
            state=tk.DISABLED,
        )
        self._rec_btn_cancel.pack(side=tk.RIGHT, padx=4)

        # Steps list (live)
        steps_frame = ttk.LabelFrame(self.tab_recorder, text="Passos gravados")
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._rec_steps_list = tk.Listbox(
            steps_frame, font=("Consolas", 10), selectmode=tk.SINGLE
        )
        self._rec_steps_list.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            steps_frame, orient=tk.VERTICAL, command=self._rec_steps_list.yview
        )
        self._rec_steps_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Save dialog
        save_frame = ttk.Frame(self.tab_recorder)
        save_frame.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(save_frame, text="Nome:").pack(side=tk.LEFT, padx=4)
        self._rec_name_entry = ttk.Entry(save_frame, width=30)
        self._rec_name_entry.pack(side=tk.LEFT, padx=4)

        ttk.Label(save_frame, text="Tags:").pack(side=tk.LEFT, padx=4)
        self._rec_tags_entry = ttk.Entry(save_frame, width=20)
        self._rec_tags_entry.pack(side=tk.LEFT, padx=4)

    def _start_recording(self) -> None:
        input_recorder.start()
        self._rec_status.config(text="Gravando...", foreground="red")
        self._rec_btn_start.config(state=tk.DISABLED)
        self._rec_btn_stop.config(state=tk.NORMAL)
        self._rec_btn_cancel.config(state=tk.NORMAL)
        self._rec_steps_list.delete(0, tk.END)
        self._poll_recorder()

    def _poll_recorder(self) -> None:
        """Poll periódico para atualizar a lista de passos."""
        if not input_recorder.is_recording:
            return
        steps = input_recorder.steps
        current_count = self._rec_steps_list.size()
        if len(steps) > current_count:
            for step in steps[current_count:]:
                self._rec_steps_list.insert(tk.END, step.description)
            self._rec_steps_list.see(tk.END)
        self.root.after(200, self._poll_recorder)

    def _stop_and_save(self) -> None:
        steps = input_recorder.stop()
        self._rec_status.config(text="Gravação concluída", foreground="green")
        self._rec_btn_start.config(state=tk.NORMAL)
        self._rec_btn_stop.config(state=tk.DISABLED)
        self._rec_btn_cancel.config(state=tk.DISABLED)

        if not steps:
            messagebox.showinfo("Aviso", "Nenhum passo gravado.")
            return

        # Abre dialog para salvar
        self._save_recorded_macro(steps)

    def _cancel_recording(self) -> None:
        input_recorder.cancel()
        self._rec_status.config(text="Gravação cancelada", foreground="gray")
        self._rec_btn_start.config(state=tk.NORMAL)
        self._rec_btn_stop.config(state=tk.DISABLED)
        self._rec_btn_cancel.config(state=tk.DISABLED)
        self._rec_steps_list.delete(0, tk.END)

    def _save_recorded_macro(self, steps: list[Any]) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Salvar Macro Gravada")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Nome:").grid(
            row=0, column=0, padx=8, pady=4, sticky=tk.W
        )
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.grid(row=0, column=1, padx=8, pady=4)
        # Sugere nome baseado no primeiro passo
        if steps:
            first = steps[0].description[:30]
            name_entry.insert(0, f"Macro: {first}")

        ttk.Label(dialog, text="Descrição:").grid(
            row=1, column=0, padx=8, pady=4, sticky=tk.W
        )
        desc_entry = ttk.Entry(dialog, width=40)
        desc_entry.grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(dialog, text="Tags (vírgula):").grid(
            row=2, column=0, padx=8, pady=4, sticky=tk.W
        )
        tags_entry = ttk.Entry(dialog, width=40)
        tags_entry.grid(row=2, column=1, padx=8, pady=4)

        # Preview dos passos
        ttk.Label(dialog, text="Passos gravados:").grid(
            row=3, column=0, padx=8, pady=4, sticky=tk.NW
        )
        preview = tk.Text(dialog, width=55, height=8, font=("Consolas", 9))
        preview.grid(row=3, column=1, padx=8, pady=4)
        for step in steps:
            preview.insert(tk.END, f"  {step.description}\n")
        preview.config(state=tk.DISABLED)

        def on_save() -> None:
            name_val = name_entry.get().strip()
            if not name_val:
                messagebox.showwarning("Aviso", "Nome é obrigatório.", parent=dialog)
                return
            desc_val = desc_entry.get().strip() or None
            tags_val = [
                t.strip() for t in tags_entry.get().split(",") if t.strip()
            ]
            steps_data = [s.to_dict() for s in steps]
            try:
                _async.run(
                    macro_service.create_macro(
                        name=name_val,
                        description=desc_val,
                        steps=steps_data,
                        tags=tags_val,
                    )
                )
                self._refresh_macros()
                messagebox.showinfo(
                    "Sucesso",
                    f"Macro '{name_val}' salva com {len(steps)} passos!",
                )
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Erro", str(exc), parent=dialog)

        ttk.Button(dialog, text="Salvar Macro", command=on_save).grid(
            row=4, column=1, pady=8, sticky=tk.E
        )

    # ── Schedules Tab ──────────────────────────────────────────────────

    def _build_schedules_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_schedules)
        toolbar.pack(fill=tk.X, padx=4, pady=4)

        for text, cmd in [
            ("Novo Agendamento", self._create_schedule_dialog),
            ("Editar", self._edit_selected_schedule),
            ("Excluir", self._delete_selected_schedule),
            ("Cancelar", self._cancel_selected_schedule),
            ("Atualizar", self._refresh_schedules),
        ]:
            ttk.Button(toolbar, text=text, command=cmd).pack(
                side=tk.LEFT, padx=2
            )

        cols = ("macro", "cron", "next_run", "enabled")
        self.schedule_tree = ttk.Treeview(
            self.tab_schedules, columns=cols, show="headings", selectmode="browse"
        )
        self.schedule_tree.heading("macro", text="Macro")
        self.schedule_tree.heading("cron", text="Cron")
        self.schedule_tree.heading("next_run", text="Próxima Execução")
        self.schedule_tree.heading("enabled", text="Ativo")
        self.schedule_tree.column("macro", width=200)
        self.schedule_tree.column("cron", width=160)
        self.schedule_tree.column("next_run", width=160)
        self.schedule_tree.column("enabled", width=60, anchor=tk.CENTER)
        self.schedule_tree.pack(fill=tk.BOTH, expand=True, padx=4)

        self._schedule_data: dict[str, Any] = {}

    def _refresh_schedules(self) -> None:
        try:
            schedules = _async.run(
                macro_service.list_scheduled(enabled_only=False)
            )
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        self._schedule_data.clear()
        for s in schedules:
            macro = _async.run(macro_service.get_macro(s.macro_id))
            macro_name = macro.name if macro else "N/A"
            schedule_info = s.cron_expression
            if not schedule_info and s.run_at:
                schedule_info = f"1x em {s.run_at.astimezone().strftime('%d/%m/%Y %H:%M')}"
            schedule_info = schedule_info or "-"
            # Converte para horário de Brasília (UTC-3) para display consistente
            from datetime import timedelta, timezone
            brasilia_tz = timezone(timedelta(hours=-3))
            next_run = (
                s.next_run_at.astimezone(brasilia_tz).strftime("%d/%m/%Y %H:%M")
                if s.next_run_at
                else "-"
            )
            enabled = "Sim" if s.enabled else "Não"
            values = (macro_name, schedule_info, next_run, enabled)
            self.schedule_tree.insert("", tk.END, iid=s.id, values=values)
            self._schedule_data[s.id] = s

    def _cancel_selected_schedule(self) -> None:
        sel = self.schedule_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um agendamento.")
            return
        if not messagebox.askyesno("Confirmar", "Cancelar este agendamento?"):
            return
        try:
            _async.run(macro_service.cancel_scheduled(sel[0]))
            self._refresh_schedules()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _delete_selected_schedule(self) -> None:
        sel = self.schedule_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um agendamento.")
            return
        if not messagebox.askyesno(
            "Confirmar", "Excluir DEFINITIVAMENTE este agendamento?"
        ):
            return
        try:
            _async.run(macro_service.delete_scheduled(sel[0]))
            self._refresh_schedules()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _edit_selected_schedule(self) -> None:
        sel = self.schedule_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um agendamento.")
            return
        schedule = self._schedule_data.get(sel[0])
        if schedule is None:
            try:
                schedule = _async.run(macro_service.get_schedule(sel[0]))
                self._schedule_data[sel[0]] = schedule
            except Exception as exc:
                messagebox.showerror("Erro", str(exc))
                return
        self._create_schedule_dialog(edit_schedule=schedule)

    def _create_schedule_dialog(self, edit_schedule: Any = None) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Editar Agendamento" if edit_schedule else "Novo Agendamento")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Macro selection
        ttk.Label(dialog, text="Macro:").grid(
            row=0, column=0, padx=8, pady=4, sticky=tk.W
        )
        macro_combo = ttk.Combobox(dialog, width=35, state="readonly")
        macro_combo.grid(row=0, column=1, padx=8, pady=4, columnspan=2)

        try:
            macros = _async.run(macro_service.list_macros(enabled_only=True))
            macro_names = [m.name for m in macros]
            macro_id_map = {m.name: m.id for m in macros}
            macro_combo["values"] = macro_names
            if macro_names:
                macro_combo.current(0)
        except Exception:
            macro_names = []
            macro_id_map = {}

        # Date/Time section
        date_frame = ttk.LabelFrame(dialog, text="Data e Hora", padding=8)
        date_frame.grid(row=1, column=0, columnspan=3, padx=8, pady=8, sticky=tk.W+tk.E)

        # Date picker
        ttk.Label(date_frame, text="Data:").grid(row=0, column=0, padx=4)
        from datetime import datetime
        now = datetime.now()
        
        day_var = tk.StringVar(value=str(now.day))
        month_var = tk.StringVar(value=str(now.month))
        year_var = tk.StringVar(value=str(now.year))
        
        day_values = [str(i) for i in range(1, 32)]
        day_combo = ttk.Combobox(
            date_frame, width=5, textvariable=day_var, values=day_values
        )
        day_combo.grid(row=0, column=1, padx=2)
        ttk.Label(date_frame, text="/").grid(row=0, column=2)
        month_values = [str(i) for i in range(1, 13)]
        month_combo = ttk.Combobox(
            date_frame, width=5, textvariable=month_var, values=month_values
        )
        month_combo.grid(row=0, column=3, padx=2)
        ttk.Label(date_frame, text="/").grid(row=0, column=4)
        year_values = [str(i) for i in range(now.year, now.year + 5)]
        year_combo = ttk.Combobox(
            date_frame, width=7, textvariable=year_var, values=year_values
        )
        year_combo.grid(row=0, column=5, padx=2)

        # Time picker
        ttk.Label(date_frame, text="Hora:").grid(row=0, column=6, padx=4)
        hour_var = tk.StringVar(value=str(now.hour).zfill(2))
        hour_spin = ttk.Spinbox(
            date_frame, from_=0, to=23, width=3,
            textvariable=hour_var, format="%02.0f"
        )
        hour_spin.grid(row=0, column=7, padx=2)
        ttk.Label(date_frame, text=":").grid(row=0, column=8)
        min_var = tk.StringVar(value=str(now.minute).zfill(2))
        min_spin = ttk.Spinbox(
            date_frame, from_=0, to=59, width=3,
            textvariable=min_var, format="%02.0f"
        )
        min_spin.grid(row=0, column=9, padx=2)

        # Repeat section
        repeat_frame = ttk.LabelFrame(dialog, text="Repetição", padding=8)
        repeat_frame.grid(row=2, column=0, columnspan=3, padx=8, pady=8, sticky=tk.W+tk.E)

        repeat_var = tk.StringVar(value="once")
        repeats = [
            ("Uma vez", "once"),
            ("A cada hora", "hourly"),
            ("A cada dia", "daily"),
            ("A cada semana", "weekly"),
            ("A cada mês", "monthly"),
        ]
        for i, (text, value) in enumerate(repeats):
            ttk.Radiobutton(repeat_frame, text=text, variable=repeat_var, value=value).grid(
                row=i//3, column=i%3, padx=4, pady=2, sticky=tk.W
            )

        # Pré-preenche os campos ao editar um agendamento existente
        if edit_schedule is not None:
            try:
                macro = _async.run(macro_service.get_macro(edit_schedule.macro_id))
                if macro and macro.name in macro_id_map:
                    macro_combo.set(macro.name)
            except Exception:
                pass
            try:
                edit_repeat, edit_dt = self._schedule_edit_defaults(edit_schedule)
                day_var.set(str(edit_dt.day))
                month_var.set(str(edit_dt.month))
                year_var.set(str(edit_dt.year))
                hour_var.set(str(edit_dt.hour).zfill(2))
                min_var.set(str(edit_dt.minute).zfill(2))
                repeat_var.set(edit_repeat)
            except Exception:
                pass

        # Summary
        summary_var = tk.StringVar()
        summary_label = ttk.Label(dialog, textvariable=summary_var, foreground="gray")
        summary_label.grid(row=3, column=0, columnspan=3, padx=8, pady=4)

        def update_summary(*args):
            try:
                d = int(day_var.get())
                m = int(month_var.get())
                y = int(year_var.get())
                h = int(hour_var.get())
                mi = int(min_var.get())
                repeat = repeat_var.get()
                
                dt = datetime(y, m, d, h, mi)
                repeat_text = {
                    "once": "uma vez",
                    "hourly": "a cada hora",
                    "daily": "a cada dia",
                    "weekly": "a cada semana",
                    "monthly": "a cada mês",
                }.get(repeat, "")
                
                summary_var.set(f"Agendado para {dt.strftime('%d/%m/%Y às %H:%M')} - {repeat_text}")
            except Exception:
                summary_var.set("")

        day_var.trace_add("write", update_summary)
        month_var.trace_add("write", update_summary)
        year_var.trace_add("write", update_summary)
        hour_var.trace_add("write", update_summary)
        min_var.trace_add("write", update_summary)
        repeat_var.trace_add("write", update_summary)
        update_summary()

        def on_save() -> None:
            name = macro_combo.get()
            if not name or name not in macro_id_map:
                messagebox.showwarning(
                    "Aviso", "Selecione uma macro válida.", parent=dialog
                )
                return
            
            try:
                d = int(day_var.get())
                m = int(month_var.get())
                y = int(year_var.get())
                h = int(hour_var.get())
                mi = int(min_var.get())
                dt = datetime(y, m, d, h, mi)
            except ValueError:
                messagebox.showwarning(
                    "Aviso", "Data/hora inválida.", parent=dialog
                )
                return
            
            repeat = repeat_var.get()
            schedule_text = ""
            
            if repeat == "once":
                schedule_text = dt.strftime("%Y-%m-%d %H:%M")
            elif repeat == "hourly":
                schedule_text = f"a cada {dt.minute} minutos" if dt.minute else "a cada hora"
            elif repeat == "daily":
                schedule_text = f"todo dia {dt.strftime('%H:%M')}"
            elif repeat == "weekly":
                weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
                weekday = weekdays[dt.weekday()]
                schedule_text = f"todo {weekday} às {dt.strftime('%H:%M')}"
            elif repeat == "monthly":
                schedule_text = f"todo dia {dt.day} às {dt.strftime('%H:%M')}"
            
            try:
                if edit_schedule is not None:
                    _async.run(
                        macro_service.update_schedule(
                            edit_schedule.id, schedule_text=schedule_text
                        )
                    )
                else:
                    macro_id = macro_id_map[name]
                    _async.run(
                        macro_service.schedule_macro(
                            macro_id, schedule_text=schedule_text
                        )
                    )
                self._refresh_schedules()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Erro", str(exc), parent=dialog)

        ttk.Button(
            dialog,
            text="Salvar" if edit_schedule else "Agendar",
            command=on_save,
        ).grid(row=4, column=2, pady=8, sticky=tk.E)

    @staticmethod
    def _schedule_edit_defaults(schedule: Any) -> tuple[str, datetime]:
        """Deriva (repetição, data/hora local) de um agendamento existente.

        O cron é normalizado em UTC (UTC-3 Brasília); converte a hora de volta
        para o horário local usado pelos campos do diálogo.
        """
        def _local_hour(utc_hour: int) -> int:
            return (utc_hour - 3) % 24

        now = datetime.now()
        cron = schedule.cron_expression or ""
        target = schedule.run_at or schedule.next_run_at
        base = target.astimezone().replace(tzinfo=None) if target else now

        if not cron:
            return "once", base

        m = re.fullmatch(r"\*/\d+ \* \* \* \*", cron)
        if m:
            minute = int(cron.split()[0].lstrip("*/"))
            return "hourly", base.replace(minute=minute, second=0, microsecond=0)

        if cron.startswith("0 * * * *") or re.fullmatch(r"0 \*/\d+ \* \* \*", cron):
            return "hourly", base.replace(minute=0, second=0, microsecond=0)

        m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) \* \* \*", cron)
        if m:
            return "daily", base.replace(
                hour=_local_hour(int(m.group(2))), minute=int(m.group(1)),
                second=0, microsecond=0,
            )

        m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) \* \* (\d)", cron)
        if m:
            py_wd = (int(m.group(3)) - 1) % 7
            dt = base.replace(
                hour=_local_hour(int(m.group(2))), minute=int(m.group(1)),
                second=0, microsecond=0,
            )
            dt += timedelta(days=(py_wd - dt.weekday()) % 7)
            return "weekly", dt

        m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) (\d{1,2}) \* \*", cron)
        if m:
            dt = base.replace(
                hour=_local_hour(int(m.group(2))), minute=int(m.group(1)),
                second=0, microsecond=0,
            )
            try:
                dt = dt.replace(day=int(m.group(3)))
            except ValueError:
                pass
            return "monthly", dt

        return "daily", base

    # ── Logs Tab ───────────────────────────────────────────────────────

    def _build_logs_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_logs)
        toolbar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(toolbar, text="Atualizar", command=self._refresh_logs).pack(
            side=tk.LEFT, padx=2
        )

        cols = ("macro", "status", "steps", "duration", "error")
        self.log_tree = ttk.Treeview(
            self.tab_logs, columns=cols, show="headings", selectmode="browse"
        )
        self.log_tree.heading("macro", text="Macro")
        self.log_tree.heading("status", text="Status")
        self.log_tree.heading("steps", text="Passos")
        self.log_tree.heading("duration", text="Duração (ms)")
        self.log_tree.heading("error", text="Erro")
        self.log_tree.column("macro", width=200)
        self.log_tree.column("status", width=80)
        self.log_tree.column("steps", width=80, anchor=tk.CENTER)
        self.log_tree.column("duration", width=100, anchor=tk.CENTER)
        self.log_tree.column("error", width=250)
        self.log_tree.pack(fill=tk.BOTH, expand=True, padx=4)

    def _refresh_logs(self) -> None:
        try:
            logs = _async.run(macro_service.get_execution_logs(limit=50))
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return
        self.log_tree.delete(*self.log_tree.get_children())
        for log in logs:
            macro = (
                _async.run(macro_service.get_macro(log.macro_id))
                if log.macro_id
                else None
            )
            macro_name = macro.name if macro else "-"
            steps_str = f"{log.steps_executed}/{log.steps_total}"
            duration = str(log.duration_ms) if log.duration_ms else "-"
            error = (log.error or "")[:50]
            self.log_tree.insert(
                "",
                tk.END,
                values=(macro_name, log.status, steps_str, duration, error),
            )

    # ── Common ─────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        self._refresh_macros()
        self._refresh_schedules()
        self._refresh_logs()

    def _show_about(self) -> None:
        messagebox.showinfo(
            "Sobre",
            "Alpha Macros v0.2\n"
            "Gravação e automação de desktop.\n\n"
            "Use a aba 'Gravar' para capturar suas ações\n"
            "ou crie macros manualmente na aba 'Macros'.",
        )

    def run(self) -> None:
        try:
            _async.start()
            # Inicia o agendador de macros no loop da GUI para que os
            # agendamentos disparem mesmo sem interação, apenas com a janela aberta.
            _async.in_background(self._start_gui_schedulers())
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.root.mainloop()
        finally:
            _async.stop()

    def _on_close(self) -> None:
        if input_recorder.is_recording:
            input_recorder.cancel()
        try:
            _async.run(self._stop_gui_schedulers())
        except Exception:
            pass
        _async.stop()
        self.root.destroy()

    async def _start_gui_schedulers(self) -> None:
        from app.core.config import get_settings
        from app.db.session import AsyncSessionLocal
        from app.notification import play_notification_sound, show_notification
        from app.reminders.runner import SchedulerRunner

        await macro_service.start_scheduler()
        settings = get_settings()
        if not settings.scheduler_enabled:
            return

        def _on_notify(message: str) -> None:
            play_notification_sound()
            show_notification("ALPHA - Lembrete", message)

        self._reminder_runner = SchedulerRunner(
            AsyncSessionLocal,
            interval_seconds=settings.scheduler_interval_seconds,
            on_notify=_on_notify,
        )
        await self._reminder_runner.start()

    async def _stop_gui_schedulers(self) -> None:
        if self._reminder_runner is not None:
            await self._reminder_runner.stop()
            self._reminder_runner = None
        await macro_service.stop_scheduler()


def open_gui() -> None:
    gui = MacroGui()
    gui.run()


if __name__ == "__main__":
    open_gui()
