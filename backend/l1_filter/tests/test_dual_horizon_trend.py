from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.dual_horizon_trend import (
    DualHorizonTrendConfig,
    weekly_dual_horizon_targets,
)


def _daily(drift, periods=180, phase=0.0):
    index = pd.date_range('2024-09-01', periods=periods, freq='1D', tz='UTC')
    wobble = 0.002 * np.sin(np.arange(periods) / 3 + phase)
    close = 100 * np.exp(np.cumsum(drift + wobble))
    return pd.DataFrame({
        'close': close,
        'close_time': index + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
    }, index=index)


def _fixtures():
    daily = {
        'UP1': _daily(0.004, phase=0.0),
        'UP2': _daily(0.003, phase=0.7),
        'DOWN': _daily(-0.003, phase=1.4),
    }
    empty_rate = lambda: pd.Series(
        0.0, index=pd.date_range('2024-09-01', periods=540, freq='8h', tz='UTC'))
    funding = {symbol: empty_rate() for symbol in daily}
    return daily, funding


def test_signal_uses_only_candles_closed_before_monday_decision():
    daily, funding = _fixtures()
    decision = pd.Timestamp('2025-02-17', tz='UTC')
    baseline = weekly_dual_horizon_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('UP1', 'UP2', 'DOWN'))
    assert len(baseline) == 1
    for frame in daily.values():
        frame.loc[decision, 'close'] *= 1000
    repeated = weekly_dual_horizon_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('UP1', 'UP2', 'DOWN'))
    assert baseline == repeated


def test_extreme_adverse_funding_vetoes_only_that_candidate():
    daily, funding = _fixtures()
    decision = pd.Timestamp('2025-02-17', tz='UTC')
    funding['UP1'].loc[decision - pd.Timedelta(days=27):decision] = 0.0002
    targets = weekly_dual_horizon_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        replace(DualHorizonTrendConfig(), min_positions=1),
        symbol_order=('UP1', 'UP2', 'DOWN'))
    assert len(targets) == 1
    assert 'UP1' not in targets[0]['weights']
    assert targets[0]['weights']['UP2'] > 0
    assert targets[0]['weights']['DOWN'] < 0


def test_targets_are_gross_capped_and_vol_scaled():
    daily, funding = _fixtures()
    decision = pd.Timestamp('2025-02-17', tz='UTC')
    target = weekly_dual_horizon_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('UP1', 'UP2', 'DOWN'))[0]
    assert sum(abs(weight) for weight in target['weights'].values()) <= 1.0
    assert max(abs(weight) for weight in target['weights'].values()) <= 0.45
    assert target['vol_scale'] <= 1.0


def test_ineligible_week_emits_explicit_flat_target():
    daily, funding = _fixtures()
    decision = pd.Timestamp('2025-02-17', tz='UTC')
    config = replace(DualHorizonTrendConfig(), max_adverse_mean_funding=0.0)
    for symbol in funding:
        side = 1 if symbol.startswith('UP') else -1
        funding[symbol].loc[decision - pd.Timedelta(days=27):decision] = side * 0.0002
    targets = weekly_dual_horizon_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7), config,
        symbol_order=('UP1', 'UP2', 'DOWN'))
    assert len(targets) == 1
    assert targets[0]['weights'] == {}
    assert targets[0]['flat_reason'] == 'INSUFFICIENT_ELIGIBLE_ASSETS'
