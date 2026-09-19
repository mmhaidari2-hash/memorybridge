"""Process-local operational metrics (Prometheus text exposition)."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Tuple


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)

    def incr(self, name: str, amount: float = 1.0, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] += amount

    def render_prometheus(self) -> str:
        lines = [
            "# HELP memorybridge_requests_total Total authenticated API requests by action and outcome.",
            "# TYPE memorybridge_requests_total counter",
        ]
        with self._lock:
            items = sorted(self._counters.items(), key=lambda item: (item[0][0], item[0][1]))
            for (name, label_items), value in items:
                if label_items:
                    label_str = ",".join(f'{k}="{v}"' for k, v in label_items)
                    lines.append(f"{name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{name} {value}")
        lines.append("")
        return "\n".join(lines)


metrics = MetricsRegistry()
