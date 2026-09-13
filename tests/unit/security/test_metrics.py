"""Métricas prometheus do ALPHA (Fase 6.1)."""
from __future__ import annotations

from app.services.health.metrics import Metrics, record, start_capture


def test_metrics_counters_and_gauge():
    m = Metrics()
    m.incr("alpha_turns_total", labels={"mode": "local"})
    m.incr("alpha_turns_total", labels={"mode": "local"})
    m.set_gauge("alpha_sessions_current", 2)
    rendered = m.render()

    assert "alpha_turns_total{mode=\"local\"} 2" in rendered
    assert 'alpha_sessions_current 2' in rendered


def test_metrics_histogram_render():
    m = Metrics()
    m.observe("alpha_llm_turn_seconds", 0.5)
    m.observe("alpha_llm_turn_seconds", 1.2)
    rendered = m.render()
    assert "# TYPE alpha_llm_turn_seconds_seconds histogram" in rendered
    assert "alpha_llm_turn_seconds_seconds_sum 1.7" in rendered
    assert "alpha_llm_turn_seconds_seconds_count 2" in rendered


def test_record_times_and_registers_histogram():
    global_metrics = record("llm_turn", start_capture())
    assert global_metrics >= 0.0


def test_metrics_never_store_sensitive_content():
    # Métricas só guardam números; strings são apenas labels de controle.
    m = Metrics()
    m.incr("alpha_tool_calls_total", labels={"tool": "file_read", "success": "false"})
    m.observe("alpha_tts_seconds", 0.3)
    rendered = m.render()
    assert "password" not in rendered
    assert "content" not in rendered.split(" ")[0]