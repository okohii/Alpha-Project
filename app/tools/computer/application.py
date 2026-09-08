# ruff: noqa: E501 - catálogo de aplicativos é dados de linha larga por natureza
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from app.security import AccessDeniedError
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.computer.window import launch_on_monitor


def _norm(text: str) -> str:
    """Normaliza um nome falado para comparação (sem acentos, minúsculas)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w\s]", "", text)  # remove pontuação não relevante
    text = text.lower()
    text = " ".join(text.split())
    return text


def _strip_filler(text: str) -> str:
    tokens_to_strip_at_start = (
        "abrindo o",
        "abrir o",
        "abra o",
        "abre o",
        "abrir",
        "abra",
        "abre",
        "iniciar o",
        "inicie o",
        "inicia o",
        "iniciar",
        "inicie",
        "inicia",
        "execute o",
        "roda o",
        "rode o",
        "rodar",
        "roda",
        "abrir aplicativo",
        "abrir programa",
        "abra aplicativo",
        "abra programa",
        "meu",
        "minha",
        "o aplicativo",
        "o programa",
        "o app",
        "aplicativo",
        "programa",
        "app",
    )
    normalized = _norm(text)
    lowered = normalized
    for token in tokens_to_strip_at_start:
        if lowered == token:
            return ""
        if lowered.startswith(token + " "):
            lowered = lowered[len(token) + 1 :]
    return lowered


class AppCatalogEntry:
    __slots__ = ("key", "aliases", "commands", "hints")

    def __init__(
        self,
        key: str,
        aliases: list[str],
        commands: list[str] | None = None,
        hints: list[str] | None = None,
    ) -> None:
        self.key = key
        self.aliases = [_norm(alias) for alias in aliases]
        self.commands = commands or []
        self.hints = [os.path.expandvars(hint) for hint in (hints or [])]

    def matches(self, normalized: str) -> bool:
        if normalized in self.aliases:
            return True
        if normalized == self.key:
            return True
        if any(normalized in alias or alias in normalized for alias in self.aliases):
            return True
        if any(self.key in normalized for _ in (0,)):
            return True
        return False

    def exe_hints(self) -> list[str]:
        return list(self.hints)


def _appdata(*parts: str) -> str:
    return os.path.join(os.environ.get("APPDATA", ""), *parts)


def _localappdata(*parts: str) -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), *parts)


APP_CATALOG: list[AppCatalogEntry] = [
    AppCatalogEntry(
        "chrome",
        ["chrome", "google chrome", "navegador", "navegador de internet", "navegador da internet"],
        commands=["chrome"],
        hints=[
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            _localappdata(r"Google\Chrome\Application\chrome.exe"),
        ],
    ),
    AppCatalogEntry(
        "edge",
        ["edge", "microsoft edge"],
        commands=["msedge"],
        hints=[r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
    ),
    AppCatalogEntry(
        "firefox",
        ["firefox", "firefox quantum", "mozilla firefox"],
        commands=["firefox"],
        hints=[
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
    ),
    AppCatalogEntry(
        "brave",
        ["brave", "brave browser"],
        commands=["brave"],
        hints=[
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            _localappdata(r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        ],
    ),
    AppCatalogEntry(
        "opera",
        ["opera", "opera browser"],
        commands=["opera"],
        hints=[_localappdata(r"Programs\Opera\opera.exe")],
    ),
    AppCatalogEntry(
        "cmd",
        ["prompt de comando", "cmd", "command prompt", "prompt de comandos", "terminal de comando"],
        commands=["cmd"],
    ),
    AppCatalogEntry(
        "powershell",
        ["powershell", "power shell", "windows powershell"],
        commands=["powershell", "pwsh"],
    ),
    AppCatalogEntry(
        "windows terminal",
        ["windows terminal", "terminal", "terminal windows", "terminal novo"],
        commands=["wt", "windows-terminal"],
        hints=[
            r"C:\Program Files\WindowsApps\Microsoft.WindowsTerminal_*\WindowsTerminal.exe",
            _localappdata(r"Microsoft\WindowsApps\wt.exe"),
        ],
    ),
    AppCatalogEntry(
        "explorer",
        [
            "explorador de arquivos",
            "explorador",
            "explorer",
            "gerenciador de arquivos",
            "ver arquivos",
        ],
        commands=["explorer"],
    ),
    AppCatalogEntry(
        "notepad",
        ["bloco de notas", "notepad", "bloco de notas do windows"],
        commands=["notepad"],
    ),
    AppCatalogEntry(
        "notepad++",
        ["notepad mais mais", "notepad plus plus", "notepad plus", "notepadpp"],
        commands=["notepad++"],
        hints=[r"C:\Program Files\Notepad++\notepad++.exe"],
    ),
    AppCatalogEntry("calc", ["calculadora", "calc", "calculadora do windows"], commands=["calc"]),
    AppCatalogEntry("paint", ["paint", "mspaint", "paint do windows"], commands=["mspaint"]),
    AppCatalogEntry("word", ["word", "microsoft word"], commands=["winword"], hints=[r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"]),
    AppCatalogEntry("excel", ["excel", "microsoft excel"], commands=["excel"], hints=[r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"]),
    AppCatalogEntry("powerpoint", ["powerpoint", "power point", "microsoft powerpoint", "slide"], commands=["powerpnt"], hints=[r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE"]),
    AppCatalogEntry("outlook", ["outlook", "microsoft outlook", "email", "meu email"], commands=["outlook"], hints=[r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE"]),
    AppCatalogEntry("vscode", ["vscode", "visual studio code", "vs code", "code"], commands=["code"], hints=[_localappdata(r"Programs\Microsoft VS Code\Code.exe")]),
    AppCatalogEntry("visual studio", ["visual studio", "vs", "visual studio 2022"], commands=["devenv"], hints=[r"C:\Program Files\Microsoft Visual Studio\2022\*\Common7\IDE\devenv.exe"]),
    AppCatalogEntry("spotify", ["spotify", "spotify music"], commands=["spotify"], hints=[_appdata(r"Spotify\Spotify.exe"), _localappdata(r"Microsoft\WindowsApps\Spotify.exe")]),
    AppCatalogEntry("discord", ["discord", "discord app"], commands=["discord"], hints=[_localappdata(r"Discord\Update.exe"), _appdata(r"Discord\Discord.exe")]),
    AppCatalogEntry("whatsapp", ["whatsapp", "whatsapp web", "zap", "zap zap"], commands=["whatsapp"], hints=[_localappdata(r"WhatsApp\WhatsApp.exe"), _localappdata(r"Microsoft\WindowsApps\WhatsApp.exe")]),
    AppCatalogEntry("telegram", ["telegram", "telegram desktop"], commands=["telegram"], hints=[_appdata(r"Telegram Desktop\Telegram.exe")]),
    AppCatalogEntry("slack", ["slack"], commands=["slack"], hints=[_localappdata(r"slack\slack.exe")]),
    AppCatalogEntry("teams", ["teams", "microsoft teams", "teams microsoft"], commands=["teams"], hints=[_localappdata(r"Microsoft\Teams\current\Teams.exe")]),
    AppCatalogEntry("zoom", ["zoom", "zoom meeting", "zoom meetings"], commands=["zoom"], hints=[_appdata(r"Zoom\bin\Zoom.exe")]),
    AppCatalogEntry("steam", ["steam", "steam games"], commands=["steam"], hints=[r"C:\Program Files (x86)\Steam\Steam.exe"]),
    AppCatalogEntry("obs", ["obs", "obs studio", "obs studio"], commands=["obs"], hints=[_appdata(r"obs-studio\bin\64bit\obs64.exe")]),
]


def _program_files_roots() -> list[Path]:
    roots = [r"C:\Program Files", r"C:\Program Files (x86)"]
    return [Path(root) for root in roots if Path(root).exists()]


def _search_program_files(name: str, max_depth: int = 2) -> list[Path]:
    normalized = _norm(name)
    if not normalized:
        return []
    found: list[Path] = []
    for root in _program_files_roots():
        try:
            for base, dirs, files in os.walk(root):
                depth = base[len(str(root)) :].count(os.sep)
                if depth > max_depth:
                    dirs[:] = []
                    continue
                for filename in files:
                    if filename.lower().endswith((".exe", ".lnk")):
                        if normalized in _norm(filename) or normalized in _norm(Path(filename).stem):
                            found.append(Path(base) / filename)
        except OSError:
            continue
    return found


def _start_menu_roots() -> list[Path]:
    roots = [
        _appdata(r"Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]
    return [Path(root) for root in roots if root and Path(root).exists()]


def _search_start_menu(name: str, max_depth: int = 3) -> list[Path]:
    normalized = _norm(name)
    if not normalized:
        return []
    found: list[Path] = []
    for root in _start_menu_roots():
        try:
            for base, dirs, files in os.walk(root):
                depth = base[len(str(root)) :].count(os.sep)
                if depth > max_depth:
                    dirs[:] = []
                    continue
                for filename in files:
                    if filename.lower().endswith((".lnk", ".url")):
                        if normalized in _norm(filename) or normalized in _norm(Path(filename).stem):
                            found.append(Path(base) / filename)
        except OSError:
            continue
    return found


def _clean_app_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\s*\(.+?\)$", "", name).strip()
    return name


class InstalledApp:
    def __init__(self, name: str, path: Path, source: str) -> None:
        self.name = name
        self.path = path
        self.source = source

    def to_dict(self) -> dict[str, str]:
        return {"app": self.name, "path": str(self.path), "source": self.source}


def _start_menu_installed() -> list[InstalledApp]:
    apps: dict[str, Path] = {}
    for root in _start_menu_roots():
        try:
            for base, dirs, files in os.walk(root):
                depth = base[len(str(root)) :].count(os.sep)
                if depth > 2:
                    dirs[:] = []
                    continue
                for filename in files:
                    if filename.lower().endswith((".lnk", ".url")):
                        name = _clean_app_name(Path(filename).stem)
                        if name:
                            apps.setdefault(name, Path(base) / filename)
        except OSError:
            continue
    return [InstalledApp(name, path, "start menu") for name, path in apps.items()]


if os.name == "nt":
    import winreg

    _REGISTRY_UNINSTALL_ROOTS: list[tuple[Any, str]] = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
else:
    winreg = None  # type: ignore[assignment]
    _REGISTRY_UNINSTALL_ROOTS: list[tuple[Any, str]] = []


def _registry_installed() -> list[InstalledApp]:
    if os.name != "nt":
        return []
    apps: dict[str, Path] = {}
    for hive, key_path in _REGISTRY_UNINSTALL_ROOTS:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        try:
            for index in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, index))
                    try:
                        display_name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        display_icon = winreg.QueryValueEx(sub, "DisplayIcon")[0]
                        install_location = winreg.QueryValueEx(sub, "InstallLocation")[0]
                    except OSError:
                        continue
                    finally:
                        sub.Close()
                    name = _clean_app_name(str(display_name))
                    if not name or name.lower() in apps:
                        continue
                    icon = str(display_icon).split(",")[0].strip().strip('"') if display_icon else ""
                    if icon and Path(icon).exists():
                        apps[name.lower()] = InstalledApp(name, Path(icon), "registry")
                        continue
                    location = str(install_location).strip().strip('"') if install_location else ""
                    if location and Path(location).is_dir():
                        apps[name.lower()] = InstalledApp(name, Path(location), "registry")
                except OSError:
                    continue
        finally:
            key.Close()
    return list(apps.values())


class InstalledAppsProvider:
    """Descobre aplicativos instalados no Windows (Menu Iniciar + registro) com cache."""

    def __init__(self, cache_ttl: float = 300.0) -> None:
        self.cache_ttl = cache_ttl
        self._cache: list[InstalledApp] = []
        self._cache_ts = 0.0

    def discover(self, force: bool = False) -> list[InstalledApp]:
        now = time.monotonic()
        if force or not self._cache or (now - self._cache_ts) > self.cache_ttl:
            apps: dict[str, InstalledApp] = {}
            for candidate in _start_menu_installed() + _registry_installed():
                apps.setdefault(candidate.name.lower(), candidate)
            self._cache = list(apps.values())
            self._cache_ts = now
        return self._cache

    def find(self, normalized: str) -> InstalledApp | None:
        if not normalized:
            return None
        tokens = normalized.split()
        best: InstalledApp | None = None
        best_score = 0
        for app in self.discover():
            key = _norm(app.name)
            if not key:
                continue
            score = 0
            if normalized == key:
                return app
            if normalized in key:
                score = len(normalized) * 2
            else:
                score = sum(len(token) for token in tokens if token in key)
            if score > best_score:
                best, best_score = app, score
        if best is not None and best_score >= min(3, len(normalized)):
            return best
        return None


def _launch_windows(target: Path) -> None:
    os.startfile(str(target))


def _launch_posix(target: Path) -> None:
    subprocess.Popen([str(target)], close_fds=True, start_new_session=True)


def _normalize_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        return url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def _open_url_default(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url], close_fds=True, start_new_session=True)


class ApplicationLauncher:
    def __init__(
        self,
        catalog: list[AppCatalogEntry] | None = None,
        installed: InstalledAppsProvider | None = None,
    ) -> None:
        self.catalog = catalog or APP_CATALOG
        self.installed = installed or InstalledAppsProvider()

    def _find_entry(self, normalized: str) -> AppCatalogEntry | None:
        best: AppCatalogEntry | None = None
        best_score = 0
        for entry in self.catalog:
            if normalized == entry.key or normalized in entry.aliases:
                return entry
            if entry.matches(normalized):
                score = 1
                if normalized in entry.key:
                    score = 2
                if score > best_score:
                    best = entry
                    best_score = score
        return best

    def resolve(self, name: str, path: str | None = None) -> dict[str, Any]:
        normalized = _strip_filler(name)
        if not normalized:
            entry = None
        else:
            entry = self._find_entry(normalized)

        candidates: list[Path] = []
        if entry is not None:
            for command in entry.commands:
                located = shutil.which(command)
                if located:
                    candidates.append(Path(located))
            for hint in entry.exe_hints():
                if "*" in hint:
                    import glob

                    candidates.extend(Path(match) for match in glob.glob(hint))
                elif hint and Path(hint).exists():
                    candidates.append(Path(hint))

        if not candidates and normalized:
            installed_match = self.installed.find(normalized)
            if installed_match is not None:
                method = "startfile" if os.name == "nt" else "popen"
                return {
                    "app": installed_match.name,
                    "path": str(installed_match.path),
                    "method": method,
                    "source": installed_match.source,
                }
            candidates.extend(_search_program_files(normalized))
            candidates.extend(_search_start_menu(normalized))

        if not candidates:
            raise ValueError(f"Aplicativo não encontrado: {name}")

        target = candidates[0]
        return {
            "app": (entry.key if entry else _norm(name) or name),
            "path": str(target),
            "method": "startfile" if os.name == "nt" else "popen",
        }

    def launch(self, name: str, path: str | None = None, args: list[str] | None = None) -> dict[str, Any]:
        info = self.resolve(name, path=path)
        target = Path(info["path"])
        if not target.exists():
            raise FileNotFoundError(target)
        args = list(args or [])
        if args and target.suffix.lower() == ".exe":
            if os.name == "nt":
                subprocess.Popen([str(target), *args])
            else:
                subprocess.Popen([str(target), *args], close_fds=True, start_new_session=True)
        elif args:
            _open_url_default(args[0])
        elif os.name == "nt":
            _launch_windows(target)
        else:
            _launch_posix(target)
        return {**info, "launched": True, "args": args}


class OpenFileTool(Tool):
    name = "open_file"
    description = (
        "Abre um arquivo ou pasta com o aplicativo padrão do sistema. "
        "Aceita caminho normal ('C:/Users/Downloads/relatorio.txt'), caminho falado "
        "('c barra users barra downloads barra relatorio ponto txt') ou apenas o nome "
        "('relatorio.txt' — procura nas pastas permitidas)."
    )
    permission = ToolPermission.write

    def __init__(self, file_manager: Any) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = str(kwargs.get("path", ""))
            result = self.file_manager.open_with_default_app(path)
            return ToolResult(name=self.name, success=True, data=result)
        except (AccessDeniedError, OSError, ValueError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo ou pasta (normal ou 'c barra users barra downloads')",
                },
            },
            "required": ["path"],
        }


class OpenAppTool(Tool):
    name = "open_app"
    description = (
        "Abre um aplicativo/programa instalado no computador pelo nome falado ou verdadeiro. "
        "Ex.: 'abra o chrome', 'abra o bloco de notas', 'abra o excel'. Aceita 'url' opcional "
        "para abrir o app já com um endereço (ex.: 'abra o chrome no site do github', "
        "url='github.com'). Aceita 'monitor' (1, 2, ...) para abrir em um monitor específico "
        "(veja list_monitors). Localiza o executável automaticamente."

    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            app = str(kwargs.get("app", ""))
            url = _normalize_url(str(kwargs.get("url", "") or ""))
            monitor = kwargs.get("monitor")
            if monitor is not None:
                monitor = int(monitor)
                if monitor <= 0:
                    raise ValueError("Monitor deve ser um número a partir de 1 (veja list_monitors).")
                info = self.launcher.resolve(app)
                result = launch_on_monitor(info["path"], monitor, args=[url] if url else None)
                return ToolResult(name=self.name, success=True, data=result)
            args = [url] if url else None
            result = self.launcher.launch(app, args=args)
            return ToolResult(name=self.name, success=True, data=result)
        except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Nome do aplicativo a abrir"},
                "url": {
                    "type": "string",
                    "description": "Opcional: endereço/site para abrir no app (ex.: 'github.com')",
                },
                "monitor": {
                    "type": "integer",
                    "description": "Opcional: número do monitor para abrir o app (ex.: 2)",
                },
            },
            "required": ["app"],
        }


class OpenUrlTool(Tool):
    name = "open_url"
    description = (
        "Abre um endereço/site no navegador padrão ou num navegador específico. "
        "Ex.: 'entre no site do github', 'abre o github no chrome'."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = _normalize_url(str(kwargs.get("url", "") or ""))
        if not url:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe a URL a abrir."
            )
        browser = str(kwargs.get("browser", "") or "").strip()
        try:
            if browser:
                result = self.launcher.launch(browser, args=[url])
                data = {"url": url, "browser": result.get("app", browser), "method": "browser"}
            else:
                _open_url_default(url)
                data = {"url": url, "browser": "default", "method": "default"}
            return ToolResult(name=self.name, success=True, data=data)
        except (ValueError, FileNotFoundError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Endereço ou site a abrir (ex.: 'github.com')"},
                "browser": {
                    "type": "string",
                    "description": "Opcional: navegador (chrome, edge, firefox...). Se vazio, usa o padrão.",
                },
            },
            "required": ["url"],
        }


class ListAppsTool(Tool):
    name = "list_apps"
    description = (
        "Lista os aplicativos instalados no computador descobertos automaticamente "
        "(Menu Iniciar e registro do Windows) e os aliases conhecidos pelo agente."
    )
    permission = ToolPermission.read

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        installed = [app.to_dict() for app in self.launcher.installed.discover()]
        limit = int(kwargs.get("limit", 100))
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "total_installed": len(installed),
                "known_catalog": [entry.key for entry in self.launcher.catalog],
                "apps": installed[:limit],
                "truncated": len(installed) > limit,
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Quantidade máxima de apps a retornar"},
            },
        }