"""Performance review (yesterday vs benchmark).

Mostly deterministic: compute each prior pick's 1-day return vs the benchmark
(QQQ) from today's price frames. An optional gpt-4o pass writes a short,
honest narrative distinguishing skill from market beta. Kept here (not as a
separate LLM "agent") to match the MVP node layout.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from market_journal.agents.llm import get_llm
from market_journal.features import one_day_return
from market_journal.state import PerformanceReview, PickOutcome


def review_yesterday(
    previous_decision: Optional[dict],
    price_frames: Dict[str, List[dict]],
    benchmark: str = "QQQ",
) -> dict:
    """Return a serialized PerformanceReview dict."""
    review = PerformanceReview(benchmark=benchmark)
    if not previous_decision:
        review.narrative = "No prior decision found; this is the first run or a gap day."
        return review.model_dump()

    review.reviewed_date = previous_decision.get("run_date")
    bench_ret = one_day_return(price_frames.get(benchmark, []))
    review.benchmark_return_pct = _pct(bench_ret)

    picks = (previous_decision.get("committee_decision", {}) or {}).get("picks", [])
    outcomes: List[PickOutcome] = []
    returns: List[float] = []
    excesses: List[float] = []

    for p in picks:
        tkr = p.get("ticker")
        bars = price_frames.get(tkr, [])
        ret = one_day_return(bars)
        excess = None
        outperformed = None
        if ret is not None and bench_ret is not None:
            excess = ret - bench_ret
            outperformed = excess > 0
            returns.append(ret)
            excesses.append(excess)
        outcomes.append(
            PickOutcome(
                ticker=tkr,
                action=p.get("action", "long"),
                entry_reference_price=p.get("entry_reference_price"),
                close_price=(bars[-1].get("close") if bars else None),
                return_pct=_pct(ret),
                benchmark_return_pct=_pct(bench_ret),
                excess_return_pct=_pct(excess),
                outperformed=outperformed,
                original_thesis=p.get("thesis", ""),
                original_confidence=p.get("confidence"),
            )
        )

    review.outcomes = outcomes
    if returns:
        review.avg_pick_return_pct = round(sum(returns) / len(returns) * 100, 3)
        wins = sum(1 for e in excesses if e > 0)
        review.hit_rate = round(wins / len(excesses), 3) if excesses else None
        review.avg_excess_return_pct = (
            round(sum(excesses) / len(excesses) * 100, 3) if excesses else None
        )

    review.narrative = _narrative(review)
    return review.model_dump()


def _narrative(review: PerformanceReview) -> str:
    llm = get_llm(smart=False, temperature=0.2)
    base = (
        f"Reviewed {review.reviewed_date}: {len(review.outcomes)} pick(s), "
        f"hit rate {review.hit_rate}, avg excess vs {review.benchmark} "
        f"{review.avg_excess_return_pct}%."
    )
    if llm is None or not review.outcomes:
        return base
    detail = "\n".join(
        f"- {o.ticker} ({o.action}): ret {o.return_pct}%, excess {o.excess_return_pct}%, "
        f"thesis was '{o.original_thesis[:80]}'"
        for o in review.outcomes
    )
    prompt = (
        "You review a PAPER portfolio's prior-day picks. In 2-4 sentences, honestly "
        "assess whether outperformance (if any) looks like stock-specific skill or "
        "just market beta, and whether confidence was well-calibrated. Be sober; do "
        "not overclaim.\n\n"
        f"Benchmark {review.benchmark} return: {review.benchmark_return_pct}%\n"
        f"Avg pick return: {review.avg_pick_return_pct}%, avg excess: "
        f"{review.avg_excess_return_pct}%, hit rate: {review.hit_rate}\n\n"
        f"Picks:\n{detail}"
    )
    try:
        resp = llm.invoke(prompt)
        text = getattr(resp, "content", "").strip()
        return text or base
    except Exception:  # noqa: BLE001
        return base


def _pct(v) -> Optional[float]:
    return round(v * 100, 3) if isinstance(v, (int, float)) else None
