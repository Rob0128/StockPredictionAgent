"""Tests for the conservative strategy-memory promotion logic."""
from __future__ import annotations

from market_journal.storage.memory import (
    PROMOTION_THRESHOLD,
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
    # Repeat the lesson until it crosses the promotion threshold.
    for _ in range(PROMOTION_THRESHOLD):
        mem = integrate_update(mem, [], [lesson], {})
    promoted_texts = [r["text"] for r in mem["promoted_rules"]]
    assert lesson in promoted_texts
    # It should no longer be in tentative_lessons once promoted.
    tentative_texts = [item["text"] for item in mem["tentative_lessons"]]
    assert lesson not in tentative_texts


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
