"""Strategy memory: conservative, auditable learning state.

Structure (see seed below):
    current_rules      — active hard rules the workflow honours.
    promoted_rules     — lessons proven over time (>=3 hits in last 20 runs).
    tentative_lessons  — candidate lessons with a `count` of supporting runs.
    observations       — raw notes from recent runs (rolling, capped).
    deprecated_rules   — rules that stopped working.
    agent_weights      — soft trust weights per signal source.
    recent_performance — rolling summary stats.

The Memory agent proposes lessons/observations; promotion to a rule is handled
deterministically here so the system does not rewrite its strategy every day.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from market_journal.config import MEMORY_FILE, ensure_dirs

PROMOTION_THRESHOLD = 3  # appearances required to promote a tentative lesson
PROMOTION_WINDOW = 20  # over this many recent runs
MAX_OBSERVATIONS = 40  # cap rolling observations


def default_memory() -> Dict[str, Any]:
    return {
        "version": 1,
        "current_rules": {
            "max_picks_per_day": 3,
            "minimum_evidence_sources": 2,
            "avoid_earnings_within_days": 1,
            "benchmark": "QQQ",
            "confidence_penalty_if_no_catalyst": True,
        },
        "promoted_rules": [],
        "tentative_lessons": [
            {
                "text": "Require volume confirmation or a filing/news catalyst before high confidence.",
                "count": 1,
            }
        ],
        "observations": [],
        "deprecated_rules": [],
        "agent_weights": {
            "momentum": 1.0,
            "relative_strength": 1.0,
            "volume_confirmation": 1.0,
            "catalyst": 1.0,
            "news": 1.0,
        },
        "recent_performance": {
            "last_5_days_hit_rate": None,
            "last_20_days_vs_benchmark": None,
            "common_failure_mode": None,
        },
    }


def load_memory() -> Dict[str, Any]:
    if not MEMORY_FILE.exists():
        mem = default_memory()
        save_memory(mem)
        return mem
    try:
        mem = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_memory()
    # Backfill any missing keys from the default to stay forward-compatible.
    base = default_memory()
    for k, v in base.items():
        mem.setdefault(k, v)
    return mem


def save_memory(memory: Dict[str, Any]) -> None:
    ensure_dirs()
    MEMORY_FILE.write_text(json.dumps(memory, indent=2, default=str), encoding="utf-8")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def integrate_update(
    memory: Dict[str, Any],
    new_observations: List[str],
    new_tentative_lessons: List[str],
    performance_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge an agent's proposed update conservatively and apply promotion logic.

    - Observations are appended (capped, deduped).
    - Tentative lessons increment a counter when re-proposed.
    - A tentative lesson with count >= PROMOTION_THRESHOLD is promoted.
    """
    mem = json.loads(json.dumps(memory))  # deep copy

    # Observations (rolling, deduped, capped).
    obs = mem.get("observations", [])
    existing_obs = {_norm(o.get("text", "")) for o in obs}
    for text in new_observations:
        if text and _norm(text) not in existing_obs:
            obs.append({"text": text})
            existing_obs.add(_norm(text))
    mem["observations"] = obs[-MAX_OBSERVATIONS:]

    # Tentative lessons (increment counts; add new ones).
    lessons = mem.get("tentative_lessons", [])
    by_norm = {_norm(item.get("text", "")): item for item in lessons}
    for text in new_tentative_lessons:
        if not text:
            continue
        key = _norm(text)
        if key in by_norm:
            by_norm[key]["count"] = int(by_norm[key].get("count", 1)) + 1
        else:
            new_lesson = {"text": text, "count": 1}
            lessons.append(new_lesson)
            by_norm[key] = new_lesson

    # Promotion: move lessons that cleared the threshold into promoted_rules.
    promoted = mem.get("promoted_rules", [])
    promoted_norms = {_norm(r.get("text", "")) for r in promoted}
    remaining: List[Dict[str, Any]] = []
    for lesson in lessons:
        if int(lesson.get("count", 1)) >= PROMOTION_THRESHOLD:
            if _norm(lesson["text"]) not in promoted_norms:
                promoted.append({"text": lesson["text"], "promoted_from_count": lesson["count"]})
                promoted_norms.add(_norm(lesson["text"]))
        else:
            remaining.append(lesson)
    mem["tentative_lessons"] = remaining
    mem["promoted_rules"] = promoted

    if performance_summary:
        mem["recent_performance"].update(
            {k: v for k, v in performance_summary.items() if v is not None}
        )

    return mem
