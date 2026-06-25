"""CLI entrypoint for the Daily Paper Portfolio workflow.

Usage:
    python -m market_journal.main --date today
    python -m market_journal.main --date 2026-06-24
    python -m market_journal.main --offline      # no LLM/network, deterministic
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from typing import Optional

from market_journal.config import DISCLAIMER, ensure_dirs


def resolve_date(value: Optional[str]) -> str:
    if not value or value.lower() == "today":
        return date.today().isoformat()
    if value.lower() == "yesterday":
        from datetime import timedelta

        return (date.today() - timedelta(days=1)).isoformat()
    # Validate explicit YYYY-MM-DD.
    datetime.strptime(value, "%Y-%m-%d")
    return value


def run(run_date: str, offline: bool = False) -> dict:
    if offline:
        os.environ["MARKET_JOURNAL_OFFLINE"] = "true"
    ensure_dirs()
    # Import after env is set so settings pick up offline mode.
    from market_journal.graph import build_graph

    app = build_graph()
    initial = {"run_date": run_date, "warnings": []}
    final_state = app.invoke(initial)
    return final_state


def cli(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily Paper Portfolio Agent (paper research journal — not trading)."
    )
    parser.add_argument(
        "--date", default="today", help="Trading day to analyse: today | yesterday | YYYY-MM-DD"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run without LLM/network calls (deterministic fallbacks).",
    )
    args = parser.parse_args(argv)

    run_date = resolve_date(args.date)
    print(f"Running market journal for {run_date} (offline={args.offline})...")
    state = run(run_date, offline=args.offline)

    decision = state.get("committee_decision", {})
    picks = decision.get("picks", [])
    print(f"\nPaper picks for {run_date}: {len(picks)}")
    for p in picks:
        print(
            f"  - {p.get('action', '').upper()} {p.get('ticker')} "
            f"(confidence {p.get('confidence')}/5, {p.get('probability_band')} prob)"
        )
    review = state.get("performance_review", {})
    if review.get("reviewed_date"):
        print(
            f"\nReviewed {review['reviewed_date']}: hit rate {review.get('hit_rate')}, "
            f"avg excess {review.get('avg_excess_return_pct')}%"
        )
    warnings = state.get("warnings", [])
    if warnings:
        print(f"\n{len(warnings)} warning(s) (first few):")
        for w in warnings[:5]:
            print(f"  ! {w}")

    print(f"\nArtifacts written under data/ for {run_date}.")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
