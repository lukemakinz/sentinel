from dataclasses import replace

import numpy as np
import pandas as pd

from backtest.swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


def _market():
    index = pd.date_range('2026-01-01', periods=5, freq='5min', tz='UTC')
    return pd.DataFrame({
        'open': [100, 100, 103, 103, 103],
        'high': [100.5, 105, 103.5, 103.5, 103.5],
        'low': [99.5, 99, 99.5, 102.5, 102.5],
        'close': [100, 104, 103, 103, 103],
    }, index=index)


def _signal(timestamp):
    return {
        'timestamp': timestamp, 'side': 1, 'stop': 98.0, 'atr': 1.0,
        'score': 1.0, 'setup': 'test', 'setup_id': 'test:1',
    }


def _run(policy, market=None, management=None, costs=False):
    market = _market() if market is None else market
    if management is None:
        management = pd.DataFrame({
            'high': [105.0], 'low': [99.0], 'close': [104.0], 'atr': [1.0],
        }, index=[market.index[2]])
    config = SwingExecutionConfig(exit_policy=policy, fee_bps=0, slippage_bps=0)
    if costs:
        config = replace(config, fee_bps=5, slippage_bps=2)
    return execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [_signal(market.index[0])]}, {'ETHUSDT': []},
        {'ETHUSDT': management}, config, market.index[0],
        market.index[-1] + pd.Timedelta(minutes=5),
    )


def test_close_derived_chandelier_activates_next_bar_not_inside_source_bar():
    result = _run('delayed_cost_be_chandelier')
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    assert trade['closed_at'] == str(pd.Timestamp('2026-01-01 00:15', tz='UTC'))
    assert trade['final_stop'] == 102.5
    assert trade['stop_updates'][0]['computed_at'] == str(
        pd.Timestamp('2026-01-01 00:10', tz='UTC'))


def test_initial_stop_only_policy_does_not_create_profit_stop():
    result = _run('initial_sl_only')
    trade = result['trades'][0]
    assert trade['final_stop'] == 98.0
    assert trade['stop_updates'] == []
    assert trade['reason'] == 'END_OF_TEST'


def test_cost_breakeven_covers_round_trip_trading_friction_at_exact_stop():
    market = _market()
    # Signal stop is based on the 100 close; the slipped entry still remains
    # within the frozen 1.5-2.5 ATR admission range.
    management = pd.DataFrame({
        'high': [105.0], 'low': [99.0], 'close': [104.0], 'atr': [1.0],
    }, index=[market.index[2]])
    result = _run('delayed_cost_be', market, management, costs=True)
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    assert abs(trade['pnl']) < 1e-10


def test_higher_score_wins_one_global_position():
    market = _market()
    second = market.copy()
    low = _signal(market.index[0])
    high = {**_signal(market.index[0]), 'score': 2.0, 'setup_id': 'sol'}
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)
    result = execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float)),
         'SOLUSDT': (second, pd.Series(dtype=float))},
        {'ETHUSDT': [low], 'SOLUSDT': [high]},
        {'ETHUSDT': [], 'SOLUSDT': []},
        {'ETHUSDT': pd.DataFrame(), 'SOLUSDT': pd.DataFrame()},
        config, market.index[0], market.index[-1] + pd.Timedelta(minutes=5),
        symbol_priority=('ETHUSDT', 'SOLUSDT'),
    )
    assert len(result['trades']) == 1
    assert result['trades'][0]['symbol'] == 'SOLUSDT'


def test_synthetic_outage_row_cannot_fill_entry():
    market = _market()
    market['synthetic'] = False
    market.loc[market.index[0], 'synthetic'] = True
    result = _run('initial_sl_only', market=market)
    assert result['trades'] == []
    assert result['summary']['diagnostics']['blocked_synthetic_entry'] == 1


def test_synthetic_outage_row_cannot_trigger_stop():
    market = _market()
    market['synthetic'] = False
    market.loc[market.index[1], ['open', 'high', 'low', 'close']] = [
        100.0, 100.0, 90.0, 95.0,
    ]
    market.loc[market.index[1], 'synthetic'] = True
    result = _run('initial_sl_only', market=market)
    trade = result['trades'][0]
    assert trade['reason'] == 'END_OF_TEST'


def test_signal_target_closes_at_frozen_price():
    market = _market()
    signal = {**_signal(market.index[0]), 'target_price': 104.0}
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)
    result = execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [signal]}, {'ETHUSDT': []},
        {'ETHUSDT': pd.DataFrame()}, config, market.index[0],
        market.index[-1] + pd.Timedelta(minutes=5),
    )
    trade = result['trades'][0]
    assert trade['reason'] == 'TARGET'
    assert trade['closed_at'] == str(pd.Timestamp('2026-01-01 00:10', tz='UTC'))


def test_stop_wins_when_stop_and_target_hit_same_five_minute_bar():
    market = _market()
    market.loc[market.index[1], 'low'] = 97.0
    signal = {**_signal(market.index[0]), 'target_price': 104.0}
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)
    result = execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [signal]}, {'ETHUSDT': []},
        {'ETHUSDT': pd.DataFrame()}, config, market.index[0],
        market.index[-1] + pd.Timedelta(minutes=5),
    )
    assert result['trades'][0]['reason'] == 'STOP'


def test_signal_specific_time_exit_is_honored():
    market = _market()
    signal = {**_signal(market.index[0]), 'max_hold_minutes': 10}
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)
    result = execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [signal]}, {'ETHUSDT': []},
        {'ETHUSDT': pd.DataFrame()}, config, market.index[0],
        market.index[-1] + pd.Timedelta(minutes=5),
    )
    trade = result['trades'][0]
    assert trade['reason'] == 'TIME'
    assert trade['closed_at'] == str(pd.Timestamp('2026-01-01 00:10', tz='UTC'))


def test_actual_fill_must_preserve_minimum_target_space():
    market = _market()
    signal = {
        **_signal(market.index[0]), 'target_price': 104.0,
        'min_target_r': 2.5,
    }
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)
    result = execute_swing_portfolio(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [signal]}, {'ETHUSDT': []},
        {'ETHUSDT': pd.DataFrame()}, config, market.index[0],
        market.index[-1] + pd.Timedelta(minutes=5),
    )
    assert result['trades'] == []
    assert result['summary']['diagnostics'][
        'blocked_target_space_after_fill'] == 1


def test_signal_risk_scale_reduces_position_risk():
    market = _market()
    full_signal = _signal(market.index[0])
    half_signal = {**full_signal, 'risk_scale': 0.5}
    config = SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=0, slippage_bps=0)

    def execute(signal):
        return execute_swing_portfolio(
            {'ETHUSDT': (market, pd.Series(dtype=float))},
            {'ETHUSDT': [signal]}, {'ETHUSDT': []},
            {'ETHUSDT': pd.DataFrame()}, config, market.index[0],
            market.index[-1] + pd.Timedelta(minutes=5),
        )

    full = execute(full_signal)['trades'][0]
    half = execute(half_signal)['trades'][0]
    assert half['quantity'] == full['quantity'] / 2
    assert half['initial_risk'] == full['initial_risk'] / 2
    assert half['signal_risk_scale'] == 0.5
