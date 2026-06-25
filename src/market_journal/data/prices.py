"""Bulk OHLCV price fetch via yfinance, with a per-day JSON cache.

Returns a dict keyed by symbol; each value is a list of daily bars:
    {"date": "YYYY-MM-DD", "open":..., "high":..., "low":..., "close":..., "volume":...}

If yfinance is unavailable or returns nothing, the symbol maps to an empty list
and a warning is recorded by the caller.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from market_journal.config import all_symbols, get_settings
from market_journal.data import cache

_NAMESPACE = "prices"


def _bars_from_dataframe(df) -> List[dict]:
    bars: List[dict] = []
    for idx, row in df.iterrows():
        try:
            date_str = idx.strftime("%Y-%m-%d")
        except AttributeError:
            date_str = str(idx)[:10]
        bars.append(
            {
                "date": date_str,
                "open": _f(row.get("Open")),
                "high": _f(row.get("High")),
                "low": _f(row.get("Low")),
                "close": _f(row.get("Close")),
                "volume": _f(row.get("Volume")),
            }
        )
    return bars


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        fv = float(v)
        if fv != fv:  # NaN
            return None
        return fv
    except (TypeError, ValueError):
        return None


def fetch_prices(
    run_date: str,
    symbols: Optional[List[str]] = None,
    lookback_days: int = 120,
    warnings: Optional[List[str]] = None,
) -> Dict[str, List[dict]]:
    """Fetch (or load cached) daily OHLCV bars for all required symbols.

    The cache is keyed by run_date so repeated runs on the same day are cheap.
    """
    if warnings is None:
        warnings = []
    if symbols is None:
        symbols = all_symbols()

    settings = get_settings()
    out: Dict[str, List[dict]] = {}

    # Try cache first (and exclusively in cache-only mode).
    missing: List[str] = []
    for sym in symbols:
        cached = cache.read(_NAMESPACE, sym, run_date)
        if cached is not None:
            out[sym] = cached
        else:
            missing.append(sym)

    if not missing:
        return out

    if settings.cache_only:
        for sym in missing:
            out[sym] = []
        warnings.append(f"cache-only: missing price cache for {len(missing)} symbols")
        return out

    try:
        import yfinance as yf  # imported lazily so offline/test paths don't need it
    except ImportError:
        warnings.append("yfinance not installed; no price data fetched")
        for sym in missing:
            out[sym] = []
        return out

    try:
        period = f"{max(lookback_days, 5)}d"
        data = yf.download(
            tickers=" ".join(missing),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=False,
            progress=False,
        )
    except Exception as exc:  # noqa: BLE001 - network/library errors are non-fatal
        warnings.append(f"yfinance download failed: {exc}")
        for sym in missing:
            out[sym] = []
        return out

    for sym in missing:
        bars: List[dict] = []
        try:
            if len(missing) == 1:
                sub = data
            else:
                sub = data[sym] if sym in data.columns.get_level_values(0) else None
            if sub is not None and not sub.empty:
                bars = _bars_from_dataframe(sub.dropna(how="all"))
        except Exception:  # noqa: BLE001
            bars = []
        out[sym] = bars
        if bars:
            cache.write(_NAMESPACE, sym, run_date, bars)
        else:
            warnings.append(f"no price data for {sym}")

    return out
