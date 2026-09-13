from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

import app.skills.computer.service as apps_module
from app.skills.computer.service import (
    AppCatalogEntry,
    ApplicationLauncher,
    InstalledAppsProvider,
    _clean_app_name,
    _norm,
    _normalize_url,
    _strip_filler,
)
from app.skills.computer.tools.application import (
    ListAppsTool,
    OpenAppTool,
    OpenUrlTool,
)
from app.skills.files.service import FileManager


def test_strip_filler_removes_leading_words():
    assert _strip_filler("abra o chrome") == "chrome"
    assert _strip_filler("abra o aplicativo bloco de notas") == "bloco de notas"
    assert _strip_filler("iniciar o excel") == "excel"
    assert _strip_filler("chrome") == "chrome"


def test_norm_removes_accents_and_case():
    assert _norm("Bloco de Notas") == "bloco de notas"
    assert _norm("Área de Trabalho") == "area de trabalho"


def test_app_catalog_matches_entries():
    catalog = ApplicationLauncher()
    entry = catalog._find_entry("chrome")
    assert entry is not None and entry.key == "chrome"
    assert catalog._find_entry("bloco de notas").key == "notepad"
    assert catalog._find_entry("excel").key == "excel"


def test_launcher_resolves_known_command(tmp_path):
    executable = tmp_path / "faketool.exe"
    executable.write_text("", encoding="utf-8")

    launcher = ApplicationLauncher(
        catalog=[
            AppCatalogEntry(
                "faketool",
                ["faketool", "ferramenta falsa"],
                commands=["faketool"],
                hints=[str(executable)],
            )
        ]
    )
    resolved = launcher.resolve("faketool")
    assert resolved["app"] == "faketool"
    assert Path(resolved["path"]) == executable


def test_launcher_resolves_por_alias(tmp_path):
    executable = tmp_path / "myeditor.exe"
    executable.write_text("", encoding="utf-8")

    launcher = ApplicationLauncher(
        catalog=[
            AppCatalogEntry(
                "myeditor",
                ["meu editor", "editor"],
                commands=["myeditor"],
                hints=[str(executable)],
            )
        ]
    )
    assert launcher.resolve("abra o meu editor")["app"] == "myeditor"


def test_launcher_resolves_unknown_raises_error():
    launcher = ApplicationLauncher(catalog=[])
    with pytest.raises(ValueError):
        launcher.resolve("aplicativo que nao existe xyz123")


def test_file_manager_resolves_spoken_path(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "teste.txt").write_text("conteúdo qualquer", encoding="utf-8")
    manager = FileManager([allowed])

    content = manager.read_file("teste ponto txt")
    assert content == "conteúdo qualquer"


def test_file_manager_reads_with_spoken_windows_path(tmp_path):
    allowed = tmp_path / "downloads"
    allowed.mkdir()
    (allowed / "relatorio.txt").write_text("oi", encoding="utf-8")
    manager = FileManager([allowed])

    relative = str(allowed.relative_to(tmp_path.anchor))
    spoken = f"{tmp_path.drive.lower()} barra {relative} barra relatorio ponto txt"
    assert manager.read_file(spoken) == "oi"


def test_open_with_system_opens_nonexistent_raises(tmp_path):
    manager = FileManager([tmp_path])
    with pytest.raises(FileNotFoundError):
        manager.open_with_default_app("arquivo-que-nao-existe.txt")


def test_clean_app_name_removes_suffix_notes():
    assert _clean_app_name("Google Chrome (x86)") == "Google Chrome"
    assert _clean_app_name("  Notepad++  ") == "Notepad++"
    assert _clean_app_name("Paint.net") == "Paint.net"


def test_provider_discovers_apps_from_start_menu(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "Google Chrome.lnk").write_text("", encoding="utf-8")
    (root / "Subpasta").mkdir()
    (root / "Subpasta" / "Notepad.lnk").write_text("", encoding="utf-8")
    monkeypatch.setattr(apps_module, "_start_menu_roots", lambda: [root])

    provider = InstalledAppsProvider()
    discovered = provider.discover()

    names = {app.name for app in discovered}
    assert "Google Chrome" in names
    assert "Notepad" in names


def test_provider_finds_app_by_spoken_name(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "Google Chrome.lnk").write_text("", encoding="utf-8")
    monkeypatch.setattr(apps_module, "_start_menu_roots", lambda: [root])

    provider = InstalledAppsProvider()
    assert provider.find("chrome") is not None
    assert provider.find("chrome").name == "Google Chrome"
    assert provider.find("bloco de notas") is None


def test_launcher_resolves_installed_app_when_catalog_empty(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "MyCustomApp.lnk").write_text("", encoding="utf-8")
    monkeypatch.setattr(apps_module, "_start_menu_roots", lambda: [root])

    launcher = ApplicationLauncher(catalog=[], installed=InstalledAppsProvider())
    resolved = launcher.resolve("my custom app")
    assert resolved["app"] == "MyCustomApp"
    assert Path(resolved["path"]) == root / "MyCustomApp.lnk"


def test_list_apps_tool_includes_installed(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "Video Editor.lnk").write_text("", encoding="utf-8")
    monkeypatch.setattr(apps_module, "_start_menu_roots", lambda: [root])

    tool = ListAppsTool(ApplicationLauncher(installed=InstalledAppsProvider()))
    result = asyncio.run(tool.execute())
    assert result.success
    assert any(app["app"] == "Video Editor" for app in result.data["apps"])
    assert result.data["total_installed"] >= 1
    assert "chrome" in result.data["known_catalog"]


def test_normalize_url_adds_https():
    assert _normalize_url("github.com") == "https://github.com"
    assert _normalize_url("https://github.com") == "https://github.com"
    assert _normalize_url("localhost:8000") == "https://localhost:8000"


def test_launch_passes_url_args_to_executable(tmp_path, monkeypatch):
    executable = tmp_path / "fakebrowser.exe"
    executable.write_text("", encoding="utf-8")
    launcher = ApplicationLauncher(
        catalog=[
            AppCatalogEntry(
                "fakebrowser", ["navegador"], commands=[], hints=[str(executable)]
            )
        ],
        installed=InstalledAppsProvider(),
    )
    captured = {}
    monkeypatch.setattr(
        apps_module.subprocess,
        "Popen",
        lambda command, *args, **kwargs: captured.update(command=command),
    )
    result = launcher.launch("fakebrowser", args=["https://github.com"])
    assert result["launched"] is True
    assert captured["command"][0] == str(executable)
    assert captured["command"][1:] == ["https://github.com"]


def test_open_url_tool_uses_specified_browser(monkeypatch):
    launcher = ApplicationLauncher()
    captured = {}
    monkeypatch.setattr(
        launcher,
        "launch",
        lambda browser, path=None, args=None: captured.update(
            browser=browser, args=args
        )
        or {"app": browser, "launched": True},
    )
    tool = OpenUrlTool(launcher)
    result = asyncio.run(tool.execute(url="github.com", browser="chrome"))
    assert result.success
    assert captured["browser"] == "chrome"
    assert captured["args"] == ["https://github.com"]


def test_open_url_tool_falls_back_to_default_browser(monkeypatch):
    opened = {}
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: opened.update(url=url),
    )
    tool = OpenUrlTool(ApplicationLauncher())
    result = asyncio.run(tool.execute(url="youtube.com"))
    assert result.success
    assert result.data["browser"] == "default"
    assert opened["url"] == "https://youtube.com"


def test_open_app_tool_opens_in_monitor(monkeypatch):
    executable = "C:/apps/notepad.exe"
    launched = {}

    class FakeLauncher:
        def resolve(self, name):
            return {"app": "notepad", "path": executable}

    monkeypatch.setattr(
        "app.skills.computer.tools.application.launch_on_monitor",
        lambda path, monitor, args=None: launched.update(path=path, monitor=monitor, args=args)
        or {"path": executable, "app": "notepad", "moved": True, "monitor": monitor},
    )
    tool = OpenAppTool(FakeLauncher())
    result = asyncio.run(tool.execute(app="bloco de notas", monitor=2))
    assert result.success
    assert launched["path"] == executable
    assert launched["monitor"] == 2


def test_open_app_tool_invalid_monitor_is_rejected():
    class FakeLauncher:
        def resolve(self, name):
            return {"app": "notepad", "path": "C:/apps/notepad.exe"}

    tool = OpenAppTool(FakeLauncher())
    result = asyncio.run(tool.execute(app="bloco de notas", monitor=0))
    assert not result.success
    assert "Monitor" in str(result.error)


def test_open_app_falls_back_to_site_when_app_not_installed(monkeypatch):
    opened = {}
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: opened.update(url=url) or "C:/apps/zen.exe",
    )
    tool = OpenAppTool(ApplicationLauncher(catalog=[]))
    result = asyncio.run(tool.execute(app="linkedin"))
    assert result.success
    assert result.data["site"] is True
    assert result.data["url"] == "https://www.linkedin.com"
    assert result.data["method"] == "browser"
    assert opened["url"] == "https://www.linkedin.com"


def test_open_app_site_fallback_prefers_provided_url(monkeypatch):
    opened = {}
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: opened.update(url=url) or None,
    )
    tool = OpenAppTool(ApplicationLauncher(catalog=[]))
    result = asyncio.run(tool.execute(app="github", url="github.com/okohii"))
    assert result.success
    assert result.data["url"] == "https://github.com/okohii"
    assert opened["url"] == "https://github.com/okohii"


def test_open_app_site_fallback_still_errors_for_unknown_app(monkeypatch):
    tool = OpenAppTool(ApplicationLauncher(catalog=[]))
    result = asyncio.run(tool.execute(app="aplicativo que nao existe xyz123"))
    assert not result.success
    assert "não encontrado" in str(result.error)


def test_open_url_reuses_recently_opened_browser(monkeypatch):
    launcher = ApplicationLauncher()
    launcher.last_launched_browser = "chrome"
    launcher._last_browser_ts = time.monotonic()
    captured = {}
    monkeypatch.setattr(
        launcher,
        "launch",
        lambda browser, path=None, args=None: captured.update(browser=browser, args=args)
        or {"app": browser, "launched": True},
    )
    result = asyncio.run(OpenUrlTool(launcher).execute(url="github.com"))
    assert result.success
    assert result.data["method"] == "browser"
    assert result.data["browser"] == "chrome"
    assert captured["args"] == ["https://github.com"]
    assert launcher.last_launched_browser is None


def test_open_url_ignores_stale_recent_browser(monkeypatch):
    launcher = ApplicationLauncher()
    launcher.last_launched_browser = "chrome"
    launcher._last_browser_ts = time.monotonic() - 60.0
    opened = {}
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: opened.update(url=url),
    )
    result = asyncio.run(OpenUrlTool(launcher).execute(url="youtube.com"))
    assert result.success
    assert result.data["browser"] == "default"
    assert opened["url"] == "https://youtube.com"


def test_open_url_dedupes_identical_url_within_window(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: called.append(url) or None,
    )
    tool = OpenUrlTool(ApplicationLauncher())
    first = asyncio.run(tool.execute(url="https://github.com/okohii"))
    second = asyncio.run(tool.execute(url="github.com/okohii"))
    assert first.success and second.success
    assert called == ["https://github.com/okohii"]
    assert second.data.get("deduped") is True


def test_open_url_not_deduped_after_window(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: called.append(url) or None,
    )
    tool = OpenUrlTool(ApplicationLauncher())
    asyncio.run(tool.execute(url="github.com"))
    tool._last_url_ts = time.monotonic() - 20.0
    asyncio.run(tool.execute(url="github.com"))
    assert called == ["https://github.com", "https://github.com"]


def test_open_url_reports_default_browser_executable(monkeypatch):
    opened = {}
    monkeypatch.setattr(
        "app.skills.computer.tools.application._open_url_default",
        lambda url: opened.update(url=url) or "C:/apps/zen.exe",
    )
    result = asyncio.run(OpenUrlTool(ApplicationLauncher()).execute(url="github.com"))
    assert result.success
    assert result.data["method"] == "browser"
    assert result.data["executable"] == "C:/apps/zen.exe"


def test_parse_shell_exe_extracts_quoted_executable():
    assert (
        apps_module._parse_shell_exe(
            '"C:\\Program Files\\Zen Browser\\zen.exe" --osint "%1"'
        )
        == "C:\\Program Files\\Zen Browser\\zen.exe"
    )
    assert (
        apps_module._parse_shell_exe("C:\\Tools\\firefox.exe -osint")
        == "C:\\Tools\\firefox.exe"
    )
    assert apps_module._parse_shell_exe("") == ""