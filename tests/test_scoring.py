"""Tests for the transparent scoring formula."""
from __future__ import annotations

from market_journal.scoring import score_breakdown, score_ticker
from market_journal.state import (
    CatalystFeatures,
    PriceFeatures,
    RelativeFeatures,
    TickerFeatures,
)


def _make(
    return_5d=0.0,
    return_20d=0.0,
    return_1d=0.0,
    rel_qqq=0.0,
    vol_vs_avg=1.0,
    volatility=0.01,
    news=0,
    earnings_risk="low",
    filing=False,
) -> TickerFeatures:
    return TickerFeatures(
        ticker="T",
        price=PriceFeatures(
            ticker="T",
            return_1d=return_1d,
            return_5d=return_5d,
            return_20d=return_20d,
            volume_vs_20d_avg=vol_vs_avg,
            volatility_20d=volatility,
            close=100.0,
        ),
        relative=RelativeFeatures(return_vs_qqq_1d=rel_qqq),
        catalyst=CatalystFeatures(
            news_count_72h=news, earnings_risk=earnings_risk, has_recent_filing=filing
        ),
    )


def test_strong_momentum_scores_higher_than_flat():
    strong = score_ticker(_make(return_5d=0.08, return_20d=0.10, rel_qqq=0.015, news=5))
    flat = score_ticker(_make())
    assert strong.candidate_score > flat.candidate_score
    assert strong.momentum_score > 0


def test_earnings_risk_penalises():
    safe = score_ticker(_make(return_5d=0.05, news=3, earnings_risk="low"))
    risky = score_ticker(_make(return_5d=0.05, news=3, earnings_risk="high"))
    assert risky.candidate_score < safe.candidate_score
    assert risky.earnings_risk_penalty > 0


def test_weak_evidence_penalty_on_unbacked_move():
    unbacked = score_ticker(_make(return_1d=0.03, news=0, filing=False))
    assert unbacked.weak_evidence_penalty > 0


def test_breakdown_total_matches_score():
    f = score_ticker(_make(return_5d=0.06, return_20d=0.04, rel_qqq=0.01, news=4))
    bd = score_breakdown(f)
    assert bd["total"] == f.candidate_score
