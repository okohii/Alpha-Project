from __future__ import annotations

from unittest.mock import patch

from app.llm.router import FaultTolerantProvider, LLMRouter


class Provider:
    async def complete(self, messages, tools=None, temperature=0.2):
        raise AssertionError("not called")


def test_hybrid_routes_short_question_local():
    router = LLMRouter(local_provider=Provider(), cloud_provider=Provider())
    with patch.object(router.settings, "llm_mode", "hybrid"):
        assert router.route_name("que horas são?") == "local"


def test_hybrid_routes_browser_workflow_cloud():
    router = LLMRouter(local_provider=Provider(), cloud_provider=Provider())
    with patch.object(router.settings, "llm_mode", "hybrid"), patch.object(router, "_cloud_available", return_value=True):
        provider = router.choose("abra o navegador, entre no GitHub e depois envie a URL")
        assert isinstance(provider, FaultTolerantProvider)


def test_hybrid_does_not_cloud_route_without_cloud():
    router = LLMRouter(local_provider=Provider(), cloud_provider=Provider())
    with patch.object(router.settings, "llm_mode", "hybrid"), patch.object(router, "_cloud_available", return_value=False):
        assert router.route_name("pesquise no navegador e depois compare os resultados") == "local"
