from __future__ import annotations

from app.agent.router import build_default_fast_path_router


def _router():
    return build_default_fast_path_router()


def test_fastpath_abre_navegador():
    match = _router().match("abra o chrome")
    assert match is not None
    assert match.intent == "abrir_navegador"
    assert match.tool == "open_app"
    assert match.arguments == {"app": "chrome"}


def test_fastpath_abre_navegador_padrao():
    match = _router().match("abre o navegador")
    assert match is not None
    assert match.arguments == {"app": "chrome"}


def test_fastpath_abre_app():
    match = _router().match("pode abrir o spotify?")
    assert match is not None
    assert match.arguments == {"app": "spotify"}


def test_fastpath_abre_site_normaliza_url():
    match = _router().match("abre youtube.com")
    assert match is not None
    assert match.arguments["url"] == "https://youtube.com"


def test_fastpath_pesquisa_web():
    match = _router().match("pesquise sobre o clima em SP")
    assert match is not None
    assert match.intent == "pesquisar_web"
    assert match.arguments["query"] == "o clima em SP"


def test_fastpath_hora_nao_casa_sem_pattern():
    match = _router().match("que horas são?")
    assert match is not None
    assert match.intent == "hora"
    assert match.arguments == {}


def test_fastpath_mensagem_desconhecida_none():
    match = _router().match("conte uma piada sobre programadores")
    assert match is None


def test_fastpath_print_screenshot():
    match = _router().match("tire um print da tela")
    assert match is not None
    assert match.tool == "screenshot"


def test_fastpath_ler_arquivo():
    match = _router().match("leia o arquivo notas.txt")
    assert match is not None
    assert match.arguments == {"path": "notas.txt"}


def test_fastpath_gera_direto_sem_llm():
    # O roteador deve retornar match síncrono sem chamar qualquer LLM.
    match = _router().match("abra o discord")
    assert match is not None
    assert match.arguments == {"app": "discord"}
