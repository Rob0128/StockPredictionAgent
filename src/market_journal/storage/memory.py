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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from market_journal.config import MEMORY_FILE, ensure_dirs

PROMOTION_THRESHOLD = 3  # in-window appearances required to promote a lesson
PROMOTION_WINDOW = 60  # over this many recent runs (~12 trading weeks)
MIN_DISTINCT_WEEKS = 2  # appearances must span >= this many separate weeks
RUNS_PER_WEEK = 5  # trading days per week, for date-less period bucketing
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
        "run_counter": 0,
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


LessonMatcher = Callable[[str, List[str]], Optional[int]]


def _find_match(
    text: str,
    items: List[Dict[str, Any]],
    lesson_matcher: Optional[LessonMatcher],
) -> Optional[int]:
    """Return the index of the existing item that means the same as `text`.

    Exact normalized-text equality is tried first (cheap, deterministic). If no
    exact match and a semantic `lesson_matcher` is supplied, ask it to decide
    whether the new text is a paraphrase of any existing item. Returns None when
    nothing matches.
    """
    if not items:
        return None
    key = _norm(text)
    for i, it in enumerate(items):
        if _norm(it.get("text", "")) == key:
            return i
    if lesson_matcher is not None:
        idx = lesson_matcher(text, [it.get("text", "") for it in items])
        if isinstance(idx, int) and 0 <= idx < len(items):
            return idx
    return None


def _period_key(current_run: int, run_date: Optional[str]) -> str:
    """Return a calendar-week key for an appearance.

    Uses the ISO year-week of `run_date` when available so appearances are
    grouped by real weeks; falls back to bucketing by run index (~5 trading
    days per week) when no date is supplied (e.g. in tests).
    """
    if run_date:
        try:
            d = datetime.strptime(run_date, "%Y-%m-%d").date()
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            pass
    return f"run-{current_run // RUNS_PER_WEEK}"


def _in_window(lesson: Dict[str, Any], current_run: int) -> List[Dict[str, Any]]:
    """Appearances still inside the promotion window."""
    return [
        a
        for a in lesson.get("appearances", [])
        if a.get("run", 0) > current_run - PROMOTION_WINDOW
    ]


def _record_appearance(
    lesson: Dict[str, Any], current_run: int, run_date: Optional[str]
) -> None:
    """Log that a lesson was seen this run (with its week) and prune stale hits."""
    apps = list(lesson.get("appearances", []))
    apps.append({"run": current_run, "week": _period_key(current_run, run_date)})
    apps = [a for a in apps if a.get("run", 0) > current_run - PROMOTION_WINDOW]
    lesson["appearances"] = apps
    lesson["count"] = len(apps)


def _qualifies_for_promotion(lesson: Dict[str, Any], current_run: int) -> bool:
    """A lesson promotes only with enough in-window hits across separate weeks.

    Legacy lessons that predate appearance tracking fall back to their raw
    cumulative `count` (with no week information available).
    """
    apps = lesson.get("appearances")
    if apps:
        in_window = _in_window(lesson, current_run)
        distinct_weeks = len({a.get("week") for a in in_window})
        return len(in_window) >= PROMOTION_THRESHOLD and distinct_weeks >= MIN_DISTINCT_WEEKS
    return int(lesson.get("count", 1)) >= PROMOTION_THRESHOLD


def integrate_update(
    memory: Dict[str, Any],
    new_observations: List[str],
    new_tentative_lessons: List[str],
    performance_summary: Dict[str, Any],
    lesson_matcher: Optional[LessonMatcher] = None,
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge an agent's proposed update conservatively and apply promotion logic.

    - Observations are appended (capped, deduped).
    - Tentative lessons record each run they were seen in, tagged with the
      calendar week. Matching is semantic when `lesson_matcher` is provided (an
      LLM judges paraphrases), and falls back to exact normalized-text equality.
    - A lesson is promoted only once it appears >= PROMOTION_THRESHOLD times
      within the last PROMOTION_WINDOW runs AND across >= MIN_DISTINCT_WEEKS
      separate weeks — so a single unusual week cannot promote a rule on its own.
    """
    mem = json.loads(json.dumps(memory))  # deep copy

    # Advance the run clock (one integrate_update call == one run).
    current_run = int(mem.get("run_counter", 0)) + 1
    mem["run_counter"] = current_run

    # Observations (rolling, deduped, capped).
    obs = mem.get("observations", [])
    existing_obs = {_norm(o.get("text", "")) for o in obs}
    for text in new_observations:
        if text and _norm(text) not in existing_obs:
            obs.append({"text": text})
            existing_obs.add(_norm(text))
    mem["observations"] = obs[-MAX_OBSERVATIONS:]

    # Tentative lessons (record this run's appearance; add new ones).
    lessons = mem.get("tentative_lessons", [])
    promoted = mem.get("promoted_rules", [])
    for text in new_tentative_lessons:
        if not text:
            continue
        # Already captured as a permanent rule? Don't re-open it as tentative.
        if _find_match(text, promoted, lesson_matcher) is not None:
            continue
        i = _find_match(text, lessons, lesson_matcher)
        if i is not None:
            _record_appearance(lessons[i], current_run, run_date)
        else:
            new_lesson = {"text": text}
            _record_appearance(new_lesson, current_run, run_date)
            lessons.append(new_lesson)

    # Promotion: enough in-window hits across separate weeks graduate to rules.
    remaining: List[Dict[str, Any]] = []
    for lesson in lessons:
        if _qualifies_for_promotion(lesson, current_run):
            if _find_match(lesson["text"], promoted, lesson_matcher) is None:
                promoted.append(
                    {"text": lesson["text"], "promoted_from_count": lesson.get("count", 1)}
                )
        else:
            remaining.append(lesson)
    mem["tentative_lessons"] = remaining
    mem["promoted_rules"] = promoted

    if performance_summary:
        mem["recent_performance"].update(
            {k: v for k, v in performance_summary.items() if v is not None}
        )

    return mem
