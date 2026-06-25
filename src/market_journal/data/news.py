"""Finnhub client: company news (last 72h) and next earnings date.

Degrades gracefully when FINNHUB_API_KEY is absent or the API is unreachable.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import requests

from market_journal.config import get_settings
from market_journal.data import cache

_BASE = "https://finnhub.io/api/v1"
_NAMESPACE_NEWS = "news"
_NAMESPACE_EARN = "earnings"
_TIMEOUT = 12


def fetch_company_news(
    ticker: str, run_date: str, warnings: Optional[List[str]] = None
) -> List[dict]:
    """Return recent (<=72h) news items: [{headline, source, url, datetime}]."""
    if warnings is None:
        warnings = []
    cached = cache.read(_NAMESPACE_NEWS, ticker, run_date)
    if cached is not None:
        return cached

    settings = get_settings()
    if settings.cache_only or not settings.has_finnhub:
        return []

    try:
        end = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        end = date.today()
    start = end - timedelta(days=3)

    try:
        resp = requests.get(
            f"{_BASE}/company-news",
            params={
                "symbol": ticker,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": settings.finnhub_api_key,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"finnhub news failed for {ticker}: {exc}")
        return []

    items: List[dict] = []
    for it in raw if isinstance(raw, list) else []:
        items.append(
            {
                "headline": it.get("headline", ""),
                "source": it.get("source", ""),
                "url": it.get("url", ""),
                "datetime": _iso_from_epoch(it.get("datetime")),
            }
        )
    items = items[:15]
    cache.write(_NAMESPACE_NEWS, ticker, run_date, items)
    return items


def fetch_next_earnings_days(
    ticker: str, run_date: str, warnings: Optional[List[str]] = None
) -> Optional[int]:
    """Return whole days until the next earnings date, or None if unknown."""
    if warnings is None:
        warnings = []
    cached = cache.read(_NAMESPACE_EARN, ticker, run_date)
    if cached is not None:
        return cached.get("days_to_earnings") if isinstance(cached, dict) else None

    settings = get_settings()
    if settings.cache_only or not settings.has_finnhub:
        return None

    try:
        ref = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        ref = date.today()

    try:
        resp = requests.get(
            f"{_BASE}/calendar/earnings",
            params={
                "symbol": ticker,
                "from": ref.isoformat(),
                "to": (ref + timedelta(days=60)).isoformat(),
                "token": settings.finnhub_api_key,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"finnhub earnings failed for {ticker}: {exc}")
        return None

    rows = (raw or {}).get("earningsCalendar", []) if isinstance(raw, dict) else []
    nearest: Optional[int] = None
    for row in rows:
        d = row.get("date")
        if not d:
            continue
        try:
            ed = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = (ed - ref).days
        if delta >= 0 and (nearest is None or delta < nearest):
            nearest = delta

    cache.write(_NAMESPACE_EARN, ticker, run_date, {"days_to_earnings": nearest})
    return nearest


def earnings_risk_label(days_to_earnings: Optional[int]) -> str:
    if days_to_earnings is None:
        return "unknown"
    if days_to_earnings <= 1:
        return "high"
    if days_to_earnings <= 5:
        return "medium"
    return "low"


def _iso_from_epoch(epoch) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""
