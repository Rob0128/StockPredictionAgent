"""Transparent candidate scoring.

candidate_score =
    momentum_score + relative_strength_score + volume_confirmation_score
    + catalyst_score
    - earnings_risk_penalty - volatility_penalty - weak_evidence_penalty

Each component is normalised into a roughly comparable range and weighted by
config.SCORE_WEIGHTS. This is deliberately simple and explainable — not a
trained model. Tune weights later from journal history.
"""
from __future__ import annotations

from market_journal.config import SCORE_WEIGHTS
from market_journal.state import TickerFeatures


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _momentum_raw(f: TickerFeatures) -> float:
    """Blend of 5d and 20d returns, scaled so ~±10% maps near ±1."""
    r5 = f.price.return_5d or 0.0
    r20 = f.price.return_20d or 0.0
    return _clip((0.6 * r5 + 0.4 * r20) / 0.10)


def _relative_strength_raw(f: TickerFeatures) -> float:
    """1-day return vs QQQ (primary), scaled so ~±2% maps near ±1."""
    rel = f.relative.return_vs_qqq_1d
    if rel is None:
        rel = f.relative.return_vs_spy_1d
    if rel is None:
        return 0.0
    return _clip(rel / 0.02)


def _volume_confirmation_raw(f: TickerFeatures) -> float:
    """Volume vs 20d avg: 1.0x -> 0, 2.0x -> +1, <1x -> negative."""
    v = f.price.volume_vs_20d_avg
    if v is None:
        return 0.0
    return _clip(v - 1.0)


def _catalyst_raw(f: TickerFeatures) -> float:
    """News volume + a recent filing nudge."""
    score = 0.0
    n = f.catalyst.news_count_72h
    if n >= 6:
        score += 1.0
    elif n >= 3:
        score += 0.6
    elif n >= 1:
        score += 0.3
    if f.catalyst.has_recent_filing:
        score += 0.3
    return _clip(score)


def _earnings_penalty_raw(f: TickerFeatures) -> float:
    risk = f.catalyst.earnings_risk
    return {"high": 1.0, "medium": 0.5, "low": 0.0, "unknown": 0.1}.get(risk, 0.1)


def _volatility_penalty_raw(f: TickerFeatures) -> float:
    """Daily vol ~>3% is penalised; scaled so 5% maps to ~1."""
    vol = f.price.volatility_20d
    if vol is None:
        return 0.0
    return _clip(max(0.0, vol - 0.02) / 0.03, 0.0, 1.0)


def _weak_evidence_penalty_raw(f: TickerFeatures) -> float:
    """Penalise a move with no supporting news/filing evidence."""
    has_evidence = f.catalyst.news_count_72h > 0 or f.catalyst.has_recent_filing
    big_move = abs(f.price.return_1d or 0.0) > 0.015
    if big_move and not has_evidence:
        return 1.0
    if not has_evidence:
        return 0.4
    return 0.0


def score_ticker(f: TickerFeatures) -> TickerFeatures:
    w = SCORE_WEIGHTS
    f.momentum_score = w.momentum * _momentum_raw(f)
    f.relative_strength_score = w.relative_strength * _relative_strength_raw(f)
    f.volume_confirmation_score = w.volume_confirmation * _volume_confirmation_raw(f)
    f.catalyst_score = w.catalyst * _catalyst_raw(f)
    f.earnings_risk_penalty = w.earnings_risk_penalty * _earnings_penalty_raw(f)
    f.volatility_penalty = w.volatility_penalty * _volatility_penalty_raw(f)
    f.weak_evidence_penalty = w.weak_evidence_penalty * _weak_evidence_penalty_raw(f)

    f.candidate_score = round(
        f.momentum_score
        + f.relative_strength_score
        + f.volume_confirmation_score
        + f.catalyst_score
        - f.earnings_risk_penalty
        - f.volatility_penalty
        - f.weak_evidence_penalty,
        4,
    )
    return f


def score_breakdown(f: TickerFeatures) -> dict:
    return {
        "momentum": round(f.momentum_score, 4),
        "relative_strength": round(f.relative_strength_score, 4),
        "volume_confirmation": round(f.volume_confirmation_score, 4),
        "catalyst": round(f.catalyst_score, 4),
        "earnings_risk_penalty": round(-f.earnings_risk_penalty, 4),
        "volatility_penalty": round(-f.volatility_penalty, 4),
        "weak_evidence_penalty": round(-f.weak_evidence_penalty, 4),
        "total": f.candidate_score,
    }
