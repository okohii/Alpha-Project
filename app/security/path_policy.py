from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Palavras faladas que costumam aparecer em transcrições de voz e que devem
# ser interpretadas como estrutura de caminho. A ordem importa: combinações
# mais específicas primeiro (ex.: "dois pontos" antes de "ponto").
_SPOKEN_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdois\s*pontos?\b", re.IGNORECASE), ":"),
    (re.compile(r"\baspas\s*duplas?\b", re.IGNORECASE), '"'),
    (re.compile(r"\bponto\s*final\b", re.IGNORECASE), "."),
    (re.compile(r"\bbarra\s*(?:invertida|reversa)\b", re.IGNORECASE), "\\\\"),
    (re.compile(r"\bbarra\b", re.IGNORECASE), "/"),
    (re.compile(r"\bsla(?:sh|che)s?\b", re.IGNORECASE), "/"),
    (re.compile(r"\bponto\b", re.IGNORECASE), "."),
    (re.compile(r"\bsubtra[çc]o\b", re.IGNORECASE), "-"),
    (re.compile(r"\bunder\s*line\b", re.IGNORECASE), "_"),
    (re.compile(r"\btra[çc]inho\b", re.IGNORECASE), "_"),
    (re.compile(r"\btra[çc]o\b|\bh[íi]fen\b", re.IGNORECASE), "-"),
    (re.compile(r"\bespa[çc]o\b", re.IGNORECASE), " "),
    (re.compile(r"\bv[íi]rgula\b", re.IGNORECASE), ","),
]

_SEPARATORS_RE = re.compile(r"\s*([\\/:._-])\s*")
_DRIVE_RE = re.compile(r"^([a-zA-Z]):(?=/|$)")
_DRIVE_NOCOLON_RE = re.compile(r"^([a-zA-Z])(?=/)")
_SPECIAL_DIRECTORIES: dict[str, str] = {
    "downloads": "Downloads",
    "download": "Downloads",
    "documentos": "Documents",
    "documents": "Documents",
    "documentos e configuracoes": "Documents",
    "meusdocumentos": "Documents",
    "meus documentos": "Documents",
    "desktop": "Desktop",
    "area de trabalho": "Desktop",
    "área de trabalho": "Desktop",
    "mesa": "Desktop",
    "imagens": "Pictures",
    "pictures": "Pictures",
    "musica": "Music",
    "música": "Music",
    "music": "Music",
    "videos": "Videos",
    "vídeos": "Videos",
}


def _normalize_ascii(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def parse_spoken_path(text: str) -> str:
    """Converte uma frase de caminho falado em um caminho com pontuação.

    Exemplos:
        "c barra users barra downloads" -> "c:/users/downloads"
        "teste ponto txt"               -> "teste.txt"
        "C dois pontos barra dados"     -> "C:/dados"
    """
    if not text:
        return ""
    value = str(text).strip()
    for pattern, replacement in _SPOKEN_TOKENS:
        value = pattern.sub(replacement, value)
    value = _SEPARATORS_RE.sub(r"\1", value)
    value = _DRIVE_RE.sub(lambda match: match.group(1).upper() + ":", value)
    value = _DRIVE_NOCOLON_RE.sub(lambda match: match.group(1).upper() + ":", value)
    return value.strip()


def _expand_special_directory(first_component: str) -> Path | None:
    key = _normalize_ascii(first_component).strip().lower()
    target = _SPECIAL_DIRECTORIES.get(key)
    if not target:
        return None
    return Path.home() / target


def resolve_path(value: str | Path, base: str | Path | None = None) -> Path | None:
    """Resolve um caminho informado pelo usuário, inclusive versão 'falada'.

    - caminhos absolutos são usados direto;
    - ~ e diretórios especiais (downloads, documentos, desktop...) são expandidos;
    - caminhos relativos são resolvidos contra `base` (ou o diretório atual).
    """
    if value is None:
        return None
    if isinstance(value, Path):
        raw_value = str(value)
    else:
        raw_value = parse_spoken_path(value)
    if not raw_value:
        return None

    candidate = Path(raw_value).expanduser()
    if candidate.parts:
        special = _expand_special_directory(candidate.parts[0])
        if special is not None:
            candidate = special.joinpath(*candidate.parts[1:])

    if not candidate.is_absolute():
        drive = _drive_of(raw_value)
        if drive:
            rest = raw_value[len(drive) + 1 :].lstrip("/\\")
            candidate = Path(f"{drive.upper()}:/").joinpath(rest)
        else:
            resolve_base = Path(base).expanduser() if base else Path.cwd()
            candidate = resolve_base / candidate

    return _finalize(candidate)


def _drive_of(raw_value: str) -> str | None:
    """Detecta letra de unidade sem separador de raiz, ex.: 'c:desktop'."""
    match = re.match(r"^([a-zA-Z]):(.)", raw_value)
    if not match:
        return None
    letter, following = match.groups()
    if following in "/\\":
        return None
    return letter


def _finalize(candidate: Path) -> Path:
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate


def is_spoken_path(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in ("barra", "slashe", "slash", "ponto", "doispontos"))


def find_in_directories(name: str, directories: list[Path], max_depth: int = 6) -> Path | None:
    """Procura um arquivo/pasta pelo nome em diretórios permitidos."""
    if not directories:
        return None
    candidate = Path(parse_spoken_path(name) or name).expanduser()
    search = candidate.name
    if not search:
        return None
    for directory in directories:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            continue
        direct = root / search
        if direct.exists():
            return direct
    for directory in directories:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            continue
        try:
            for found in root.rglob(search):
                rel = found.relative_to(root)
                if len(rel.parts) > max_depth:
                    continue
                return found
        except OSError:
            continue
    return None


def is_within_allowed_directories(candidate: Path, allowed_directories: list[Path]) -> bool:
    resolved_candidate = candidate.expanduser().resolve()
    for allowed in allowed_directories:
        try:
            resolved_candidate.relative_to(allowed.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False