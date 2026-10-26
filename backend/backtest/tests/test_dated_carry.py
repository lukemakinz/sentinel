from dataclasses import replace

import numpy as np
import pandas as pd

from backtest.dated_carry import (
    DatedCarryConfig,
    DatedCarryCosts,
    build_dated_carry_schedule,
    quarterly_expiries,
    simulate_dated_carry,
)


def _frame(start, end, value):
    index = pd.date_range(start, end, freq='1h', inclusive='left', tz='UTC')
    values = np.full(len(index), value, dtype=float)
    return pd.DataFrame({
        'open': values, 'high': values, 'low': values, 'close': values,
    }, index=index)


def test_quarter_expiry_is_last_friday_at_eight_utc():
    expiries = quarterly_expiries('2026-01-01', '2027-01-01')
    assert expiries == [
        pd.Timestamp('2026-03-27 08:00', tz='UTC'),
        pd.Timestamp('2026-06-26 08:00', tz='UTC'),
        pd.Timestamp('2026-09-25 08:00', tz='UTC'),
        pd.Timestamp('2026-12-25 08:00', tz='UTC'),
    ]


def test_schedule_uses_prior_closed_hour_and_selects_larger_premium():
    start, end = '2026-01-01', '2026-04-01'
    spot = _frame(start, end, 100)
    data = {
        'BTCUSDT': {'spot': spot, 'futures': _frame(start, end, 101)},
        'ETHUSDT': {'spot': spot, 'futures': _frame(start, end, 102)},
    }
    schedule = build_dated_carry_schedule(data, start, end, DatedCarryConfig())
    assert len(schedule) == 1
    assert schedule[0]['selected']['symbol'] == 'ETHUSDT'
    assert schedule[0]['feature_cutoff'] == pd.Timestamp(
        '2026-02-25 07:00', tz='UTC')
    assert schedule[0]['entry_time'] == pd.Timestamp(
        '2026-02-25 09:00', tz='UTC')


def test_stress_combined_round_trip_is_fifty_bps():
    config = replace(DatedCarryConfig(), costs=DatedCarryCosts(
        spot_fee_bps=10, futures_fee_bps=5,
        spot_slippage_bps=5, futures_slippage_bps=5))
    assert config.costs.combined_round_trip_bps == 50


def test_real_spot_halt_gap_does_not_create_price_or_hide_futures_risk():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 100)
    futures = _frame(start, end, 102)
    expiry_exit = pd.Timestamp('2023-03-31 07:00', tz='UTC')
    futures.loc[expiry_exit:, ['open', 'high', 'low', 'close']] = 100
    halt = pd.Timestamp('2023-03-24 13:00', tz='UTC')
    spot = spot.drop(halt)
    result = simulate_dated_carry(
        {'BTCUSDT': {'spot': spot, 'futures': futures}},
        start, end, DatedCarryConfig())
    assert result['summary']['episodes'] == 1
    assert result['summary']['net_pnl'] > 0
    assert result['trades'][0]['closed_at'] == expiry_exit


def test_missing_feature_hour_cancels_symbol_instead_of_synthesizing_signal():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 100).drop(
        pd.Timestamp('2023-03-01 07:00', tz='UTC'))
    futures = _frame(start, end, 102)
    result = simulate_dated_carry(
        {'BTCUSDT': {'spot': spot, 'futures': futures}},
        start, end, DatedCarryConfig())
    assert result['summary']['qualified_decisions'] == 0
    assert result['summary']['episodes'] == 0


def test_planned_exit_bar_close_is_not_used_for_pre_exit_risk():
    start, end = '2023-01-01', '2023-04-01'
    spot = _frame(start, end, 100)
    futures = _frame(start, end, 102)
    planned_exit = pd.Timestamp('2023-03-31 07:00', tz='UTC')
    # The position exits at this bar's open (102). Its later close must not be
    # observed. A synthetic high/close shock would otherwise trip the gate.
    futures.loc[planned_exit, ['high', 'close']] = 1000
    result = simulate_dated_carry(
        {'BTCUSDT': {'spot': spot, 'futures': futures}},
        start, end, DatedCarryConfig())
    trade = result['trades'][0]
    assert trade['closed_at'] == planned_exit
    assert trade['reason'] == 'PRE_EXPIRY_EXIT'
    assert trade['max_futures_mark_leverage'] < .8
