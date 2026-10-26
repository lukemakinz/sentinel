from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from backtest.cluster_scalp_simulator import execute_cluster
from l1_filter.scalp_strategy import ScalpConfig


def _market(start='2026-01-01', periods=10):
    index = pd.date_range(start, periods=periods, freq='min', tz='UTC')
    return pd.DataFrame({
        'open': np.full(periods, 100.0),
        'high': np.full(periods, 100.1),
        'low': np.full(periods, 99.9),
        'close': np.full(periods, 100.0),
        'volume': np.full(periods, 10.0),
        'taker_buy_volume': np.full(periods, 5.0),
    }, index=index)


def _config():
    return ScalpConfig(
        name='cluster_test', minutes=15, target_r=2.0, partial_r=1.0,
        partial_fraction=0, trailing=False, max_hold_minutes=2,
        risk_fraction=0.002, max_notional_equity=0.5,
        daily_loss_fraction=0.006, fee_bps=0, slippage_bps=0,
        min_reward_cost_ratio=0, leverage=5, max_margin_fraction=0.1,
        maker_fee_bps=0, limit_penetration_bps=0,
    )


def _signal(timestamp, setup, limit=None):
    signal = {
        'timestamp': timestamp, 'side': 1, 'stop': 99.0, 'atr': 1.0,
        'score': 6, 'setup': setup, 'setup_id': setup,
        'min_stop_atr': 0.5, 'max_stop_atr': 1.5,
    }
    if limit is not None:
        signal['limit_price'] = limit
        signal['limit_ttl_minutes'] = 3
    return signal


def test_signal_risk_scale_reduces_position_size():
    market = _market(periods=5)
    ts = market.index[0]
    config = replace(_config(), fixed_risk_usd=10.0)
    full = _signal(ts, 'full')
    half = dict(full, risk_scale=0.5, setup_id='half')
    r_full = execute_cluster(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [full]},
        config, ts, market.index[-1] + pd.Timedelta(minutes=1), 250.0,
    )
    r_half = execute_cluster(
        {'ETHUSDT': (market, pd.Series(dtype=float))},
        {'ETHUSDT': [half]},
        config, ts, market.index[-1] + pd.Timedelta(minutes=1), 250.0,
    )
    assert len(r_full['trades']) == 1 and len(r_half['trades']) == 1
    assert r_half['trades'][0]['quantity'] < r_full['trades'][0]['quantity']


def _check_cluster_uses_one_global_position_and_declared_tie_break():
    eth, sol = _market(), _market()
    timestamp = eth.index[0]
    result = execute_cluster(
        {'ETHUSDT': (eth, pd.Series(dtype=float)),
         'SOLUSDT': (sol, pd.Series(dtype=float))},
        {'ETHUSDT': [_signal(timestamp, 'eth')],
         'SOLUSDT': [_signal(timestamp, 'sol')]},
        _config(), timestamp, eth.index[-1] + pd.Timedelta(minutes=1),
        symbol_priority=('ETHUSDT', 'SOLUSDT'),
    )
    assert len(result['trades']) == 1
    assert result['trades'][0]['symbol'] == 'ETHUSDT'
    assert result['trades'][0]['setup_id'] == 'eth'


def _check_pending_order_blocks_other_symbol_until_it_expires():
    eth, sol = _market(), _market()
    start = eth.index[0]
    result = execute_cluster(
        {'ETHUSDT': (eth, pd.Series(dtype=float)),
         'SOLUSDT': (sol, pd.Series(dtype=float))},
        {'ETHUSDT': [_signal(start, 'pending', limit=98.0)],
         'SOLUSDT': [_signal(start + pd.Timedelta(minutes=1), 'blocked')]},
        _config(), start, eth.index[-1] + pd.Timedelta(minutes=1),
        symbol_priority=('ETHUSDT', 'SOLUSDT'),
    )
    assert result['trades'] == []
    assert result['summary']['diagnostics']['blocked_pending_order'] == 1


def _check_actual_market_gap_respects_signal_stop_cap():
    eth = _market()
    eth.loc[eth.index[0], ['open', 'high', 'low', 'close']] = [102.0, 102.1, 101.9, 102.0]
    start = eth.index[0]
    signal = _signal(start, 'gap')
    result = execute_cluster(
        {'ETHUSDT': (eth, pd.Series(dtype=float))}, {'ETHUSDT': [signal]},
        replace(_config(), max_hold_minutes=3), start,
        eth.index[-1] + pd.Timedelta(minutes=1),
    )
    assert result['trades'] == []
    assert result['summary']['diagnostics']['blocked_stop_width_or_gap'] == 1


def _trailing_market():
    index = pd.date_range('2026-01-01', periods=4, freq='min', tz='UTC')
    return pd.DataFrame({
        'open':  [100.0, 100.0, 101.5, 103.0],
        'high':  [100.1, 101.5, 103.0, 103.1],
        'low':   [99.9,  99.9,  101.5, 101.8],
        'close': [100.0, 101.5, 103.0, 101.9],
        'volume': np.full(4, 10.0),
        'taker_buy_volume': np.full(4, 5.0),
    }, index=index)


def _check_trailing_moves_stop_to_breakeven_then_chandelier():
    eth = _trailing_market()
    start = eth.index[0]
    signal = _signal(start, 'runner')
    config = replace(_config(), target_r=5.0, partial_r=1.0, trailing=True, trail_atr=1.0,
                      max_hold_minutes=10)
    result = execute_cluster(
        {'ETHUSDT': (eth, pd.Series(dtype=float))}, {'ETHUSDT': [signal]},
        config, start, eth.index[-1] + pd.Timedelta(minutes=1),
    )
    assert len(result['trades']) == 1
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    # Entry at 100, initial stop 99. Runner reached 103 before pulling back to
    # 101.8; the chandelier trail (best - 1*ATR) must have locked in profit
    # far above the original 99 stop and above breakeven.
    assert trade['pnl'] > 0


def _check_trailing_requires_zero_partial_fraction():
    eth = _market()
    start = eth.index[0]
    signal = _signal(start, 'bad_config')
    config = replace(_config(), partial_fraction=0.4, trailing=True, trail_atr=1.0)
    try:
        execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))}, {'ETHUSDT': [signal]},
            config, start, eth.index[-1] + pd.Timedelta(minutes=1),
        )
        raised = False
    except ValueError:
        raised = True
    assert raised


class ClusterScalpSimulatorTests(unittest.TestCase):
    def test_cluster_uses_one_global_position_and_declared_tie_break(self):
        _check_cluster_uses_one_global_position_and_declared_tie_break()

    def test_pending_order_blocks_other_symbol_until_it_expires(self):
        _check_pending_order_blocks_other_symbol_until_it_expires()

    def test_actual_market_gap_respects_signal_stop_cap(self):
        _check_actual_market_gap_respects_signal_stop_cap()

    def test_trailing_moves_stop_to_breakeven_then_chandelier(self):
        _check_trailing_moves_stop_to_breakeven_then_chandelier()

    def test_trailing_requires_zero_partial_fraction(self):
        _check_trailing_requires_zero_partial_fraction()

    def test_two_consecutive_losses_block_the_rest_of_the_day(self):
        index = pd.date_range('2026-01-01', periods=20, freq='min', tz='UTC')
        eth = pd.DataFrame({
            'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.0,
            'volume': 10.0, 'taker_buy_volume': 5.0,
        }, index=index)
        for ts in (index[0], index[5], index[10]):
            eth.loc[ts, ['open', 'high', 'low', 'close']] = [100.0, 100.1, 98.0, 98.5]
        config = replace(
            _config(), max_hold_minutes=30, daily_loss_fraction=0.05,
            consecutive_loss_halt=2, consecutive_loss_halt_side='all',
        )
        signals = [
            _signal(index[0], 'loss1'),
            _signal(index[5], 'loss2'),
            _signal(index[10], 'should_block'),
        ]
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))}, {'ETHUSDT': signals},
            config, index[0], index[-1] + pd.Timedelta(minutes=1),
        )
        setups = [trade['setup'] for trade in result['trades']]
        self.assertEqual(setups, ['loss1', 'loss2'])
        self.assertGreaterEqual(
            result['summary']['diagnostics'].get('blocked_consecutive_loss_halt', 0), 1)

    def test_short_loss_streak_still_allows_a_long(self):
        index = pd.date_range('2026-01-01', periods=20, freq='min', tz='UTC')
        eth = pd.DataFrame({
            'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.0,
            'volume': 10.0, 'taker_buy_volume': 5.0,
        }, index=index)
        for ts in (index[0], index[5]):
            eth.loc[ts, ['open', 'high', 'low', 'close']] = [100.0, 102.0, 99.9, 101.5]
        eth.loc[index[10], ['open', 'high', 'low', 'close']] = [100.0, 100.1, 98.0, 98.5]
        config = replace(
            _config(), max_hold_minutes=30, daily_loss_fraction=0.05,
            consecutive_loss_halt=2, consecutive_loss_halt_side='short',
        )

        def short_signal(ts, name):
            item = _signal(ts, name)
            item['side'] = -1
            item['stop'] = 101.0
            return item

        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))},
            {'ETHUSDT': [
                short_signal(index[0], 'short1'),
                short_signal(index[5], 'short2'),
                _signal(index[10], 'long_ok'),
            ]},
            config, index[0], index[-1] + pd.Timedelta(minutes=1),
        )
        setups = [trade['setup'] for trade in result['trades']]
        self.assertIn('long_ok', setups)
        self.assertEqual(setups.count('short1') + setups.count('short2'), 2)

    def test_dollar_ratchet_locks_open_profit_into_the_stop(self):
        eth = _trailing_market()
        eth.loc[eth.index[-1], 'low'] = 101.4
        start = eth.index[0]
        config = replace(
            _config(), target_r=8.0, partial_r=1.0, trailing=True,
            trail_atr=10.0, max_hold_minutes=10, dollar_ratchet=True,
            dollar_ratchet_lock_fraction=0.5,
        )
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))},
            {'ETHUSDT': [_signal(start, 'ratchet')]},
            config, start, eth.index[-1] + pd.Timedelta(minutes=1),
        )
        self.assertEqual(len(result['trades']), 1)
        trade = result['trades'][0]
        self.assertEqual(trade['reason'], 'STOP')
        self.assertGreater(trade['pnl'], 0)

    def test_wider_drawdown_halt_lets_a_second_trade_open(self):
        index = pd.date_range('2026-01-01', periods=30, freq='min', tz='UTC')
        eth = pd.DataFrame({
            'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.0,
            'volume': 10.0, 'taker_buy_volume': 5.0,
        }, index=index)
        eth.loc[index[0], ['open', 'high', 'low', 'close']] = [100.0, 100.1, 90.0, 91.0]
        eth.loc[index[10], ['open', 'high', 'low', 'close']] = [100.0, 110.0, 99.9, 109.0]
        config = replace(
            _config(), max_hold_minutes=8, daily_loss_fraction=0.20,
            weekly_loss_fraction=0.25, drawdown_halt_fraction=0.25,
            drawdown_risk_scale_fraction=0.20, fixed_risk_usd=20.0,
            risk_fraction=0.10, max_notional_equity=8.0, max_margin_fraction=0.8,
            leverage=5, min_reward_cost_ratio=0, fee_bps=0, slippage_bps=0,
            maker_fee_bps=0,
        )
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))},
            {'ETHUSDT': [_signal(index[0], 'loss'), _signal(index[10], 'second')]},
            config, index[0], index[-1] + pd.Timedelta(minutes=1),
        )
        setups = [trade['setup'] for trade in result['trades']]
        self.assertIn('loss', setups)
        self.assertIn('second', setups)

    def test_same_side_signal_does_not_churn_the_open_leg(self):
        eth = _market(periods=30)
        start = eth.index[0]
        config = replace(
            _config(), max_hold_minutes=100, flip_on_opposite_signal=True,
            min_reward_cost_ratio=0, fee_bps=0, slippage_bps=0, maker_fee_bps=0,
        )
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))},
            {'ETHUSDT': [
                _signal(start, 'first'),
                _signal(eth.index[10], 'same_again'),
            ]},
            config, start, eth.index[-1] + pd.Timedelta(minutes=1),
        )
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['trades'][0]['setup'], 'first')

    def test_opposite_signal_flips_the_open_leg(self):
        eth = _market(periods=20)
        start = eth.index[0]
        config = replace(
            _config(), max_hold_minutes=100, flip_on_opposite_signal=True,
            min_reward_cost_ratio=0, fee_bps=0, slippage_bps=0, maker_fee_bps=0,
        )
        short = _signal(eth.index[6], 'flip_short')
        short['side'] = -1
        short['stop'] = 101.0
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float))},
            {'ETHUSDT': [_signal(start, 'first_long'), short]},
            config, start, eth.index[-1] + pd.Timedelta(minutes=1),
        )
        self.assertEqual(result['trades'][0]['reason'], 'FLIP')
        self.assertEqual(result['trades'][1]['side'], 'SHORT')

    def test_two_slots_can_hold_two_symbols_at_once(self):
        eth, sol = _market(), _market()
        timestamp = eth.index[0]
        config = replace(
            _config(), max_positions=2, max_hold_minutes=5,
            min_reward_cost_ratio=0, fee_bps=0, slippage_bps=0, maker_fee_bps=0,
        )
        result = execute_cluster(
            {'ETHUSDT': (eth, pd.Series(dtype=float)),
             'SOLUSDT': (sol, pd.Series(dtype=float))},
            {'ETHUSDT': [_signal(timestamp, 'eth')],
             'SOLUSDT': [_signal(timestamp, 'sol')]},
            config, timestamp, eth.index[-1] + pd.Timedelta(minutes=1),
            symbol_priority=('ETHUSDT', 'SOLUSDT'),
        )
        symbols = {trade['symbol'] for trade in result['trades']}
        self.assertEqual(symbols, {'ETHUSDT', 'SOLUSDT'})

