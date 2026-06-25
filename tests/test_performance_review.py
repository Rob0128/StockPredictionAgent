"""Test the performance review feedback loop (deterministic, offline)."""
from __future__ import annotations

import os

from helpers import make_bars

os.environ["MARKET_JOURNAL_OFFLINE"] = "true"

from market_journal.agents.performance_review import review_yesterday  # noqa: E402


def test_review_computes_excess_vs_benchmark():
    previous = {
        "run_date": "2026-06-23",
        "committee_decision": {
            "picks": [
                {"ticker": "AAA", "action": "long", "thesis": "t", "confidence": 3,
                 "entry_reference_price": 100.0},
                {"ticker": "BBB", "action": "long", "thesis": "t", "confidence": 2,
                 "entry_reference_price": 50.0},
            ]
        },
    }
    # AAA +2%, BBB -1%, QQQ +0.5%
    frames = {
        "AAA": make_bars([100.0, 102.0]),
        "BBB": make_bars([50.0, 49.5]),
        "QQQ": make_bars([400.0, 402.0]),
    }
    review = review_yesterday(previous, frames, benchmark="QQQ")
    assert review["reviewed_date"] == "2026-06-23"
    assert len(review["outcomes"]) == 2
    # AAA outperformed (+2% vs +0.5%), BBB did not (-1% vs +0.5%)
    aaa = next(o for o in review["outcomes"] if o["ticker"] == "AAA")
    bbb = next(o for o in review["outcomes"] if o["ticker"] == "BBB")
    assert aaa["outperformed"] is True
    assert bbb["outperformed"] is False
    assert review["hit_rate"] == 0.5


def test_review_no_previous_decision():
    review = review_yesterday(None, {}, benchmark="QQQ")
    assert review["outcomes"] == []
    assert "No prior decision" in review["narrative"]
