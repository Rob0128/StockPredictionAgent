"""Helpers to synthesise OHLCV bars for deterministic tests."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List


def make_bars(closes: List[float], volumes: List[float] = None, start="2026-06-01") -> List[dict]:
    if volumes is None:
        volumes = [1_000_000] * len(closes)
    d0 = date.fromisoformat(start)
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            {
                "date": (d0 + timedelta(days=i)).isoformat(),
                "open": c,
                "high": c * 1.01,
                "low": c * 0.99,
                "close": c,
                "volume": volumes[i] if i < len(volumes) else volumes[-1],
            }
        )
    return bars


def rising_series(n: int = 70, start: float = 100.0, step: float = 1.0) -> List[float]:
    return [start + step * i for i in range(n)]
