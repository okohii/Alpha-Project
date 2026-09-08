from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.security import (
    AccessDeniedError,
    find_in_directories,
    is_within_allowed_directories,
    parse_spoken_path,
    resolve_path,
)


@dataclass(slots=True)
class FileSearchResult:
    path: str
    name: str
    size: int


class FileManager:
    def __init__(self, allowed_directories: list[Path] | None = None) -> None:
        self.settings = get_settings()
        self.allowed_directories = (
            list(allowed_directories) if allowed_directories is not None else []
        )
        if not self.allowed_directories:
            self.allowed_directories = list(self.settings.allowed_directories)

    def _ensure_allowed(self, path: Path) -> Path:
        candidate = path.expanduser().resolve()
        candidate_str = str(candidate)
        if not self.allowed_directories:
            raise AccessDeniedError(
                "Nenhum diretório autorizado foi configurado", candidate=candidate_str
            )
        if not is_within_allowed_directories(candidate, self.allowed_directories):
            raise AccessDeniedError(
                f"Acesso negado fora dos diretórios autorizados: {candidate}",
                candidate=candidate_str,
            )
        return candidate

    def _resolve_input(self, value: str | Path, *, search: bool = True) -> Path:
        """Normaliza a entrada (inclusive 'c barra users barra downloads'),
        localizando arquivos por nome dentro dos diretórios permitidos quando
        o texto não corresponde a um caminho absoluto existente."""
        if value is None:
            raise ValueError("O parâmetro de caminho não pode ser vazio")
        raw = str(value)
        parsed = parse_spoken_path(raw)
        candidate = Path(parsed or raw).expanduser()
        base = self.allowed_directories[0] if self.allowed_directories else Path.cwd()

        if candidate.is_absolute():
            return self._ensure_allowed(candidate)

        if search:
            match = find_in_directories(raw, self.allowed_directories)
            if match is not None:
                return self._ensure_allowed(match)

        resolved = resolve_path(raw, base=base)
        if resolved is not None:
            try:
                return self._ensure_allowed(resolved)
            except AccessDeniedError:
                pass
        return self._ensure_allowed(base / candidate)

    def list_directory(self, path: str) -> list[dict[str, Any]]:
        directory = self._resolve_input(path)
        if not directory.is_dir():
            raise FileNotFoundError(path)
        result: list[dict[str, Any]] = []
        for entry in directory.iterdir():
            result.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir()})
        return result

    def search_files(self, query: str, path: str) -> list[dict[str, Any]]:
        directory = self._resolve_input(path)
        if not directory.is_dir():
            directory = directory.parent
        results: list[dict[str, Any]] = []
        for root, _, files in os.walk(directory):
            root_path = Path(root)
            self._ensure_allowed(root_path)
            for filename in files:
                if fnmatch.fnmatch(filename.lower(), f"*{query.lower()}*"):
                    file_path = root_path / filename
                    results.append(
                        {"path": str(file_path), "name": filename, "size": file_path.stat().st_size}
                    )
        if not results:
            for entry in directory.iterdir():
                results.append(
                    {
                        "path": str(entry),
                        "name": entry.name,
                        "size": entry.stat().st_size,
                    }
                )
        return results

    def read_file(self, path: str) -> str:
        file_path = self._resolve_input(path)
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def create_file(self, path: str, content: str) -> dict[str, Any]:
        file_path = self._resolve_input(path, search=False)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"path": str(file_path), "created": True}

    def create_directory(self, path: str) -> dict[str, Any]:
        directory = self._resolve_input(path, search=False)
        directory.mkdir(parents=True, exist_ok=True)
        return {"path": str(directory), "created": True, "is_dir": True}

    def file_info(self, path: str) -> dict[str, Any]:
        file_path = self._resolve_input(path)
        stat = file_path.stat()
        return {
            "path": str(file_path),
            "name": file_path.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "is_dir": file_path.is_dir(),
        }

    def open_with_default_app(self, path: str) -> dict[str, Any]:
        """Abre um arquivo ou pasta com o aplicativo padrão do sistema."""
        file_path = self._ensure_allowed(self._resolve_input(path, search=True))
        if not file_path.exists():
            raise FileNotFoundError(path)
        open_with_system(file_path)
        return {"path": str(file_path), "opened": True, "is_dir": file_path.is_dir()}


def open_with_system(target: Path) -> None:
    """Abre arquivo/pasta com o app padrão do SO."""
    import os as _os
    import platform as _platform
    import subprocess as _subprocess

    target = target.expanduser().resolve()
    system = _platform.system()
    if system == "Windows":
        _os.startfile(str(target))
    elif system == "Darwin":
        _subprocess.Popen(["open", str(target)])
    else:
        _subprocess.Popen(["xdg-open", str(target)])