"""Tests for the conservative strategy-memory promotion logic."""
from __future__ import annotations

from market_journal.storage.memory import (
    PROMOTION_WINDOW,
    default_memory,
    integrate_update,
)


def test_observation_dedup_and_cap():
    mem = default_memory()
    mem = integrate_update(mem, ["note A", "note A"], [], {})
    texts = [o["text"] for o in mem["observations"]]
    assert texts.count("note A") == 1


def test_tentative_lesson_increments_then_promotes():
    mem = default_memory()
    lesson = "Volume confirmation matters for momentum picks."
    # The same lesson recurring across separate weeks crosses the promotion bar.
    for d in ("2026-07-06", "2026-07-13", "2026-07-20"):
        mem = integrate_update(mem, [], [lesson], {}, run_date=d)
    promoted_texts = [r["text"] for r in mem["promoted_rules"]]
    assert lesson in promoted_texts
    # It should no longer be in tentative_lessons once promoted.
    tentative_texts = [item["text"] for item in mem["tentative_lessons"]]
    assert lesson not in tentative_texts


def test_same_week_cluster_does_not_promote():
    mem = default_memory()
    mem["tentative_lessons"] = []
    lesson = "A lesson from one strange week."
    # Three appearances, but all within the SAME calendar week (Mon-Wed).
    for d in ("2026-07-06", "2026-07-07", "2026-07-08"):
        mem = integrate_update(mem, [], [lesson], {}, run_date=d)
    # Enough count, but only one distinct week -> must NOT promote.
    assert lesson not in [r["text"] for r in mem["promoted_rules"]]
    remaining = {i["text"]: i["count"] for i in mem["tentative_lessons"]}
    assert remaining[lesson] == 3


def test_lesson_not_promoted_too_early():
    mem = default_memory()
    lesson = "A brand new tentative idea."
    mem = integrate_update(mem, [], [lesson], {})
    promoted_texts = [r["text"] for r in mem["promoted_rules"]]
    assert lesson not in promoted_texts


def test_performance_summary_merged():
    mem = default_memory()
    mem = integrate_update(mem, [], [], {"last_5_days_hit_rate": 0.6})
    assert mem["recent_performance"]["last_5_days_hit_rate"] == 0.6


def _catalyst_stub_matcher(new_text, existing_texts):
    """Deterministic stand-in for the LLM matcher: lessons about a 'catalyst'
    are treated as the same idea, so paraphrases merge onto one counter."""
    if "catalyst" in new_text.lower():
        for i, text in enumerate(existing_texts):
            if "catalyst" in text.lower():
                return i
    return None


def test_semantic_matcher_merges_paraphrases_and_promotes():
    mem = default_memory()
    # Remove the seeded lesson so we start clean and control the counts.
    mem["tentative_lessons"] = []
    variants = [
        "Require a real catalyst before high confidence.",
        "A concrete catalyst should back any high-confidence pick.",
        "Do not assign high confidence without a genuine catalyst.",
    ]
    # Space the paraphrases across separate weeks so promotion can trigger.
    for v, d in zip(variants, ("2026-07-06", "2026-07-13", "2026-07-20")):
        mem = integrate_update(
            mem, [], [v], {}, lesson_matcher=_catalyst_stub_matcher, run_date=d
        )

    # All three paraphrases collapsed onto one idea and crossed the threshold.
    promoted_texts = [r["text"] for r in mem["promoted_rules"]]
    assert variants[0] in promoted_texts  # first wording is kept as canonical
    assert len(promoted_texts) == 1
    assert mem["tentative_lessons"] == []


def test_semantic_matcher_skips_already_promoted_idea():
    mem = default_memory()
    mem["tentative_lessons"] = []
    mem["promoted_rules"] = [
        {"text": "Require a real catalyst before high confidence.", "promoted_from_count": 3}
    ]
    # A paraphrase of an already-promoted rule must not re-open a tentative lesson.
    mem = integrate_update(
        mem,
        [],
        ["A concrete catalyst should back any high-confidence pick."],
        {},
        lesson_matcher=_catalyst_stub_matcher,
    )
    assert mem["tentative_lessons"] == []
    assert len(mem["promoted_rules"]) == 1


def test_unrelated_lesson_not_merged_by_matcher():
    mem = default_memory()
    mem["tentative_lessons"] = [{"text": "Require a real catalyst.", "count": 1}]
    # No 'catalyst' -> stub returns None -> stays a separate lesson at count 1.
    mem = integrate_update(
        mem, [], ["Diversify across sectors."], {}, lesson_matcher=_catalyst_stub_matcher
    )
    texts = {item["text"]: item["count"] for item in mem["tentative_lessons"]}
    assert texts["Diversify across sectors."] == 1
    assert texts["Require a real catalyst."] == 1
    assert mem["promoted_rules"] == []


def test_appearances_outside_window_do_not_promote():
    mem = default_memory()
    mem["tentative_lessons"] = []
    lesson = "A slowly recurring idea."

    # First appearance, then let the window fully pass with unrelated runs.
    mem = integrate_update(mem, [], [lesson], {}, run_date="2026-01-05")
    for _ in range(PROMOTION_WINDOW):
        mem = integrate_update(mem, ["filler observation"], [], {})

    # Two more appearances in separate weeks: the original has now aged out of
    # the run window, so only 2 in-window hits remain (< threshold) -> no promote.
    mem = integrate_update(mem, [], [lesson], {}, run_date="2026-06-01")
    mem = integrate_update(mem, [], [lesson], {}, run_date="2026-06-08")

    promoted_texts = [r["text"] for r in mem["promoted_rules"]]
    assert lesson not in promoted_texts
    remaining = {item["text"]: item["count"] for item in mem["tentative_lessons"]}
    assert remaining[lesson] == 2  # only in-window appearances are counted
