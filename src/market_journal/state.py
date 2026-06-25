"""Pydantic models and the LangGraph state TypedDict.

Every candidate and pick carries audit fields (evidence_sources,
reasoning_summary, risk_notes, model_used, created_at) so the journal is
auditable and portfolio-presentable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Per-ticker deterministic features ────────────────────────────────────────
class PriceFeatures(BaseModel):
    ticker: str
    close: Optional[float] = None
    return_1d: Optional[float] = None
    return_5d: Optional[float] = None
    return_20d: Optional[float] = None
    return_60d: Optional[float] = None
    gap_pct: Optional[float] = None
    volume: Optional[float] = None
    volume_vs_20d_avg: Optional[float] = None
    volatility_20d: Optional[float] = None
    dist_from_ma20: Optional[float] = None
    dist_from_ma50: Optional[float] = None


class RelativeFeatures(BaseModel):
    return_vs_qqq_1d: Optional[float] = None
    return_vs_spy_1d: Optional[float] = None
    return_vs_sector_1d: Optional[float] = None
    sector_etf: Optional[str] = None


class CatalystFeatures(BaseModel):
    news_count_72h: int = 0
    headlines: List[str] = Field(default_factory=list)
    days_to_earnings: Optional[int] = None
    earnings_risk: str = "unknown"  # low | medium | high | unknown
    has_recent_filing: bool = False
    filing_types: List[str] = Field(default_factory=list)
    filing_url: Optional[str] = None
    filing_summary: Optional[str] = None


class TickerFeatures(BaseModel):
    ticker: str
    price: PriceFeatures
    relative: RelativeFeatures
    catalyst: CatalystFeatures
    # Transparent component scores (filled by scoring.py).
    momentum_score: float = 0.0
    relative_strength_score: float = 0.0
    volume_confirmation_score: float = 0.0
    catalyst_score: float = 0.0
    earnings_risk_penalty: float = 0.0
    volatility_penalty: float = 0.0
    weak_evidence_penalty: float = 0.0
    candidate_score: float = 0.0


# ── Candidates & picks ───────────────────────────────────────────────────────
class Candidate(BaseModel):
    ticker: str
    candidate_score: float
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    # Filled by the News/Catalyst agent for top-N candidates.
    catalyst_assessment: Optional[str] = None
    catalyst_is_real: Optional[bool] = None
    # Audit fields.
    evidence_sources: List[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    risk_notes: str = ""
    model_used: str = "deterministic"
    created_at: str = Field(default_factory=_utc_now)


class PaperPick(BaseModel):
    ticker: str
    action: str  # long | watch | avoid
    probability_band: str  # low | medium | high
    confidence: int = Field(ge=1, le=5)
    horizon_days: int = 1
    entry_reference_price: Optional[float] = None
    thesis: str = ""
    # Audit fields.
    evidence_sources: List[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    risk_notes: str = ""
    model_used: str = "gpt-4o"
    created_at: str = Field(default_factory=_utc_now)


class RejectedCandidate(BaseModel):
    ticker: str
    reason: str


class CommitteeDecision(BaseModel):
    """Structured output produced by the Portfolio Committee agent."""

    picks: List[PaperPick] = Field(default_factory=list)
    rejected: List[RejectedCandidate] = Field(default_factory=list)
    committee_summary: str = ""


# ── Performance review (yesterday vs benchmark) ──────────────────────────────
class PickOutcome(BaseModel):
    ticker: str
    action: str
    entry_reference_price: Optional[float] = None
    close_price: Optional[float] = None
    return_pct: Optional[float] = None
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None
    outperformed: Optional[bool] = None
    original_thesis: str = ""
    original_confidence: Optional[int] = None


class PerformanceReview(BaseModel):
    reviewed_date: Optional[str] = None
    benchmark: str = "QQQ"
    outcomes: List[PickOutcome] = Field(default_factory=list)
    hit_rate: Optional[float] = None
    avg_pick_return_pct: Optional[float] = None
    benchmark_return_pct: Optional[float] = None
    avg_excess_return_pct: Optional[float] = None
    narrative: str = ""  # filled by the performance-review reasoning


# ── Macro snapshot (small context object, not a full agent) ──────────────────
class MacroSnapshot(BaseModel):
    market_regime: str = "unknown"  # risk_on | risk_off | neutral | high_vol | unknown
    qqq_return_1d: Optional[float] = None
    spy_return_1d: Optional[float] = None
    vix_change: Optional[float] = None
    ten_year_yield_change: Optional[float] = None
    notes: str = ""


# ── LangGraph state ──────────────────────────────────────────────────────────
class GraphState(TypedDict, total=False):
    run_date: str  # YYYY-MM-DD (the trading day being analysed)
    offline: bool

    # Loaded inputs.
    memory: Dict[str, Any]
    yesterday_picks: List[Dict[str, Any]]
    yesterday_date: Optional[str]

    # Deterministic data/features.
    price_frames: Dict[str, Any]  # raw cached OHLCV keyed by symbol (dict form)
    features: List[Dict[str, Any]]  # serialized TickerFeatures
    macro: Dict[str, Any]  # serialized MacroSnapshot

    # Performance feedback loop.
    performance_review: Dict[str, Any]  # serialized PerformanceReview

    # Decision pipeline.
    candidates: List[Dict[str, Any]]  # serialized Candidate (top-N enriched)
    committee_decision: Dict[str, Any]  # serialized CommitteeDecision

    # Outputs.
    report_markdown: str
    new_memory: Dict[str, Any]

    # Transient working values (not part of the persisted record schema).
    _previous_decision: Optional[Dict[str, Any]]
    _risk_review: Dict[str, Any]

    # Diagnostics.
    warnings: List[str]
