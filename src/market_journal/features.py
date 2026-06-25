"""Deterministic feature engineering from raw OHLCV bars.

Computes price/relative/catalyst features per ticker. No network calls here —
news/earnings/filings data is passed in by the caller (the graph node) so this
module stays pure and easily testable.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from market_journal.config import SECTOR_ETF
from market_journal.data import news as news_client
from market_journal.state import (
    CatalystFeatures,
    PriceFeatures,
    RelativeFeatures,
    TickerFeatures,
)


def _closes(bars: List[dict]) -> List[float]:
    return [b["close"] for b in bars if b.get("close") is not None]


def _volumes(bars: List[dict]) -> List[float]:
    return [b["volume"] for b in bars if b.get("volume") is not None]


def _pct_change(values: List[float], periods: int) -> Optional[float]:
    if len(values) <= periods:
        return None
    old = values[-periods - 1]
    new = values[-1]
    if not old:
        return None
    return (new - old) / old


def _volatility(closes: List[float], window: int = 20) -> Optional[float]:
    if len(closes) <= window:
        return None
    rets = []
    for i in range(len(closes) - window, len(closes)):
        prev = closes[i - 1]
        if prev:
            rets.append((closes[i] - prev) / prev)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def _sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def build_price_features(ticker: str, bars: List[dict]) -> PriceFeatures:
    closes = _closes(bars)
    vols = _volumes(bars)
    pf = PriceFeatures(ticker=ticker)
    if not closes:
        return pf

    pf.close = closes[-1]
    pf.return_1d = _pct_change(closes, 1)
    pf.return_5d = _pct_change(closes, 5)
    pf.return_20d = _pct_change(closes, 20)
    pf.return_60d = _pct_change(closes, 60)
    pf.volatility_20d = _volatility(closes, 20)

    if bars and bars[-1].get("open") and len(closes) >= 2:
        prev_close = closes[-2]
        today_open = bars[-1]["open"]
        if prev_close:
            pf.gap_pct = (today_open - prev_close) / prev_close

    if vols:
        pf.volume = vols[-1]
        avg20 = _sma(vols, 20)
        if avg20:
            pf.volume_vs_20d_avg = vols[-1] / avg20

    ma20 = _sma(closes, 20)
    ma50 = _sma(closes, 50)
    if ma20:
        pf.dist_from_ma20 = (closes[-1] - ma20) / ma20
    if ma50:
        pf.dist_from_ma50 = (closes[-1] - ma50) / ma50
    return pf


def build_relative_features(
    ticker: str,
    price_features: PriceFeatures,
    benchmark_1d: Dict[str, Optional[float]],
    sector_1d: Optional[float],
) -> RelativeFeatures:
    rf = RelativeFeatures(sector_etf=SECTOR_ETF.get(ticker))
    r1 = price_features.return_1d
    if r1 is not None:
        if benchmark_1d.get("QQQ") is not None:
            rf.return_vs_qqq_1d = r1 - benchmark_1d["QQQ"]
        if benchmark_1d.get("SPY") is not None:
            rf.return_vs_spy_1d = r1 - benchmark_1d["SPY"]
        if sector_1d is not None:
            rf.return_vs_sector_1d = r1 - sector_1d
    return rf


def build_catalyst_features(
    ticker: str,
    run_date: str,
    news_items: List[dict],
    days_to_earnings: Optional[int],
    filings: dict,
) -> CatalystFeatures:
    headlines = [n.get("headline", "") for n in news_items if n.get("headline")]
    most_recent = filings.get("most_recent") or {}
    return CatalystFeatures(
        news_count_72h=len(news_items),
        headlines=headlines[:8],
        days_to_earnings=days_to_earnings,
        earnings_risk=news_client.earnings_risk_label(days_to_earnings),
        has_recent_filing=bool(filings.get("has_recent_filing")),
        filing_types=list(filings.get("filing_types", [])),
        filing_url=most_recent.get("url"),
        filing_summary=most_recent.get("summary"),
    )


def one_day_return(bars: List[dict]) -> Optional[float]:
    closes = _closes(bars)
    return _pct_change(closes, 1) if closes else None


def build_ticker_features(
    ticker: str,
    bars: List[dict],
    benchmark_1d: Dict[str, Optional[float]],
    sector_1d: Optional[float],
    run_date: str,
    news_items: List[dict],
    days_to_earnings: Optional[int],
    filings: dict,
) -> TickerFeatures:
    price = build_price_features(ticker, bars)
    relative = build_relative_features(ticker, price, benchmark_1d, sector_1d)
    catalyst = build_catalyst_features(
        ticker, run_date, news_items, days_to_earnings, filings
    )
    return TickerFeatures(ticker=ticker, price=price, relative=relative, catalyst=catalyst)
