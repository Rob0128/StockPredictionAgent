"""Portfolio Committee agent (gpt-4o, structured output).

The final decision maker. Receives scored candidates, catalyst assessments,
risk notes, macro regime, and the active strategy rules, then selects today's
paper picks (long / watch / avoid) with confidence and a thesis, and explains
rejections. Honours max_picks_per_day and the no-trading framing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from market_journal.agents.llm import get_llm, model_name
from market_journal.config import MAX_PICKS_PER_DAY, PREDICTION_HORIZON_DAYS
from market_journal.state import (
    CommitteeDecision,
    PaperPick,
    RejectedCandidate,
)


def _probability_band(score: float) -> str:
    if score >= 0.20:
        return "high"
    if score >= 0.08:
        return "medium"
    return "low"


def _confidence(score: float, catalyst_is_real) -> int:
    base = 1
    if score >= 0.25:
        base = 4
    elif score >= 0.15:
        base = 3
    elif score >= 0.05:
        base = 2
    if catalyst_is_real is True and base < 5:
        base += 1
    if catalyst_is_real is False and base > 1:
        base -= 1
    return max(1, min(5, base))


def _deterministic_decision(
    candidates: List[dict],
    features_by_ticker: Dict[str, dict],
    risk_notes: Dict[str, str],
    max_picks: int,
) -> CommitteeDecision:
    ranked = sorted(candidates, key=lambda c: c.get("candidate_score", 0), reverse=True)
    picks: List[PaperPick] = []
    rejected: List[RejectedCandidate] = []

    for c in ranked:
        tkr = c.get("ticker")
        score = c.get("candidate_score", 0.0)
        feat = features_by_ticker.get(tkr, {})
        price = feat.get("price", {})
        if len(picks) < max_picks and score > 0.05:
            picks.append(
                PaperPick(
                    ticker=tkr,
                    action="long",
                    probability_band=_probability_band(score),
                    confidence=_confidence(score, c.get("catalyst_is_real")),
                    horizon_days=PREDICTION_HORIZON_DAYS,
                    entry_reference_price=price.get("close"),
                    thesis=c.get("catalyst_assessment") or "Score-driven momentum/relative-strength pick.",
                    evidence_sources=c.get("evidence_sources", []),
                    reasoning_summary=f"candidate_score={score}; "
                    + (c.get("catalyst_assessment") or ""),
                    risk_notes=risk_notes.get(tkr, ""),
                    model_used="deterministic",
                )
            )
        else:
            reason = (
                "score below threshold" if score <= 0.05 else "daily pick limit reached"
            )
            rejected.append(RejectedCandidate(ticker=tkr, reason=reason))

    summary = (
        f"Selected {len(picks)} paper pick(s) by transparent score; "
        f"{len(rejected)} rejected. Paper tracking only."
    )
    return CommitteeDecision(picks=picks, rejected=rejected, committee_summary=summary)


def decide(
    candidates: List[dict],
    features_by_ticker: Dict[str, dict],
    risk_review: dict,
    macro: dict,
    rules: dict,
) -> dict:
    """Return a serialized CommitteeDecision dict."""
    max_picks = int(rules.get("max_picks_per_day", MAX_PICKS_PER_DAY))
    risk_notes = risk_review.get("ticker_risks", {})

    llm = get_llm(smart=True, temperature=0.2)
    if llm is None or not candidates:
        return _deterministic_decision(
            candidates, features_by_ticker, risk_notes, max_picks
        ).model_dump()

    lines = []
    for c in candidates:
        tkr = c.get("ticker")
        feat = features_by_ticker.get(tkr, {})
        price = feat.get("price", {})
        lines.append(
            f"- {tkr}: score={c.get('candidate_score')}, close={price.get('close')}, "
            f"1d={_pct(price.get('return_1d'))}, 5d={_pct(price.get('return_5d'))}, "
            f"catalyst_real={c.get('catalyst_is_real')}, "
            f"catalyst='{(c.get('catalyst_assessment') or '')[:120]}', "
            f"risk='{risk_notes.get(tkr, '')}'"
        )
    candidates_block = "\n".join(lines)
    rules_block = "; ".join(f"{k}={v}" for k, v in rules.items())

    structured = llm.with_structured_output(CommitteeDecision)
    prompt = (
        "You are the portfolio committee for a PAPER (non-traded) research journal. "
        "Select today's paper picks from the candidates. This is NOT a trade "
        "recommendation and you must not imply certainty.\n\n"
        f"Active rules: {rules_block}\n"
        f"Max picks today: {max_picks}\n"
        f"Market regime: {macro.get('market_regime')} ({macro.get('notes')})\n"
        f"Portfolio risk note: {risk_review.get('portfolio_risk')}\n\n"
        f"Candidates:\n{candidates_block}\n\n"
        "For each chosen pick set: action ('long' or 'watch'; use 'avoid' to "
        "explicitly flag a tempting name to stay away from), probability_band "
        "(low/medium/high) for outperforming QQQ over the next trading day, "
        "confidence 1-5, a short thesis, reasoning_summary, and risk_notes. "
        "Penalise confidence when there is no real catalyst. Reject the rest with "
        "a one-line reason. Respect the max picks limit. Set horizon_days="
        f"{PREDICTION_HORIZON_DAYS}."
    )
    try:
        decision: CommitteeDecision = structured.invoke(prompt)
        # Enforce limit and stamp audit fields from code, not the model.
        decision.picks = decision.picks[:max_picks]
        smart_model = model_name(smart=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        candidates_by_ticker = {c.get("ticker"): c for c in candidates}
        for p in decision.picks:
            # Audit fields must be system-stamped (the LLM hallucinates these).
            p.model_used = smart_model
            p.created_at = now_iso
            # Ground evidence_sources in real candidate evidence, not invented text.
            cand = candidates_by_ticker.get(p.ticker, {})
            p.evidence_sources = list(cand.get("evidence_sources", []))
            if p.entry_reference_price is None:
                price = features_by_ticker.get(p.ticker, {}).get("price", {})
                p.entry_reference_price = price.get("close")
        return decision.model_dump()
    except Exception:  # noqa: BLE001
        return _deterministic_decision(
            candidates, features_by_ticker, risk_notes, max_picks
        ).model_dump()


def _pct(v) -> str:
    return f"{v * 100:+.2f}%" if isinstance(v, (int, float)) else "n/a"
