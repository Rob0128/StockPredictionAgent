"""Read/write the daily decision JSON and the Markdown report."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from market_journal.config import DECISIONS_DIR, REPORTS_DIR, ensure_dirs


def decision_path(run_date: str) -> Path:
    return DECISIONS_DIR / f"{run_date}.json"


def report_path(run_date: str) -> Path:
    return REPORTS_DIR / f"{run_date}.md"


def save_decision(run_date: str, record: Dict[str, Any]) -> Path:
    ensure_dirs()
    p = decision_path(run_date)
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return p


def load_decision(run_date: str) -> Optional[Dict[str, Any]]:
    p = decision_path(run_date)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_report(run_date: str, markdown: str) -> Path:
    ensure_dirs()
    p = report_path(run_date)
    p.write_text(markdown, encoding="utf-8")
    return p


def find_previous_decision(run_date: str, max_lookback: int = 7) -> Optional[Dict[str, Any]]:
    """Return the most recent decision strictly before run_date (within lookback)."""
    try:
        ref = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    for back in range(1, max_lookback + 1):
        d = (ref - timedelta(days=back)).isoformat()
        rec = load_decision(d)
        if rec is not None:
            return rec
    return None


def list_recent_decisions(run_date: str, lookback: int = 20) -> List[Dict[str, Any]]:
    """Return decisions from the lookback window (oldest first), excluding run_date."""
    try:
        ref = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        return []
    out: List[Dict[str, Any]] = []
    for back in range(lookback, 0, -1):
        d = (ref - timedelta(days=back)).isoformat()
        rec = load_decision(d)
        if rec is not None:
            out.append(rec)
    return out
