from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Metrics:
    counters: Counter[str] = field(default_factory=Counter)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def as_dict(self) -> dict[str, int]:
        return dict(self.counters)
