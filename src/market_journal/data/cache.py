"""Tiny JSON file cache keyed by (namespace, key, date).

Used to avoid re-hitting rate-limited APIs within a single trading day and to
support cache-only / offline dry-runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from market_journal.config import CACHE_DIR


def _safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in part)


def _path(namespace: str, key: str, date: str) -> Path:
    return CACHE_DIR / f"{_safe(namespace)}__{_safe(key)}__{_safe(date)}.json"


def read(namespace: str, key: str, date: str) -> Optional[Any]:
    """Return cached JSON for the given namespace/key/date, or None."""
    p = _path(namespace, key, date)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write(namespace: str, key: str, date: str, value: Any) -> None:
    """Persist JSON-serialisable value to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(namespace, key, date)
    try:
        p.write_text(json.dumps(value, default=str), encoding="utf-8")
    except OSError:
        pass
