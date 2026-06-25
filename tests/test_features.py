"""Tests for deterministic feature engineering."""
from __future__ import annotations

from helpers import make_bars, rising_series

from market_journal.features import (
    build_price_features,
    build_relative_features,
    one_day_return,
)


def test_one_day_return():
    bars = make_bars([100.0, 110.0])
    assert abs(one_day_return(bars) - 0.10) < 1e-9


def test_price_features_returns_and_ma():
    closes = rising_series(70, start=100.0, step=1.0)
    bars = make_bars(closes)
    pf = build_price_features("TEST", bars)
    assert pf.close == closes[-1]
    # 1d return = (169 - 168)/168
    assert pf.return_1d is not None and pf.return_1d > 0
    # 20d return positive in a rising series
    assert pf.return_20d > 0
    # last close is above the 20d SMA in a rising series
    assert pf.dist_from_ma20 > 0


def test_price_features_empty_bars():
    pf = build_price_features("TEST", [])
    assert pf.close is None
    assert pf.return_1d is None


def test_relative_features_vs_benchmark():
    closes = [100.0, 102.0]  # +2%
    pf = build_price_features("TEST", make_bars(closes))
    rel = build_relative_features(
        "TEST", pf, benchmark_1d={"QQQ": 0.005, "SPY": 0.004}, sector_1d=0.01
    )
    assert rel.return_vs_qqq_1d is not None
    assert abs(rel.return_vs_qqq_1d - (0.02 - 0.005)) < 1e-6
    assert abs(rel.return_vs_sector_1d - (0.02 - 0.01)) < 1e-6


def test_volume_spike_detected():
    closes = rising_series(30, 100.0, 0.5)
    volumes = [1_000_000] * 29 + [3_000_000]
    pf = build_price_features("TEST", make_bars(closes, volumes))
    assert pf.volume_vs_20d_avg is not None
    assert pf.volume_vs_20d_avg > 2.0
