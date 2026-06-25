"""Risk/Challenge agent (gpt-4o).

Challenges the candidate set as a whole: factor crowding (e.g. all mega-cap
tech), earnings/event risk, weak evidence, chasing yesterday's move, and
excessive confidence. Produces concise per-ticker risk notes plus a portfolio-
level caution. This is the "controlled desk process" guardrail.
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

from market_journal.agents.llm import get_llm, model_name
from market_journal.config import SECTOR_ETF


class _TickerRisk(BaseModel):
    ticker: str
    risk_note: str = Field(description="One concise risk sentence for this name")


class _RiskReview(BaseModel):
    portfolio_risk: str = Field(description="Portfolio-level risk/concentration caution")
    ticker_risks: List[_TickerRisk] = Field(default_factory=list)


def _deterministic_review(candidates: List[dict], features_by_ticker: Dict[str, dict]) -> dict:
    sectors: Dict[str, int] = {}
    ticker_risks: Dict[str, str] = {}
    for c in candidates:
        tkr = c.get("ticker")
        sec = SECTOR_ETF.get(tkr, "?")
        sectors[sec] = sectors.get(sec, 0) + 1
        feat = features_by_ticker.get(tkr, {})
        cat = feat.get("catalyst", {})
        notes = []
        if cat.get("earnings_risk") in {"high", "medium"}:
            notes.append(f"earnings risk {cat.get('earnings_risk')} (in {cat.get('days_to_earnings')}d)")
        vol = (feat.get("price", {}) or {}).get("volatility_20d")
        if isinstance(vol, (int, float)) and vol > 0.03:
            notes.append("elevated volatility")
        if cat.get("news_count_72h", 0) == 0 and not cat.get("has_recent_filing"):
            notes.append("thin evidence")
        ticker_risks[tkr] = "; ".join(notes) if notes else "no major flags"

    crowded = [s for s, n in sectors.items() if n >= max(2, len(candidates) // 2 + 1)]
    portfolio_risk = (
        f"Sector concentration in {', '.join(crowded)}." if crowded
        else "No severe single-sector concentration detected."
    )
    return {"portfolio_risk": portfolio_risk, "ticker_risks": ticker_risks, "model_used": "deterministic"}


def review_candidates(candidates: List[dict], features_by_ticker: Dict[str, dict], macro: dict) -> dict:
    """Return {'portfolio_risk': str, 'ticker_risks': {ticker: note}, 'model_used': str}."""
    if not candidates:
        return {"portfolio_risk": "No candidates to review.", "ticker_risks": {}, "model_used": "deterministic"}

    llm = get_llm(smart=True, temperature=0.2)
    if llm is None:
        return _deterministic_review(candidates, features_by_ticker)

    lines = []
    for c in candidates:
        tkr = c.get("ticker")
        feat = features_by_ticker.get(tkr, {})
        price = feat.get("price", {})
        cat = feat.get("catalyst", {})
        lines.append(
            f"- {tkr}: score={c.get('candidate_score')}, "
            f"1d={_pct(price.get('return_1d'))}, 5d={_pct(price.get('return_5d'))}, "
            f"vol20={_pct(price.get('volatility_20d'))}, "
            f"sector={SECTOR_ETF.get(tkr, '?')}, "
            f"earnings_risk={cat.get('earnings_risk')}, news72h={cat.get('news_count_72h', 0)}, "
            f"catalyst_real={c.get('catalyst_is_real')}"
        )
    candidates_block = "\n".join(lines)
    structured = llm.with_structured_output(_RiskReview)
    prompt = (
        "You are a risk officer reviewing PAPER (non-traded) candidate picks. "
        "Challenge them. Flag: factor/sector crowding, earnings/event risk, weak or "
        "missing evidence, chasing yesterday's move, and overconfidence. Be concise "
        "and specific. Do not recommend trades.\n\n"
        f"Market regime: {macro.get('market_regime')} ({macro.get('notes')})\n\n"
        f"Candidates:\n{candidates_block}\n\n"
        "Return a short portfolio-level caution and one risk sentence per ticker."
    )
    try:
        review: _RiskReview = structured.invoke(prompt)
        return {
            "portfolio_risk": review.portfolio_risk.strip(),
            "ticker_risks": {r.ticker: r.risk_note.strip() for r in review.ticker_risks},
            "model_used": model_name(smart=True),
        }
    except Exception:  # noqa: BLE001
        return _deterministic_review(candidates, features_by_ticker)


def _pct(v) -> str:
    return f"{v * 100:+.2f}%" if isinstance(v, (int, float)) else "n/a"
