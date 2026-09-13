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


BROWSER_KEYS: set[str] = {
    "chrome",
    "google chrome",
    "edge",
    "microsoft edge",
    "firefox",
    "mozilla firefox",
    "brave",
    "brave browser",
    "opera",
    "opera browser",
    "zen",
    "zen browser",
    "vivaldi",
    "arc",
}

SITE_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "youtube": "https://www.youtube.com",
    "whatsapp web": "https://web.whatsapp.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "stack overflow": "https://stackoverflow.com",
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "amazon": "https://www.amazon.com.br",
    "reddit": "https://www.reddit.com",
    "tiktok": "https://www.tiktok.com",
    "chatgpt": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "notion": "https://www.notion.so",
}


def _normalize_url(value: str) -> str:
    """Coerção de URL — fonte única em ``app.security.urlpolicy``."""
    from app.security.urlpolicy import normalize_url

    return normalize_url(value)


def _parse_shell_exe(command: str) -> str:
    """Extrai o caminho do executável de um comando registrado no Windows."""
    command = (command or "").strip()
    quoted = re.match(r'^\s*"([^"]+)"', command)
    if quoted:
        return quoted.group(1).strip()
    first = command.split(None, 1)
    return first[0].strip('"') if first else ""


def default_browser_progid() -> str | None:
    """ProgId do navegador padrão (registro Windows) — fonte única."""
    if os.name != "nt":
        return None
    import winreg

    progid: str | None = None
    for root in (
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as key:
                progid, _ = winreg.QueryValueEx(key, "ProgId")
            if progid:
                break
        except OSError:
            continue
    return progid


def _default_browser_exe() -> str | None:
    """Retorna o executável do navegador padrão do sistema (somente Windows)."""
    if os.name != "nt":
        return None
    import winreg

    progid = default_browser_progid()
    if not progid:
        return None
    for hive, base in (
        (winreg.HKEY_CURRENT_USER, r"Software\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Classes"),
    ):
        try:
            with winreg.OpenKey(hive, rf"{base}\{progid}\shell\open\command") as key:
                command, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        exe = _parse_shell_exe(str(command))
        if exe and Path(exe).exists():
            return exe
    return None


def _open_url_default(url: str) -> str | None:
    """Abre a URL no navegador padrão; retorna o executável usado (None = startfile)."""
    exe = _default_browser_exe()
    if exe:
        subprocess.Popen([exe, url])
        return exe
    if os.name == "nt":
        os.startfile(url)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url], close_fds=True, start_new_session=True)
    return None


class ApplicationLauncher:
    def __init__(
        self,
        catalog: list[AppCatalogEntry] | None = None,
        installed: InstalledAppsProvider | None = None,
    ) -> None:
        self.catalog = catalog or APP_CATALOG
        self.installed = installed or InstalledAppsProvider()
        self.last_launched_browser: str | None = None
        self._last_browser_ts: float = 0.0

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
        key = _norm(info.get("app", ""))
        if key in BROWSER_KEYS:
            self.last_launched_browser = key
            self._last_browser_ts = time.monotonic()
        return {**info, "launched": True, "args": args}