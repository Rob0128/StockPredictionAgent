"""Render the human-readable daily Markdown report."""
from __future__ import annotations

from typing import Any, Dict, List

from market_journal.config import BENCHMARK_PRIMARY, DISCLAIMER


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if isinstance(v, (int, float)) else "n/a"


def _yesterday_section(review: Dict[str, Any]) -> str:
    if not review or not review.get("reviewed_date"):
        return "_No prior picks to review (first run or gap day)._\n"
    lines = [
        f"Reviewed date: **{review.get('reviewed_date')}**  |  Benchmark: "
        f"**{review.get('benchmark')}** ({_fmt_pct(review.get('benchmark_return_pct'))})",
        "",
        f"- Hit rate: **{review.get('hit_rate')}**",
        f"- Avg pick return: **{_fmt_pct(review.get('avg_pick_return_pct'))}**",
        f"- Avg excess vs benchmark: **{_fmt_pct(review.get('avg_excess_return_pct'))}**",
        "",
    ]
    outcomes: List[dict] = review.get("outcomes", [])
    if outcomes:
        lines.append("| Ticker | Action | Return | Excess | Outperformed |")
        lines.append("| --- | --- | --- | --- | --- |")
        for o in outcomes:
            lines.append(
                f"| {o.get('ticker')} | {o.get('action')} | "
                f"{_fmt_pct(o.get('return_pct'))} | {_fmt_pct(o.get('excess_return_pct'))} | "
                f"{'✅' if o.get('outperformed') else '❌' if o.get('outperformed') is False else '—'} |"
            )
        lines.append("")
    if review.get("narrative"):
        lines.append(f"> {review['narrative']}")
        lines.append("")
    return "\n".join(lines)


def _candidates_section(candidates: List[dict]) -> str:
    if not candidates:
        return "_No candidates scored today._\n"
    lines = ["| Ticker | Score | Catalyst real? | Assessment |", "| --- | --- | --- | --- |"]
    for c in candidates:
        assess = (c.get("catalyst_assessment") or "")[:90]
        real = c.get("catalyst_is_real")
        real_str = "yes" if real is True else "no" if real is False else "—"
        lines.append(
            f"| {c.get('ticker')} | {c.get('candidate_score')} | {real_str} | {assess} |"
        )
    lines.append("")
    return "\n".join(lines)


def _picks_section(decision: Dict[str, Any]) -> str:
    picks: List[dict] = decision.get("picks", [])
    if not picks:
        return "_No paper picks today._\n"
    lines = []
    for i, p in enumerate(picks, 1):
        lines.append(
            f"{i}. **{p.get('action', '').upper()} {p.get('ticker')}** — "
            f"confidence {p.get('confidence')}/5, "
            f"{p.get('probability_band')} probability of {BENCHMARK_PRIMARY} "
            f"outperformance over {p.get('horizon_days')}d"
        )
        if p.get("thesis"):
            lines.append(f"   - Thesis: {p['thesis']}")
        if p.get("risk_notes"):
            lines.append(f"   - Risk: {p['risk_notes']}")
        if p.get("entry_reference_price") is not None:
            lines.append(f"   - Entry reference: {p['entry_reference_price']}")
    lines.append("")
    return "\n".join(lines)


def _rejected_section(decision: Dict[str, Any]) -> str:
    rejected: List[dict] = decision.get("rejected", [])
    if not rejected:
        return ""
    lines = ["**Rejected candidates:**", ""]
    for r in rejected:
        lines.append(f"- {r.get('ticker')} — {r.get('reason')}")
    lines.append("")
    return "\n".join(lines)


def render_report(
    run_date: str,
    review: Dict[str, Any],
    macro: Dict[str, Any],
    candidates: List[dict],
    committee_decision: Dict[str, Any],
    risk_review: Dict[str, Any],
) -> str:
    parts: List[str] = []
    parts.append(f"# Daily Paper Portfolio Report — {run_date}\n")
    parts.append(
        f"_Market regime: **{macro.get('market_regime')}** "
        f"({macro.get('notes', '')})_\n"
    )

    parts.append("## 1. Yesterday's review\n")
    parts.append(_yesterday_section(review))

    parts.append("## 2. Today's candidates\n")
    parts.append(_candidates_section(candidates))

    parts.append("## 3. Today's paper picks\n")
    parts.append(_picks_section(committee_decision))
    parts.append(_rejected_section(committee_decision))

    parts.append("## 4. Risk notes\n")
    parts.append(risk_review.get("portfolio_risk", "—") + "\n")

    if committee_decision.get("committee_summary"):
        parts.append("## 5. Committee summary\n")
        parts.append(committee_decision["committee_summary"] + "\n")

    parts.append("---\n")
    parts.append(f"> {DISCLAIMER}\n")
    parts.append(f"> Review these paper picks against {BENCHMARK_PRIMARY} on the next run.\n")
    return "\n".join(parts)
