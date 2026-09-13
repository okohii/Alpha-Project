from __future__ import annotations

from app.memory.repository import keyword_overlap_score
from app.services.health.metrics import Metrics


def test_portuguese_stopwords_do_not_drive_memory_overlap() -> None:
    assert keyword_overlap_score("o que é isso", "isso") == 0.0
    assert keyword_overlap_score("abrir navegador", "abrir o navegador") > 0.0


def test_metrics_histograms_are_bounded_and_prometheus_compatible() -> None:
    metrics = Metrics()
    for index in range(3000):
        metrics.observe("alpha_latency_seconds", index / 1000.0, labels={"route": 'local"test'})
    rendered = metrics.render()
    assert "# TYPE alpha_latency_seconds histogram" in rendered
    assert 'route="local\\\"test"' in rendered
    assert rendered.count("alpha_latency_seconds_bucket") >= 2


def test_metrics_does_not_accumulate_unbounded_histogram_samples() -> None:
    metrics = Metrics()
    for index in range(3000):
        metrics.observe("alpha_latency_seconds", float(index))
    assert len(metrics._histograms["alpha_latency_seconds"]) <= 2048
