"""Memory/Learning agent (gpt-4o).

Proposes a small number of conservative observations and tentative lessons from
today's run and the performance review. It does NOT rewrite rules — promotion of
a tentative lesson to a rule is handled deterministically in storage.memory
(>=3 appearances over the last 20 runs).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from market_journal.agents.llm import get_llm


class _LessonMatch(BaseModel):
    match_index: int = Field(
        description=(
            "0-based index of the existing lesson that expresses the SAME "
            "underlying idea as the new lesson, or -1 if none of them match."
        )
    )


def make_lesson_matcher():
    """Return a semantic matcher callable, or None when no LLM is available.

    The callable takes (new_text, existing_texts) and returns the index of the
    existing lesson that means the same thing, or None. Used by
    storage.memory.integrate_update so paraphrased lessons increment the same
    counter instead of creating near-duplicates. Falls back (via a None return)
    to the deterministic exact-text matching in storage.memory when unavailable.
    """
    llm = get_llm(smart=False, temperature=0.0)
    if llm is None:
        return None
    structured = llm.with_structured_output(_LessonMatch)

    def _match(new_text: str, existing_texts: List[str]) -> Optional[int]:
        if not existing_texts:
            return None
        listing = "\n".join(f"{i}: {t}" for i, t in enumerate(existing_texts))
        prompt = (
            "You de-duplicate a strategy journal's tentative lessons. Decide "
            "whether the NEW lesson expresses the same underlying, reusable idea "
            "as any EXISTING lesson (paraphrases and rewordings count as a match; "
            "merely sharing a topic does NOT). Return the index of the matching "
            "existing lesson, or -1 if none genuinely match.\n\n"
            f"NEW lesson:\n{new_text}\n\n"
            f"EXISTING lessons:\n{listing}"
        )
        try:
            res: _LessonMatch = structured.invoke(prompt)
            idx = res.match_index
            if isinstance(idx, int) and 0 <= idx < len(existing_texts):
                return idx
            return None
        except Exception:  # noqa: BLE001 - never break the workflow on matching
            return None

    return _match


class _MemoryProposal(BaseModel):
    observations: List[str] = Field(
        default_factory=list, description="0-3 factual notes about today's run"
    )
    tentative_lessons: List[str] = Field(
        default_factory=list, description="0-2 cautious, reusable lessons"
    )


def propose_update(
    performance_review: dict,
    committee_decision: dict,
    macro: dict,
) -> Dict[str, Any]:
    """Return {'observations': [...], 'tentative_lessons': [...], 'performance_summary': {...}}."""
    perf_summary = {
        "last_5_days_hit_rate": performance_review.get("hit_rate"),
        "last_20_days_vs_benchmark": performance_review.get("avg_excess_return_pct"),
    }

    llm = get_llm(smart=True, temperature=0.3)
    if llm is None:
        obs = []
        narrative = performance_review.get("narrative")
        if narrative:
            obs.append(narrative[:200])
        picks = committee_decision.get("picks", [])
        obs.append(f"Made {len(picks)} paper pick(s) in {macro.get('market_regime')} regime.")
        return {
            "observations": obs,
            "tentative_lessons": [],
            "performance_summary": perf_summary,
        }

    structured = llm.with_structured_output(_MemoryProposal)
    picks_block = "; ".join(
        f"{p.get('ticker')}({p.get('action')},conf {p.get('confidence')})"
        for p in committee_decision.get("picks", [])
    ) or "(none)"
    prompt = (
        "You maintain a conservative strategy memory for a PAPER research journal. "
        "Based on the day's performance review and today's picks, propose at most 3 "
        "factual observations and at most 2 cautious, reusable lessons. Do NOT "
        "overreact to a single day. Lessons should be general patterns worth tracking "
        "across runs (they only become rules after repeated evidence). Avoid "
        "ticker-specific predictions.\n\n"
        f"Market regime: {macro.get('market_regime')} ({macro.get('notes')})\n"
        f"Performance narrative: {performance_review.get('narrative')}\n"
        f"Hit rate: {performance_review.get('hit_rate')}, avg excess: "
        f"{performance_review.get('avg_excess_return_pct')}%\n"
        f"Today's picks: {picks_block}"
    )
    try:
        proposal: _MemoryProposal = structured.invoke(prompt)
        return {
            "observations": proposal.observations[:3],
            "tentative_lessons": proposal.tentative_lessons[:2],
            "performance_summary": perf_summary,
        }
    except Exception:  # noqa: BLE001
        return {
            "observations": [],
            "tentative_lessons": [],
            "performance_summary": perf_summary,
        }
