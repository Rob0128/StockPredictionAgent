"""End-to-end graph test in offline mode, proving the closed feedback loop.

Day 1: produce picks. Day 2: read day 1's picks, score them vs QQQ, write a
review, and update memory. Network price fetch is monkeypatched with synthetic
data; no LLM or API calls are made (offline mode).
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from helpers import make_bars, rising_series

os.environ["MARKET_JOURNAL_OFFLINE"] = "true"
os.environ["MARKET_JOURNAL_USE_CACHE_ONLY"] = "true"


@pytest.fixture
def synthetic_frames():
    """A deterministic price world: each symbol gets a gently rising series."""
    from market_journal.config import all_symbols

    frames = {}
    for i, sym in enumerate(all_symbols()):
        # Vary slope slightly per symbol so scores differ.
        slope = 0.5 + (i % 5) * 0.2
        frames[sym] = make_bars(rising_series(70, 100.0, slope))
    return frames


def _patch_data(monkeypatch, frames):
    from market_journal.data import prices as prices_mod
    from market_journal.data import news as news_mod
    from market_journal.data import filings as filings_mod
    from market_journal.data import macro as macro_mod

    monkeypatch.setattr(prices_mod, "fetch_prices", lambda *a, **k: frames)
    monkeypatch.setattr(news_mod, "fetch_company_news", lambda *a, **k: [])
    monkeypatch.setattr(news_mod, "fetch_next_earnings_days", lambda *a, **k: 30)
    monkeypatch.setattr(
        filings_mod,
        "fetch_recent_filings",
        lambda *a, **k: {"has_recent_filing": False, "filing_types": [], "most_recent": None},
    )
    monkeypatch.setattr(
        macro_mod,
        "build_macro_snapshot",
        lambda *a, **k: {"market_regime": "neutral", "qqq_return_1d": 0.001, "notes": "test"},
    )


def test_end_to_end_closed_loop(tmp_path, monkeypatch, synthetic_frames):
    # Redirect all data artifacts into a temp dir so the test is isolated.
    import market_journal.config as config
    import market_journal.storage.decisions as dec
    import market_journal.storage.memory as mem

    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DECISIONS_DIR", data_dir / "decisions")
    monkeypatch.setattr(config, "REPORTS_DIR", data_dir / "reports")
    monkeypatch.setattr(config, "MEMORY_DIR", data_dir / "memory")
    monkeypatch.setattr(config, "CACHE_DIR", data_dir / "cache")
    monkeypatch.setattr(config, "MEMORY_FILE", data_dir / "memory" / "strategy_memory.json")
    monkeypatch.setattr(dec, "DECISIONS_DIR", data_dir / "decisions")
    monkeypatch.setattr(dec, "REPORTS_DIR", data_dir / "reports")
    monkeypatch.setattr(mem, "MEMORY_FILE", data_dir / "memory" / "strategy_memory.json")
    config.ensure_dirs()

    _patch_data(monkeypatch, synthetic_frames)

    from market_journal.graph import build_graph

    app = build_graph()

    day1 = (date.today() - timedelta(days=1)).isoformat()
    day2 = date.today().isoformat()

    # ── Day 1 ────────────────────────────────────────────────
    s1 = app.invoke({"run_date": day1, "warnings": []})
    rec1 = dec.load_decision(day1)
    assert rec1 is not None
    assert (data_dir / "reports" / f"{day1}.md").exists()
    picks1 = rec1["committee_decision"]["picks"]
    assert len(picks1) >= 1  # produced at least one paper pick
    # First run: nothing to review yet.
    assert s1["performance_review"].get("reviewed_date") is None

    # ── Day 2 ────────────────────────────────────────────────
    s2 = app.invoke({"run_date": day2, "warnings": []})
    review2 = s2["performance_review"]
    # The closed loop: day 2 reviewed day 1's picks against QQQ.
    assert review2["reviewed_date"] == day1
    assert len(review2["outcomes"]) == len(picks1)
    assert review2["benchmark"] == "QQQ"
    # Memory file exists and was updated.
    assert (data_dir / "memory" / "strategy_memory.json").exists()
    assert "observations" in s2["new_memory"]


def test_offline_run_writes_audit_fields(tmp_path, monkeypatch, synthetic_frames):
    import market_journal.config as config
    import market_journal.storage.decisions as dec
    import market_journal.storage.memory as mem

    data_dir = tmp_path / "data"
    for mod, attr, val in [
        (config, "DECISIONS_DIR", data_dir / "decisions"),
        (config, "REPORTS_DIR", data_dir / "reports"),
        (config, "MEMORY_DIR", data_dir / "memory"),
        (config, "CACHE_DIR", data_dir / "cache"),
        (config, "MEMORY_FILE", data_dir / "memory" / "strategy_memory.json"),
        (dec, "DECISIONS_DIR", data_dir / "decisions"),
        (dec, "REPORTS_DIR", data_dir / "reports"),
        (mem, "MEMORY_FILE", data_dir / "memory" / "strategy_memory.json"),
    ]:
        monkeypatch.setattr(mod, attr, val)
    config.ensure_dirs()
    _patch_data(monkeypatch, synthetic_frames)

    from market_journal.graph import build_graph

    today = date.today().isoformat()
    state = build_graph().invoke({"run_date": today, "warnings": []})

    for pick in state["committee_decision"]["picks"]:
        assert "evidence_sources" in pick
        assert "reasoning_summary" in pick
        assert "model_used" in pick
        assert "created_at" in pick
