"""Macro snapshot: a small context object, not a full agent.

Combines:
    - QQQ / SPY 1-day returns (computed from already-fetched price frames),
    - VIX 1-day change (^VIX via yfinance, cached),
    - 10-year Treasury yield change (FRED series DGS10, if a key is present),
and derives a coarse market-regime label.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import requests

from market_journal.config import get_settings
from market_journal.data import cache, prices

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_NAMESPACE_FRED = "fred"
_TIMEOUT = 12


def _return_1d(bars: List[dict]) -> Optional[float]:
    closes = [b.get("close") for b in bars if b.get("close") is not None]
    if len(closes) < 2:
        return None
    prev, last = closes[-2], closes[-1]
    if not prev:
        return None
    return (last - prev) / prev


def _vix_change(run_date: str, warnings: List[str]) -> Optional[float]:
    frames = prices.fetch_prices(run_date, symbols=["^VIX"], lookback_days=10, warnings=warnings)
    bars = frames.get("^VIX", [])
    closes = [b.get("close") for b in bars if b.get("close") is not None]
    if len(closes) < 2 or not closes[-2]:
        return None
    return (closes[-1] - closes[-2]) / closes[-2]


def _ten_year_yield_change(run_date: str, warnings: List[str]) -> Optional[float]:
    settings = get_settings()
    cached = cache.read(_NAMESPACE_FRED, "DGS10", run_date)
    if isinstance(cached, dict):
        return cached.get("change")
    if settings.cache_only or not settings.has_fred:
        return None
    try:
        resp = requests.get(
            _FRED_BASE,
            params={
                "series_id": "DGS10",
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        obs = (resp.json() or {}).get("observations", [])
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"fred DGS10 failed: {exc}")
        return None

    vals: List[float] = []
    for o in obs:
        try:
            vals.append(float(o["value"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(vals) < 2:
        return None
    change = vals[0] - vals[1]  # latest minus prior (percentage points)
    cache.write(_NAMESPACE_FRED, "DGS10", run_date, {"change": change})
    return change


def _classify_regime(
    qqq: Optional[float], vix_chg: Optional[float]
) -> str:
    if qqq is None:
        return "unknown"
    if vix_chg is not None and vix_chg > 0.05 and qqq < 0:
        return "risk_off"
    if vix_chg is not None and vix_chg > 0.08:
        return "high_vol"
    if qqq > 0.004:
        return "risk_on"
    if qqq < -0.004:
        return "risk_off"
    return "neutral"


def build_macro_snapshot(
    run_date: str,
    price_frames: Dict[str, List[dict]],
    warnings: Optional[List[str]] = None,
) -> dict:
    """Return a serialized MacroSnapshot-compatible dict."""
    if warnings is None:
        warnings = []

    qqq = _return_1d(price_frames.get("QQQ", []))
    spy = _return_1d(price_frames.get("SPY", []))
    vix_chg = _vix_change(run_date, warnings)
    ten_y = _ten_year_yield_change(run_date, warnings)
    regime = _classify_regime(qqq, vix_chg)

    notes_parts = [f"regime={regime}"]
    if qqq is not None:
        notes_parts.append(f"QQQ {qqq * 100:+.2f}%")
    if vix_chg is not None:
        notes_parts.append(f"VIX {vix_chg * 100:+.1f}%")
    if ten_y is not None:
        notes_parts.append(f"10y {ten_y:+.2f}pp")

    return {
        "market_regime": regime,
        "qqq_return_1d": qqq,
        "spy_return_1d": spy,
        "vix_change": vix_chg,
        "ten_year_yield_change": ten_y,
        "notes": ", ".join(notes_parts),
    }
