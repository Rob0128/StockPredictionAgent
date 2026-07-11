"""LangGraph workflow wiring.

Deterministic nodes gather data and compute features/scores; LLM agents apply
judgement (news/catalyst, risk, committee, memory). State flows linearly:

    load_memory -> load_yesterday -> fetch_prices -> calculate_features
    -> score_yesterday -> fetch_context -> build_candidates
    -> news_catalyst -> risk -> committee
    -> write_decision -> render_report -> update_memory
"""
from __future__ import annotations

from typing import Dict, List

from langgraph.graph import END, START, StateGraph

from market_journal import report as report_mod
from market_journal.agents import memory_agent, news_catalyst, performance_review, risk
from market_journal.agents import portfolio_committee as committee
from market_journal.config import (
    BENCHMARK_PRIMARY,
    BENCHMARK_SECONDARY,
    SECTOR_ETF,
    TOP_N_CANDIDATES,
    UNIVERSE,
    all_symbols,
)
from market_journal.data import filings as filings_client
from market_journal.data import macro as macro_client
from market_journal.data import news as news_client
from market_journal.data import prices as prices_client
from market_journal.features import build_ticker_features, one_day_return
from market_journal.scoring import score_breakdown, score_ticker
from market_journal.state import Candidate, GraphState, TickerFeatures
from market_journal.storage import decisions as decisions_store
from market_journal.storage import memory as memory_store


# ── Deterministic nodes ──────────────────────────────────────────────────────
def node_load_memory(state: GraphState) -> dict:
    return {"memory": memory_store.load_memory(), "warnings": state.get("warnings", [])}


def node_load_yesterday(state: GraphState) -> dict:
    prev = decisions_store.find_previous_decision(state["run_date"])
    return {
        "yesterday_picks": (prev or {}).get("committee_decision", {}).get("picks", []),
        "yesterday_date": (prev or {}).get("run_date"),
        "_previous_decision": prev,  # transient, not in schema but allowed (total=False)
    }


def node_fetch_prices(state: GraphState) -> dict:
    warnings = state.get("warnings", [])
    frames = prices_client.fetch_prices(state["run_date"], all_symbols(), warnings=warnings)
    return {"price_frames": frames, "warnings": warnings}


def node_calculate_features(state: GraphState) -> dict:
    frames: Dict[str, List[dict]] = state["price_frames"]
    benchmark_1d = {
        "QQQ": one_day_return(frames.get(BENCHMARK_PRIMARY, [])),
        "SPY": one_day_return(frames.get(BENCHMARK_SECONDARY, [])),
    }
    sector_1d_cache: Dict[str, float] = {}
    for etf in set(SECTOR_ETF.values()):
        sector_1d_cache[etf] = one_day_return(frames.get(etf, []))

    features: List[dict] = []
    for tkr in UNIVERSE:
        sector_etf = SECTOR_ETF.get(tkr)
        sector_1d = sector_1d_cache.get(sector_etf) if sector_etf else None
        # Context (news/earnings/filings) collected in fetch_context node; here we
        # build price/relative features and leave catalyst empty placeholders.
        tf = build_ticker_features(
            ticker=tkr,
            bars=frames.get(tkr, []),
            benchmark_1d=benchmark_1d,
            sector_1d=sector_1d,
            run_date=state["run_date"],
            news_items=[],
            days_to_earnings=None,
            filings={},
        )
        features.append(tf.model_dump())
    return {"features": features}


def node_score_yesterday(state: GraphState) -> dict:
    prev = state.get("_previous_decision")
    review = performance_review.review_yesterday(
        prev, state["price_frames"], benchmark=BENCHMARK_PRIMARY
    )
    return {"performance_review": review}


def node_fetch_context(state: GraphState) -> dict:
    """Fetch news/earnings/filings per ticker and macro snapshot; enrich features."""
    warnings = state.get("warnings", [])
    run_date = state["run_date"]
    frames = state["price_frames"]

    benchmark_1d = {
        "QQQ": one_day_return(frames.get(BENCHMARK_PRIMARY, [])),
        "SPY": one_day_return(frames.get(BENCHMARK_SECONDARY, [])),
    }
    sector_1d_cache = {
        etf: one_day_return(frames.get(etf, [])) for etf in set(SECTOR_ETF.values())
    }

    enriched: List[dict] = []
    for tkr in UNIVERSE:
        news_items = news_client.fetch_company_news(tkr, run_date, warnings)
        dte = news_client.fetch_next_earnings_days(tkr, run_date, warnings)
        flt = filings_client.fetch_recent_filings(tkr, run_date, warnings)
        sector_etf = SECTOR_ETF.get(tkr)
        sector_1d = sector_1d_cache.get(sector_etf) if sector_etf else None
        tf = build_ticker_features(
            ticker=tkr,
            bars=frames.get(tkr, []),
            benchmark_1d=benchmark_1d,
            sector_1d=sector_1d,
            run_date=run_date,
            news_items=news_items,
            days_to_earnings=dte,
            filings=flt,
        )
        enriched.append(tf.model_dump())

    macro = macro_client.build_macro_snapshot(run_date, frames, warnings)
    return {"features": enriched, "macro": macro, "warnings": warnings}


def node_build_candidates(state: GraphState) -> dict:
    """Score every ticker, keep the top-N by candidate_score as candidates."""
    scored: List[TickerFeatures] = []
    for f in state["features"]:
        tf = score_ticker(TickerFeatures(**f))
        scored.append(tf)

    scored.sort(key=lambda t: t.candidate_score, reverse=True)
    top = scored[:TOP_N_CANDIDATES]

    candidates: List[dict] = []
    for tf in top:
        evidence: List[str] = []
        if tf.catalyst.news_count_72h:
            evidence.append(f"{tf.catalyst.news_count_72h} news items (Finnhub)")
        if tf.catalyst.has_recent_filing:
            evidence.append(f"SEC filing: {', '.join(tf.catalyst.filing_types)}")
        evidence.append("price/volume (yfinance)")
        cand = Candidate(
            ticker=tf.ticker,
            candidate_score=tf.candidate_score,
            score_breakdown=score_breakdown(tf),
            evidence_sources=evidence,
            reasoning_summary=f"Top-{TOP_N_CANDIDATES} by transparent score.",
            model_used="deterministic",
        )
        candidates.append(cand.model_dump())

    # Persist full scored features back so downstream nodes can look them up.
    return {
        "candidates": candidates,
        "features": [t.model_dump() for t in scored],
    }


# ── LLM agent nodes ──────────────────────────────────────────────────────────
def _features_by_ticker(state: GraphState) -> Dict[str, dict]:
    return {f["ticker"]: f for f in state.get("features", [])}


def node_news_catalyst(state: GraphState) -> dict:
    fbt = _features_by_ticker(state)
    enriched: List[dict] = []
    for c in state.get("candidates", []):
        verdict = news_catalyst.assess_candidate(c, fbt.get(c["ticker"], {}))
        c = dict(c)
        c["catalyst_is_real"] = verdict["catalyst_is_real"]
        c["catalyst_assessment"] = verdict["catalyst_assessment"]
        if verdict["model_used"] != "deterministic":
            c["model_used"] = verdict["model_used"]
        enriched.append(c)
    return {"candidates": enriched}


def node_risk(state: GraphState) -> dict:
    fbt = _features_by_ticker(state)
    review = risk.review_candidates(state.get("candidates", []), fbt, state.get("macro", {}))
    return {"_risk_review": review}


def node_committee(state: GraphState) -> dict:
    fbt = _features_by_ticker(state)
    rules = state.get("memory", {}).get("current_rules", {})
    decision = committee.decide(
        candidates=state.get("candidates", []),
        features_by_ticker=fbt,
        risk_review=state.get("_risk_review", {}),
        macro=state.get("macro", {}),
        rules=rules,
    )
    return {"committee_decision": decision}


# ── Output nodes ─────────────────────────────────────────────────────────────
def node_write_decision(state: GraphState) -> dict:
    record = {
        "run_date": state["run_date"],
        "yesterday_date": state.get("yesterday_date"),
        "macro": state.get("macro", {}),
        "performance_review": state.get("performance_review", {}),
        "candidates": state.get("candidates", []),
        "risk_review": state.get("_risk_review", {}),
        "committee_decision": state.get("committee_decision", {}),
        "warnings": state.get("warnings", []),
    }
    decisions_store.save_decision(state["run_date"], record)
    return {}


def node_render_report(state: GraphState) -> dict:
    md = report_mod.render_report(
        run_date=state["run_date"],
        review=state.get("performance_review", {}),
        macro=state.get("macro", {}),
        candidates=state.get("candidates", []),
        committee_decision=state.get("committee_decision", {}),
        risk_review=state.get("_risk_review", {}),
    )
    decisions_store.save_report(state["run_date"], md)
    return {"report_markdown": md}


def node_update_memory(state: GraphState) -> dict:
    proposal = memory_agent.propose_update(
        performance_review=state.get("performance_review", {}),
        committee_decision=state.get("committee_decision", {}),
        macro=state.get("macro", {}),
    )
    new_mem = memory_store.integrate_update(
        memory=state.get("memory", {}),
        new_observations=proposal.get("observations", []),
        new_tentative_lessons=proposal.get("tentative_lessons", []),
        performance_summary=proposal.get("performance_summary", {}),
        lesson_matcher=memory_agent.make_lesson_matcher(),
        run_date=state["run_date"],
    )
    memory_store.save_memory(new_mem)
    return {"new_memory": new_mem}


# ── Graph builder ────────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(GraphState)

    g.add_node("load_memory", node_load_memory)
    g.add_node("load_yesterday", node_load_yesterday)
    g.add_node("fetch_prices", node_fetch_prices)
    g.add_node("calculate_features", node_calculate_features)
    g.add_node("score_yesterday", node_score_yesterday)
    g.add_node("fetch_context", node_fetch_context)
    g.add_node("build_candidates", node_build_candidates)
    g.add_node("news_catalyst", node_news_catalyst)
    g.add_node("risk", node_risk)
    g.add_node("committee", node_committee)
    g.add_node("write_decision", node_write_decision)
    g.add_node("render_report", node_render_report)
    g.add_node("update_memory", node_update_memory)

    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "load_yesterday")
    g.add_edge("load_yesterday", "fetch_prices")
    g.add_edge("fetch_prices", "calculate_features")
    g.add_edge("calculate_features", "score_yesterday")
    g.add_edge("score_yesterday", "fetch_context")
    g.add_edge("fetch_context", "build_candidates")
    g.add_edge("build_candidates", "news_catalyst")
    g.add_edge("news_catalyst", "risk")
    g.add_edge("risk", "committee")
    g.add_edge("committee", "write_decision")
    g.add_edge("write_decision", "render_report")
    g.add_edge("render_report", "update_memory")
    g.add_edge("update_memory", END)

    return g.compile()
