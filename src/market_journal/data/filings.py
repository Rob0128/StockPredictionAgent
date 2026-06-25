"""SEC EDGAR client: simple recent-filing flags per ticker.

MVP scope (intentionally shallow — no deep materiality analysis):
    - new 8-K?  10-Q?  10-K?  Form 4?
    - most recent relevant filing: type, date, URL, one-line description.

Uses the public EDGAR submissions API (no key). A descriptive User-Agent is
required by the SEC fair-access policy and is read from SEC_USER_AGENT.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from market_journal.config import get_settings
from market_journal.data import cache

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_NAMESPACE_MAP = "edgar_map"
_NAMESPACE_FILINGS = "filings"
_RELEVANT = {"8-K", "10-Q", "10-K", "4"}
_TIMEOUT = 15
# How recent a filing must be (days) to count as "recent" for the daily flag.
_RECENCY_DAYS = 5


def _headers() -> Dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent, "Accept-Encoding": "gzip, deflate"}


def _load_ticker_cik_map(run_date: str, warnings: List[str]) -> Dict[str, int]:
    cached = cache.read(_NAMESPACE_MAP, "all", run_date)
    if isinstance(cached, dict):
        return {k: int(v) for k, v in cached.items()}

    settings = get_settings()
    if settings.cache_only:
        return {}

    try:
        resp = requests.get(_TICKERS_URL, headers=_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"edgar ticker map failed: {exc}")
        return {}

    mapping: Dict[str, int] = {}
    for entry in (raw or {}).values():
        try:
            mapping[entry["ticker"].upper()] = int(entry["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
    if mapping:
        cache.write(_NAMESPACE_MAP, "all", run_date, mapping)
    return mapping


def fetch_recent_filings(
    ticker: str, run_date: str, warnings: Optional[List[str]] = None
) -> dict:
    """Return a simple filings flag object for the ticker.

    {
      "has_recent_filing": bool,
      "filing_types": ["8-K", ...],
      "most_recent": {"type", "date", "url", "summary"} | None
    }
    """
    if warnings is None:
        warnings = []
    empty = {"has_recent_filing": False, "filing_types": [], "most_recent": None}

    cached = cache.read(_NAMESPACE_FILINGS, ticker, run_date)
    if isinstance(cached, dict):
        return cached

    settings = get_settings()
    if settings.cache_only:
        return empty

    cik_map = _load_ticker_cik_map(run_date, warnings)
    cik = cik_map.get(ticker.upper())
    if cik is None:
        return empty

    try:
        resp = requests.get(
            _SUBMISSIONS_URL.format(cik=cik), headers=_headers(), timeout=_TIMEOUT
        )
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"edgar submissions failed for {ticker}: {exc}")
        return empty

    recent = (((raw or {}).get("filings") or {}).get("recent")) or {}
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    accns = recent.get("accessionNumber", []) or []
    docs = recent.get("primaryDocument", []) or []

    try:
        ref = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        ref = datetime.utcnow().date()
    cutoff = ref - timedelta(days=_RECENCY_DAYS)

    found_types: List[str] = []
    most_recent: Optional[dict] = None
    for i, form in enumerate(forms):
        if form not in _RELEVANT:
            continue
        d_str = dates[i] if i < len(dates) else ""
        try:
            fdate = datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate < cutoff or fdate > ref:
            continue
        label = "Form 4" if form == "4" else form
        if label not in found_types:
            found_types.append(label)
        if most_recent is None:
            url = _filing_url(cik, accns[i] if i < len(accns) else "",
                              docs[i] if i < len(docs) else "")
            most_recent = {
                "type": label,
                "date": d_str,
                "url": url,
                "summary": _summary_for(label),
            }

    result = {
        "has_recent_filing": bool(found_types),
        "filing_types": found_types,
        "most_recent": most_recent,
    }
    cache.write(_NAMESPACE_FILINGS, ticker, run_date, result)
    return result


def _filing_url(cik: int, accession: str, primary_doc: str) -> str:
    if not accession:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    accn_nodash = accession.replace("-", "")
    if primary_doc:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{primary_doc}"
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/"


def _summary_for(label: str) -> str:
    return {
        "8-K": "Material event report (8-K) filed.",
        "10-Q": "Quarterly report (10-Q) filed.",
        "10-K": "Annual report (10-K) filed.",
        "Form 4": "Insider transaction (Form 4) filed.",
    }.get(label, f"{label} filed.")
