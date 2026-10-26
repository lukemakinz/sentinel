from dataclasses import replace

import numpy as np
import pandas as pd

from backtest.xfrd import (
    XFRDConfig,
    XFRDCosts,
    funding_candidate,
    normalize_funding_hourly,
    paired_funding_features,
)


def _rates(start, values):
    return pd.Series(values, index=pd.date_range(
        start, periods=len(values), freq='8h', tz='UTC'), dtype=float)


def _market(start='2025-12-01', periods=1200, value=100.0):
    index = pd.date_range(start, periods=periods, freq='1h', tz='UTC')
    values = np.full(periods, value)
    return pd.DataFrame({
        'open': values, 'high': values, 'low': values, 'close': values,
    }, index=index)


def test_funding_is_normalized_by_realized_interval():
    rates = pd.Series(
        [.001, .0008, .0004],
        index=pd.DatetimeIndex([
            '2026-01-01 00:00', '2026-01-01 08:00', '2026-01-01 12:00'],
            tz='UTC'),
    )
    normalized = normalize_funding_hourly(rates)
    assert normalized.iloc[0].interval_hours == 8
    assert normalized.iloc[1].interval_hours == 4
    assert np.allclose(normalized.hourly_rate, .0001)


def test_candidate_uses_only_rates_through_decision_timestamp():
    config = replace(
        XFRDConfig(), entry_projected_7d_bps=1,
        basis_max_bps=200,
    )
    binance = _rates('2026-01-01', [.001] * 12)
    bybit = _rates('2026-01-01', [0.0] * 12)
    features = {'ETHUSDT': paired_funding_features(binance, bybit, config)}
    market = _market()
    data = {'ETHUSDT': {
        'binance': {'mark': market}, 'bybit': {'mark': market * .999},
    }}
    timestamp = features['ETHUSDT'].index[9]
    before = funding_candidate(data, features, 'ETHUSDT', timestamp, config)
    altered = binance.copy()
    altered.loc[altered.index > timestamp] = -1
    changed = {'ETHUSDT': paired_funding_features(altered, bybit, config)}
    after = funding_candidate(data, changed, 'ETHUSDT', timestamp, config)
    assert before == after
    assert before['short_venue'] == 'binance'
    assert before['planned_fill_time'] == timestamp + pd.Timedelta(hours=1)


def test_stress_round_trip_is_forty_bps():
    config = replace(XFRDConfig(), costs=XFRDCosts(5, 5))
    assert config.costs.combined_round_trip_bps == 40
