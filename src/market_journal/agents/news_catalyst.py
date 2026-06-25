"""News/Catalyst agent (gpt-4o-mini).

For the top-N candidates only, assess whether the recent price move is backed
by a real, source-identifiable catalyst, or whether it is likely noise. Keeps
cost low by reasoning over a compact summary, not raw article text.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from market_journal.agents.llm import get_llm, model_name


class _CatalystVerdict(BaseModel):
    is_real_catalyst: bool = Field(description="True if a concrete catalyst explains the move")
    assessment: str = Field(description="One or two sentences, source-grounded and cautious")


def assess_candidate(candidate: dict, feature: dict) -> dict:
    """Return {'catalyst_is_real': bool|None, 'catalyst_assessment': str, 'model_used': str}."""
    cat = (feature or {}).get("catalyst", {})
    headlines: List[str] = cat.get("headlines", []) or []
    filing_summary = cat.get("filing_summary")
    news_count = cat.get("news_count_72h", 0)
    r1d = ((feature or {}).get("price", {}) or {}).get("return_1d")

    llm = get_llm(smart=False, temperature=0.1)
    if llm is None:
        # Deterministic fallback: a catalyst is "real" only with concrete evidence.
        is_real = bool(headlines) or bool(filing_summary)
        text = (
            f"{news_count} news item(s) in 72h"
            + (f"; filing: {filing_summary}" if filing_summary else "")
            + ("." if (headlines or filing_summary) else "; no source-backed catalyst found.")
        )
        return {
            "catalyst_is_real": is_real,
            "catalyst_assessment": text,
            "model_used": "deterministic",
        }

    structured = llm.with_structured_output(_CatalystVerdict)
    move_str = f"{r1d * 100:+.2f}%" if isinstance(r1d, (int, float)) else "n/a"
    headlines_block = "\n".join(f"- {h}" for h in headlines[:8]) or "- (none)"
    prompt = (
        "You are a cautious equity research assistant. For PAPER tracking only, "
        "judge whether the stock's recent 1-day move is explained by a concrete, "
        "source-identifiable catalyst (earnings, guidance, M&A, product, regulatory, "
        "analyst action, insider/SEC filing) or is more likely noise.\n\n"
        f"Ticker: {candidate.get('ticker')}\n"
        f"1-day move: {move_str}\n"
        f"News items (72h): {news_count}\n"
        f"Headlines:\n{headlines_block}\n"
        f"Recent filing: {filing_summary or '(none)'}\n\n"
        "If there is no concrete catalyst in the provided evidence, set "
        "is_real_catalyst=false and say the move is 'unexplained from available "
        "public sources'. Do not invent catalysts. Be concise."
    )
    try:
        verdict: _CatalystVerdict = structured.invoke(prompt)
        return {
            "catalyst_is_real": verdict.is_real_catalyst,
            "catalyst_assessment": verdict.assessment.strip(),
            "model_used": model_name(smart=False),
        }
    except Exception as exc:  # noqa: BLE001 - keep workflow resilient
        return {
            "catalyst_is_real": bool(headlines or filing_summary),
            "catalyst_assessment": f"(LLM unavailable: {exc}) news_count={news_count}",
            "model_used": "deterministic",
        }
