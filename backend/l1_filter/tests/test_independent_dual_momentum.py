from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.independent_dual_momentum import (
    IndependentDualMomentumConfig,
    weekly_independent_momentum_targets,
)


def _daily(drift, phase=0.0, periods=260):
    index = pd.date_range('2024-01-01', periods=periods, freq='1D', tz='UTC')
    returns = drift + 0.002 * np.sin(np.arange(periods) / 4 + phase)
    close = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        'close': close,
        'close_time': index + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
    }, index=index)


def _fixture():
    daily = {
        'STRONG': _daily(.004, 0.0),
        'WEAK': _daily(.002, .8),
        'BEAR': _daily(-.002, 1.6),
    }
    rates = pd.date_range('2024-01-01', periods=780, freq='8h', tz='UTC')
    funding = {symbol: pd.Series(0.0, index=rates) for symbol in daily}
    return daily, funding


def test_own_sma_gate_and_relative_rank_select_only_bull_assets():
    daily, funding = _fixture()
    decision = pd.Timestamp('2024-09-02', tz='UTC')
    target = weekly_independent_momentum_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('STRONG', 'WEAK', 'BEAR'))[0]
    assert set(target['weights']) == {'STRONG', 'WEAK'}
    assert all(weight > 0 for weight in target['weights'].values())
    assert target['selected']['STRONG']['score'] > target['selected']['WEAK']['score']


def test_unclosed_decision_day_cannot_change_target():
    daily, funding = _fixture()
    decision = pd.Timestamp('2024-09-02', tz='UTC')
    baseline = weekly_independent_momentum_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('STRONG', 'WEAK', 'BEAR'))
    for frame in daily.values():
        frame.loc[decision, 'close'] *= 1000
    repeated = weekly_independent_momentum_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        symbol_order=('STRONG', 'WEAK', 'BEAR'))
    assert baseline == repeated


def test_funding_veto_can_force_explicit_cash_target():
    daily, funding = _fixture()
    decision = pd.Timestamp('2024-09-02', tz='UTC')
    for symbol in ('STRONG', 'WEAK'):
        funding[symbol].loc[decision - pd.Timedelta(days=27):decision] = .0002
    target = weekly_independent_momentum_targets(
        daily, funding, decision, decision + pd.Timedelta(days=7),
        replace(IndependentDualMomentumConfig(), max_mean_funding=.0001),
        symbol_order=('STRONG', 'WEAK', 'BEAR'))[0]
    assert target['weights'] == {}
    assert target['flat_reason'] == 'NO_ELIGIBLE_ASSET'
