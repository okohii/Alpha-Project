from __future__ import annotations

from pathlib import Path

from app.core.path_resolver import find_in_directories, parse_spoken_path, resolve_path


def test_parse_spoken_path_windows_drive():
    assert parse_spoken_path("c barra users barra downloads") == "C:/users/downloads"


def test_parse_spoken_path_uppercases_drive():
    assert parse_spoken_path("c dois pontos barra dados") == "C:/dados"


def test_parse_spoken_path_file_with_extension():
    assert parse_spoken_path("teste ponto txt") == "teste.txt"
    assert parse_spoken_path("relatorio ponto pdf") == "relatorio.pdf"


def test_parse_spoken_path_traco_and_underline():
    assert parse_spoken_path("meu arquivo traco final") == "meu arquivo-final"
    assert parse_spoken_path("codigo tracinho fonte") == "codigo_fonte"


def test_parse_spoken_path_preserves_simple_text():
    assert parse_spoken_path("Downloads") == "Downloads"


def test_resolve_special_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    resolved = resolve_path("downloads")
    assert resolved == home / "Downloads"


def test_resolve_relative_against_base(tmp_path):
    base = tmp_path / "base"
    resolved = resolve_path("x.py", base=base)
    assert resolved == base / "x.py"


def test_find_in_directories(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "teste.txt").write_text("oi", encoding="utf-8")
    (root / "sub").mkdir()

    found = find_in_directories("teste.txt", [root])
    assert found == root / "teste.txt"

    assert find_in_directories("nao-existe.bin", [root]) is None