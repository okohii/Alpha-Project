"""Métricas leves do ALPHA — formato Prometheus text, sem dependências."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_MAX_HISTOGRAM_SAMPLES = 2048


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def incr(self, name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
        key = _label_name(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = _label_name(name, labels)
        with self._lock:
            values = self._histograms[key]
            values.append(float(value))
            if len(values) > _MAX_HISTOGRAM_SAMPLES:
                del values[: len(values) - _MAX_HISTOGRAM_SAMPLES]

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = _label_name(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key in sorted(self._counters):
                base, label = _split_name(key)
                lines.append(_format_line("counter", base, label, self._counters[key]))
            for key in sorted(self._gauges):
                base, label = _split_name(key)
                lines.append(_format_line("gauge", base, label, self._gauges[key]))
            for key in sorted(self._histograms):
                values = list(self._histograms[key])
                base, label = _split_name(key)
                total = sum(values)
                lines.extend(_format_histogram(base + "_seconds", label, values, total, len(values)))
        return "\n".join(lines) + "\n"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _label_name(name: str, labels: dict[str, str] | None) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{k}="{_escape_label(v)}"' for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


def _split_name(key: str) -> tuple[str, str]:
    if "{" in key and key.endswith("}"):
        base, _, label = key.partition("{")
        return base, "{" + label
    return key, ""


def _format_line(kind: str, base: str, label: str, value: float | int) -> str:
    return f"# TYPE {base} {kind}\n{base}{label} {value}"


def _format_histogram(base: str, label: str, values: list[float], total: float, count: int) -> list[str]:
    buckets = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    lines = [f"# TYPE {base} histogram"]
    for bucket in buckets:
        cumulative = sum(1 for value in values if value <= bucket)
        lines.append(f'{base}_bucket{{le="{bucket}"{_append_label_suffix(label)}}} {cumulative}')
    lines.append(f'{base}_bucket{{le="+Inf"{_append_label_suffix(label)}}} {count}')
    lines.append(f"{base}_sum{label} {total}")
    lines.append(f"{base}_count{label} {count}")
    return lines


def _append_label_suffix(label: str) -> str:
    if not label:
        return ""
    return "," + label[1:]


metrics = Metrics()


def start_capture() -> float:
    return time.perf_counter()


def record(kind: str, started_at: float, labels: dict[str, str] | None = None) -> float:
    elapsed = time.perf_counter() - started_at
    metrics.observe(f"alpha_{kind}_seconds", elapsed, labels)
    return elapsed


__all__ = ["Metrics", "metrics", "start_capture", "record"]
