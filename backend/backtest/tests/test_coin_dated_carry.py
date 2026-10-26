from dataclasses import replace

import numpy as np
import pandas as pd

from backtest.coin_dated_carry import (
    CoinCarryConfig,
    CoinCarryCosts,
    build_coin_carry_schedule,
    simulate_coin_carry,
)


def _frame(start, end, value):
    index = pd.date_range(start, end, freq='1h', inclusive='left', tz='UTC')
    values = np.full(len(index), value, dtype=float)
    return pd.DataFrame({
        'open': values, 'high': values, 'low': values, 'close': values,
    }, index=index)


def test_inverse_carry_locks_positive_basis_with_contract_rounding():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 100)
    futures = _frame(start, end, 102)
    exit_time = pd.Timestamp('2023-03-31 07:00', tz='UTC')
    futures.loc[exit_time:, ['open', 'high', 'low', 'close']] = 100
    zero_cost = replace(CoinCarryConfig(), costs=CoinCarryCosts(0, 0, 0, 0))
    result = simulate_coin_carry(
        {'ETHUSDT': {'spot': spot, 'futures': futures}},
        start, end, zero_cost)
    trade = result['trades'][0]
    assert trade['contract_notional_usd'] == 220
    assert trade['net_pnl'] > 0
    assert trade['closed_at'] == exit_time
    assert trade['max_futures_mark_leverage'] < 1.1


def test_schedule_rejects_coarse_contract_with_too_much_residual_coin():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 150)
    futures = _frame(start, end, 153)
    strict = replace(CoinCarryConfig(), maximum_unhedged_coin_fraction=.01)
    schedule = build_coin_carry_schedule(
        {'BTCUSDT': {'spot': spot, 'futures': futures}}, start, end, strict)
    assert schedule[0]['selected'] is None


def test_stress_headline_cost_is_fifty_bps():
    stress = CoinCarryCosts(
        spot_fee_bps=10, futures_fee_bps=5,
        spot_slippage_bps=5, futures_slippage_bps=5)
    assert stress.headline_four_fill_rate_sum_bps == 50


def test_spot_halt_gap_is_not_filled_and_futures_risk_still_runs():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 100).drop(
        pd.Timestamp('2023-03-24 13:00', tz='UTC'))
    futures = _frame(start, end, 102)
    result = simulate_coin_carry(
        {'ETHUSDT': {'spot': spot, 'futures': futures}},
        start, end, CoinCarryConfig())
    assert result['summary']['episodes'] == 1
    assert result['summary']['collateral_exhaustions'] == 0
