"""Configuration: settings, universe, benchmarks, scoring weights, paths.

All values are intentionally simple and transparent. Tune scoring weights
later from journal history rather than optimising prematurely.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()  # load .env if present (no-op in CI where env vars are set directly)


# ── Paths ────────────────────────────────────────────────────────────────────
# Repo root = three levels up from this file (src/market_journal/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DECISIONS_DIR = DATA_DIR / "decisions"
REPORTS_DIR = DATA_DIR / "reports"
MEMORY_DIR = DATA_DIR / "memory"
CACHE_DIR = DATA_DIR / "cache"
MEMORY_FILE = MEMORY_DIR / "strategy_memory.json"


def ensure_dirs() -> None:
    """Create the data directories if they do not yet exist."""
    for d in (DECISIONS_DIR, REPORTS_DIR, MEMORY_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ── Universe & benchmarks ────────────────────────────────────────────────────
# Boring, liquid US large-caps: easy data, rich news coverage.
UNIVERSE: List[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX",
    "JPM", "BAC", "V", "MA", "UNH", "LLY", "JNJ", "XOM", "CVX", "COST",
    "WMT", "HD", "CRM", "ORCL", "ASML",
]

BENCHMARK_PRIMARY = "QQQ"
BENCHMARK_SECONDARY = "SPY"

# Optional sector ETF per ticker (used for relative-strength context).
SECTOR_ETF: Dict[str, str] = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AMD": "XLK", "AVGO": "XLK",
    "CRM": "XLK", "ORCL": "XLK", "ASML": "XLK",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "COST": "XLP", "WMT": "XLP",
    "GOOGL": "XLC", "META": "XLC", "NFLX": "XLC",
    "JPM": "XLF", "BAC": "XLF", "V": "XLF", "MA": "XLF",
    "UNH": "XLV", "LLY": "XLV", "JNJ": "XLV",
    "XOM": "XLE", "CVX": "XLE",
}

# All symbols we need OHLCV for each run (universe + benchmarks + sector ETFs).
def all_symbols() -> List[str]:
    syms = set(UNIVERSE)
    syms.add(BENCHMARK_PRIMARY)
    syms.add(BENCHMARK_SECONDARY)
    syms.update(SECTOR_ETF.values())
    return sorted(syms)


# ── Scoring weights (transparent, equal-ish; tune later) ─────────────────────
@dataclass(frozen=True)
class ScoreWeights:
    momentum: float = 0.30
    relative_strength: float = 0.25
    volume_confirmation: float = 0.15
    catalyst: float = 0.20
    # Penalties are subtracted; each is a fraction of the raw signal sum.
    earnings_risk_penalty: float = 0.15
    volatility_penalty: float = 0.10
    weak_evidence_penalty: float = 0.10


SCORE_WEIGHTS = ScoreWeights()

# How many top-scored candidates get expensive LLM attention.
TOP_N_CANDIDATES = 6
# How many paper picks the committee may select per day.
MAX_PICKS_PER_DAY = 3

# Avoid 1-day momentum picks when earnings are within N days (rule, not a hard block).
AVOID_EARNINGS_WITHIN_DAYS = 1

# Days into the future we frame the prediction over (v1 = single day).
PREDICTION_HORIZON_DAYS = 1


# ── Settings (env-driven) ────────────────────────────────────────────────────
def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    finnhub_api_key: str = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY", ""))
    fred_api_key: str = field(default_factory=lambda: os.getenv("FRED_API_KEY", ""))
    sec_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "SEC_USER_AGENT", "MarketJournal research example@example.com"
        )
    )
    model_cheap: str = field(default_factory=lambda: os.getenv("MODEL_CHEAP", "gpt-4o-mini"))
    model_smart: str = field(default_factory=lambda: os.getenv("MODEL_SMART", "gpt-4o"))
    offline: bool = field(default_factory=lambda: _env_bool("MARKET_JOURNAL_OFFLINE", False))
    cache_only: bool = field(
        default_factory=lambda: _env_bool("MARKET_JOURNAL_USE_CACHE_ONLY", False)
    )

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key) and not self.offline

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def has_fred(self) -> bool:
        return bool(self.fred_api_key)


def get_settings() -> Settings:
    return Settings()


# Standard disclaimer surfaced in every report.
DISCLAIMER = (
    "This is a paper research journal for educational purposes only. "
    "It records simulated decisions and does not place trades. "
    "Nothing here is investment advice."
)
