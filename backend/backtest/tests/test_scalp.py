"""Execution invariants and anti-lookahead regression tests for S7."""
from dataclasses import replace
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from backtest.scalp_data import validate_minutes
from backtest.scalp_simulator import execute
from l1_filter.scalp_strategy import (
    ScalpConfig, build_features, divergence_events, generate_signals, resample_closed,
)
from l1_filter.scalp_strategy_v2 import RevisionConfig, revision_features, revision_signals
from l1_filter.profile_routes import ProfileRouteConfig, route_features, route_signals
from l1_filter.price_action_scalp import action_features, action_signals, ActionConfig, connors_rsi
from l1_filter.mean_reversion_scalp import S8Config, s8_features, s8_signals
from l1_filter.mean_reversion_scalp_v2 import S8v2Config, s8v2_features, s8v2_signals
from l1_filter.session_momentum_scalp import (
    SessionMomentumConfig, session_momentum_features, session_momentum_signals,
)


def candles(rows):
    frame = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'])
    frame.index = pd.date_range('2026-01-01', periods=len(frame), freq='min', tz='UTC')
    frame['volume'], frame['taker_buy_volume'] = 10.0, 6.0
    return frame


def signal(frame, i=0, side=1, stop=None):
    return {'timestamp': frame.index[i], 'side': side, 'stop': stop or (99 if side == 1 else 101),
            'atr': 1.0, 'reference': 100, 'score': 3, 'setup': 'test'}


def replay(frame, signals=None, config=None, funding=None):
    config = config or ScalpConfig()
    features = pd.DataFrame({'atr': np.ones(len(frame))}, index=frame.index)
    return execute(frame, pd.Series(dtype=float) if funding is None else funding,
                   [signal(frame)] if signals is None else signals, features, config,
                   frame.index[0], frame.index[-1] + pd.Timedelta(minutes=1))


class ExecutionTests(unittest.TestCase):
    def test_fixed_margin_and_risk_are_caps_not_profit_multipliers(self):
        frame = candles([(100, 100.1, 99.9, 100)])
        config = replace(ScalpConfig(), leverage=20, fixed_margin_usd=10,
                         fixed_risk_usd=2.5, max_notional_equity=3)
        trade = replay(frame, config=config)['trades'][0]
        self.assertLessEqual(trade['initial_margin'], 10)
        self.assertLessEqual(trade['quantity'] * trade['entry'], 200)

    def test_explicit_profile_target_and_dollar_filter(self):
        frame = candles([(100, 104, 99.9, 103)])
        setup = {**signal(frame), 'target_price': 103, 'min_target_r': 2.5}
        config = replace(ScalpConfig(), partial_fraction=0, trailing=False)
        trade = replay(frame, [setup], config)['trades'][0]
        self.assertEqual(trade['reason'], 'TARGET')
        self.assertAlmostEqual(trade['exits'][0]['price'], 103 * (1-.0002))
        setup['min_profit_usd'] = 1000
        result = replay(frame, [setup], config)
        self.assertEqual(result['summary']['trades'], 0)
        self.assertEqual(result['summary']['diagnostics']['blocked_dollar_profit_target'], 1)

    def test_leverage_changes_margin_not_fixed_risk_pnl(self):
        frame = candles([(100, 100.1, 99.9, 100)])
        results = []
        for leverage in (20, 30):
            config = replace(ScalpConfig(), leverage=leverage, max_margin_fraction=.15,
                             max_notional_equity=3)
            results.append(replay(frame, config=config)['trades'][0])
        a, b = results
        self.assertAlmostEqual(a['pnl'], b['pnl'])
        self.assertAlmostEqual(a['quantity'], b['quantity'])
        self.assertAlmostEqual(a['initial_margin'] / b['initial_margin'], 1.5)
        self.assertAlmostEqual(b['margin_return_pct'] / a['margin_return_pct'], 1.5)

    def test_wide_stop_rejected_by_margin_buffer(self):
        frame = candles([(100, 100.1, 99.9, 100)])
        config = replace(ScalpConfig(), leverage=30, max_margin_fraction=.15)
        result = replay(frame, [signal(frame, stop=98)], config)
        self.assertEqual(result['summary']['diagnostics']['blocked_margin_stop_buffer'], 1)

    def test_limit_requires_penetration_and_no_same_bar_target(self):
        frame = candles([(100, 100.1, 99.49, 100), (100, 104, 99.47, 100)])
        setup = {**signal(frame, stop=98.5), 'limit_price': 99.5, 'limit_ttl_minutes': 5}
        trade = replay(frame, [setup])['trades'][0]
        self.assertEqual(trade['opened_at'], str(frame.index[1]))
        self.assertEqual(trade['reason'], 'END_OF_TEST')
        self.assertEqual(len(trade['exits']), 1)
        self.assertAlmostEqual(trade['entry'], 99.5)
        exit_price = trade['exits'][0]['price']
        self.assertAlmostEqual(trade['fees'], trade['quantity'] * (99.5 * .0002 + exit_price * .0005))

    def test_limit_expiration(self):
        frame = candles([(100, 100.1, 99.9, 100), (100, 100.1, 99, 100)])
        setup = {**signal(frame, stop=98.5), 'limit_price': 99.5, 'limit_ttl_minutes': 1}
        result = replay(frame, [setup])
        self.assertEqual(result['summary']['trades'], 0)
        self.assertEqual(result['summary']['diagnostics']['expired_limit'], 1)

    def test_marketable_limit_does_not_receive_maker_fill(self):
        frame = candles([(100, 100.1, 99.9, 100)])
        result = replay(frame, [{**signal(frame), 'limit_price': 100.1}])
        self.assertEqual(result['summary']['trades'], 0)
        self.assertEqual(result['summary']['diagnostics']['blocked_marketable_limit'], 1)

    def test_limit_fill_can_stop_out_same_minute(self):
        frame = candles([(100, 104, 98, 100)])
        setup = {**signal(frame, stop=98.5), 'limit_price': 99.5}
        trade = replay(frame, [setup])['trades'][0]
        self.assertEqual(trade['reason'], 'STOP')
        self.assertLess(trade['pnl'], 0)

    def test_stop_precedes_target_when_both_touched(self):
        result = replay(candles([(100, 104, 98, 102)]))
        trade = result['trades'][0]
        self.assertEqual(trade['reason'], 'STOP')
        self.assertEqual(len(trade['exits']), 1)
        self.assertLess(trade['pnl'], 0)

    def test_new_trail_only_active_next_minute_and_gap_fill(self):
        frame = candles([(100, 101.7, 99.5, 101), (100, 100.5, 99.5, 100)])
        result = replay(frame)
        exits = result['trades'][0]['exits']
        self.assertEqual([x['reason'] for x in exits], ['PARTIAL', 'STOP'])
        self.assertNotEqual(exits[0]['timestamp'], exits[1]['timestamp'])
        self.assertAlmostEqual(exits[1]['price'], 100 * (1 - .0002))

    def test_adverse_slippage_both_sides_and_fee_ledger(self):
        frame = candles([(100, 100.1, 99.9, 100)])
        for side in (1, -1):
            result = replay(frame, [signal(frame, side=side)])
            trade = result['trades'][0]
            self.assertEqual(trade['reason'], 'END_OF_TEST')
            self.assertAlmostEqual(trade['entry'], 100 * (1 + side * .0002))
            self.assertAlmostEqual(trade['exits'][0]['price'], 100 * (1 - side * .0002))
            self.assertLess(trade['pnl'], 0)
            self.assertAlmostEqual(trade['gross_pnl'] - trade['fees'] + trade['funding_pnl'], trade['pnl'])
            self.assertAlmostEqual(result['equity_hourly'][-1]['equity'] - 10000, trade['pnl'])

    def test_historical_funding_signed_and_not_charged_before_entry(self):
        frame = candles([(100, 100.1, 99.9, 100)] * 2)
        rates = pd.Series([.01, .001], index=frame.index)
        for side in (1, -1):
            trade = replay(frame, [signal(frame, side=side)], funding=rates)['trades'][0]
            self.assertAlmostEqual(trade['funding_pnl'], -side * trade['quantity'] * 100 * .001)

    def test_initial_risk_includes_stop_costs(self):
        result = replay(candles([(100, 100.1, 98.9, 99)]))
        self.assertAlmostEqual(result['trades'][0]['pnl'], -25)

    def test_mark_to_market_drawdown_includes_open_loss(self):
        frame = candles([(100, 100.1, 99.2, 99.3), (99.3, 100.2, 99.2, 100.1)])
        result = replay(frame)
        self.assertGreater(result['summary']['max_drawdown_pct'], .1)

    def test_one_position_and_time_exit(self):
        frame = candles([(100, 100.1, 99.9, 100)] * 3)
        result = replay(frame, [signal(frame, 0), signal(frame, 1)],
                        replace(ScalpConfig(), max_hold_minutes=2))
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['trades'][0]['reason'], 'TIME')
        self.assertEqual(result['summary']['diagnostics']['blocked_open_position'], 1)

    def test_daily_loss_blocks_reentry(self):
        frame = candles([(100, 100.1, 98, 99), (100, 100.1, 99.9, 100)])
        result = replay(frame, [signal(frame, 0), signal(frame, 1)],
                        replace(ScalpConfig(), daily_loss_fraction=.001))
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['summary']['diagnostics']['blocked_daily_loss_or_capital'], 1)

    def test_missing_data_rejected(self):
        frame = candles([(100, 101, 99, 100)] * 3).iloc[[0, 2]]
        with self.assertRaisesRegex(ValueError, 'Missing minutes'):
            validate_minutes(frame)

    def test_no_trades_is_explicit(self):
        result = replay(candles([(100, 101, 99, 100)]), [])
        self.assertEqual(result['summary']['zero_trade_days'], 1)
        self.assertEqual(result['summary']['net_pnl'], 0)
        self.assertIsNone(result['summary']['profit_factor'])

    def test_poc_boundary_rechecked_after_entry_gap(self):
        frame = candles([(101, 101.1, 100.9, 101)])
        setup = {**signal(frame), 'target_boundary': 103}
        self.assertEqual(replay(frame, [setup])['summary']['trades'], 0)


class CausalityTests(unittest.TestCase):
    def test_profile_routes_and_price_action_do_not_repaint(self):
        rng = np.random.default_rng(723)
        close = 100 + np.cumsum(rng.normal(0, .03, 18000))
        frame = candles(list(zip(close, close + .06, close - .06, close)))
        frame['volume'] = rng.uniform(5, 20, len(frame))
        frame['taker_buy_volume'] = frame.volume * rng.uniform(.2, .8, len(frame))
        for days in (1, 3):
            full, prefix = route_features(frame, 5, days), route_features(frame.iloc[:15000], 5, days)
            assert_frame_equal(full.loc[prefix.index], prefix)
            config = ProfileRouteConfig('test', minutes=5, profile_days=days)
            self.assertEqual([x for x in route_signals(full, config) if x['timestamp'] <= prefix.index[-1]],
                             route_signals(prefix, config))
        full, prefix = action_features(frame), action_features(frame.iloc[:15000])
        assert_frame_equal(full.loc[prefix.index], prefix)
        for setup in ('pullback', 'sweep_fvg'):
            for oscillator in ('none', 'crsi', 'stoch_rsi', 'macd'):
                config = ActionConfig('test', setup, oscillator)
                self.assertEqual([x for x in action_signals(full, config) if x['timestamp'] <= prefix.index[-1]],
                                 action_signals(prefix, config))

    def test_crsi_stays_bounded_and_requires_rank_warmup(self):
        close = pd.Series(100 + np.sin(np.arange(300) / 3))
        crsi = connors_rsi(close)
        self.assertTrue(crsi.iloc[:101].isna().all())
        self.assertTrue(crsi.dropna().between(0, 100).all())

    def test_profile_routes_never_signal_against_the_htf_bias(self):
        """Trend-only revision: no countertrend exception, no matter the setup."""
        rng = np.random.default_rng(19)
        close = 100 + np.cumsum(rng.normal(0, .03, 18000))
        frame = candles(list(zip(close, close + .06, close - .06, close)))
        frame['volume'] = rng.uniform(5, 20, len(frame))
        frame['taker_buy_volume'] = frame.volume * rng.uniform(.2, .8, len(frame))
        bars = route_features(frame, 5, 1)
        config = ProfileRouteConfig('test', minutes=5, profile_days=1)
        records = route_signals(bars, config)
        self.assertTrue(records)
        for record in records:
            self.assertFalse(record['countertrend'])
            bias = bars.bias4h.loc[record['timestamp']]
            self.assertEqual(bias, record['side'])

    def test_revision_features_and_signals_are_causal(self):
        rng = np.random.default_rng(72)
        close = 100 + np.cumsum(rng.normal(0, .05, 6000))
        frame = candles(list(zip(close, close + .1, close - .1, close)))
        for interval in (5, 15, 60):
            full = revision_features(frame, interval)
            prefix = revision_features(frame.iloc[:4500], interval)
            assert_frame_equal(full.loc[prefix.index], prefix)
            for setup in ('absorption', 'exhaustion', 'breakout_retest',
                          'channel_breakout', 'squeeze_breakout', 'range_sweep'):
                config = RevisionConfig('test', setup, minutes=interval, entry_style='limit')
                expected = [x for x in revision_signals(full, config) if x['timestamp'] <= prefix.index[-1]]
                self.assertEqual(expected, revision_signals(prefix, config))

    def test_partial_bar_is_never_published(self):
        frame = candles([(100, 101, 99, 100)] * 7)
        bars = resample_closed(frame, 5)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars.index[0], frame.index[5])

    def test_divergence_waits_for_confirmation(self):
        bars = pd.DataFrame({'low': [12, 11, 9, 11, 12, 11, 8, 11, 12],
                             'high': [13] * 9,
                             'rsi14': [50, 40, 20, 40, 50, 40, 30, 40, 50],
                             'cvd': [0, 0, -10, 0, 0, 0, -5, 0, 0]})
        rsi, cvd = divergence_events(bars, 1)
        self.assertFalse(rsi[:8].any())
        self.assertFalse(cvd[:8].any())
        self.assertTrue(rsi[8] and cvd[8])

    def test_future_data_does_not_change_features_or_signals(self):
        rng = np.random.default_rng(7)
        close = 100 + np.cumsum(rng.normal(0, .05, 4500))
        frame = candles(list(zip(close, close + .1, close - .1, close)))
        frame['taker_buy_volume'] = rng.uniform(1, 9, len(frame))
        for profile in ('previous_day', 'rolling_6h'):
            for interval in (5, 15):
                full = build_features(frame, interval, profile)
                prefix = build_features(frame.iloc[:3600], interval, profile)
                assert_frame_equal(full.loc[prefix.index], prefix)
                config = ScalpConfig(minutes=interval, profile=profile, mode='hybrid')
                expected = [x for x in generate_signals(full, config) if x['timestamp'] <= prefix.index[-1]]
                self.assertEqual(expected, generate_signals(prefix, config))

    @staticmethod
    def _ranging_frame(rng):
        # Neither a pure random walk (never re-enters its own 24h range) nor
        # a smooth sine (each half-cycle is itself a sustained, high-ADX
        # trend) exercises S8's regime filter. Use a mean-reverting
        # (Ornstein-Uhlenbeck-like) process instead: low ADX and range
        # containment are then the TYPICAL condition, matching the chop
        # regime S8 is designed to trade rather than an edge case.
        n = 18000
        price = np.empty(n)
        price[0] = 100.0
        k = 0.02
        noise = rng.normal(0, .04, n)
        for i in range(1, n):
            price[i] = price[i - 1] + k * (100.0 - price[i - 1]) + noise[i]
        close = price
        frame = candles(list(zip(close, close + .06, close - .06, close)))
        frame['volume'] = rng.uniform(5, 20, len(frame))
        frame['taker_buy_volume'] = frame.volume * rng.uniform(.2, .8, len(frame))
        return frame

    def test_s8_features_and_signals_are_causal(self):
        frame = self._ranging_frame(np.random.default_rng(58))
        for minutes in (5, 15):
            config = S8Config('test', minutes=minutes)
            full, prefix = s8_features(frame, config), s8_features(frame.iloc[:15000], config)
            assert_frame_equal(full.loc[prefix.index], prefix)
            expected = [x for x in s8_signals(full, config) if x['timestamp'] <= prefix.index[-1]]
            self.assertEqual(expected, s8_signals(prefix, config))
            self.assertTrue(expected, 'test fixture produced no signals to check causality on')

    def test_s8_signals_are_regime_gated_not_trend_gated(self):
        """Opposite filter from S7 trend-only: requires the ABSENCE of a
        trend (low ADX, contained range), never agreement with one."""
        frame = self._ranging_frame(np.random.default_rng(61))
        config = S8Config('test', minutes=5)
        bars = s8_features(frame, config)
        records = s8_signals(bars, config)
        self.assertTrue(records)
        for record in records:
            row = bars.loc[record['timestamp']]
            self.assertLessEqual(row.htf_adx, config.adx_threshold)
            self.assertTrue(bool(row.contained))
            # No trend requirement of any kind, either direction.
            self.assertIn(record['side'], (1, -1))

    def test_s8_risk_per_trade_is_independent_of_leverage(self):
        frame = candles([(100, 100.1, 99.4, 100)] * 3)
        setup = {'timestamp': frame.index[0], 'side': 1, 'stop': 99, 'atr': 1.0,
                'reference': 100, 'score': 0, 'setup': 'profile_edge',
                'target_price': 101, 'limit_price': 99.5, 'limit_ttl_minutes': 30}
        features = pd.DataFrame({'atr': np.ones(len(frame))}, index=frame.index)
        low_lev = S8Config('test', leverage=5).execution()
        high_lev = S8Config('test', leverage=20).execution()
        low = execute(frame, pd.Series(dtype=float), [setup], features, low_lev,
                      frame.index[0], frame.index[-1] + pd.Timedelta(minutes=1))['trades'][0]
        high = execute(frame, pd.Series(dtype=float), [setup], features, high_lev,
                       frame.index[0], frame.index[-1] + pd.Timedelta(minutes=1))['trades'][0]
        self.assertAlmostEqual(low['quantity'], high['quantity'])
        self.assertAlmostEqual(low['pnl'], high['pnl'])
        self.assertGreater(low['initial_margin'], high['initial_margin'])

    def test_s8v2_features_and_signals_are_causal(self):
        frame = self._ranging_frame(np.random.default_rng(58))
        for minutes in (5, 15):
            config = S8v2Config('test', minutes=minutes)
            full, prefix = s8v2_features(frame, config), s8v2_features(frame.iloc[:15000], config)
            assert_frame_equal(full.loc[prefix.index], prefix)
            expected = [x for x in s8v2_signals(full, config) if x['timestamp'] <= prefix.index[-1]]
            self.assertEqual(expected, s8v2_signals(prefix, config))
            self.assertTrue(expected, 'test fixture produced no signals to check causality on')

    def test_s8v2_signals_require_a_rejection_candle_and_fix_exit_geometry(self):
        """The v1->v2 fix: entry needs a wick-through-and-reclaim rejection
        candle (not just presence of the level), stop sits behind that wick,
        and target is a small ATR multiple (not a large value-area fraction)."""
        frame = self._ranging_frame(np.random.default_rng(61))
        config = S8v2Config('test', minutes=5, target_atr_mult=1.25)
        bars = s8v2_features(frame, config)
        records = s8v2_signals(bars, config)
        self.assertTrue(records)
        for record in records:
            row = bars.loc[record['timestamp']]
            self.assertLessEqual(row.htf_adx, config.adx_threshold)
            self.assertTrue(bool(row.contained))
            side = record['side']
            if record['setup'] == 'profile_edge':
                level = row.val if side == 1 else row.vah
            else:
                level = row.vwap_lower if side == 1 else row.vwap_upper
            if side == 1:
                self.assertLess(row.low, level)
                self.assertGreaterEqual(row.close, level)
                self.assertGreater(row.close, row.open)
                wick = row.low
            else:
                self.assertGreater(row.high, level)
                self.assertLessEqual(row.close, level)
                self.assertLess(row.close, row.open)
                wick = row.high
            self.assertAlmostEqual(record['stop'], wick - side * config.stop_buffer_atr_mult * row.atr)
            self.assertAlmostEqual(record['target_price'], level + side * config.target_atr_mult * row.atr)

    def test_s8v2_risk_per_trade_is_independent_of_leverage(self):
        frame = candles([(100, 100.1, 99.4, 100)] * 3)
        setup = {'timestamp': frame.index[0], 'side': 1, 'stop': 99, 'atr': 1.0,
                'reference': 100, 'score': 0, 'setup': 'profile_edge',
                'target_price': 101, 'limit_price': 99.5, 'limit_ttl_minutes': 30}
        features = pd.DataFrame({'atr': np.ones(len(frame))}, index=frame.index)
        low_lev = S8v2Config('test', leverage=5).execution()
        high_lev = S8v2Config('test', leverage=20).execution()
        low = execute(frame, pd.Series(dtype=float), [setup], features, low_lev,
                      frame.index[0], frame.index[-1] + pd.Timedelta(minutes=1))['trades'][0]
        high = execute(frame, pd.Series(dtype=float), [setup], features, high_lev,
                       frame.index[0], frame.index[-1] + pd.Timedelta(minutes=1))['trades'][0]
        self.assertAlmostEqual(low['quantity'], high['quantity'])
        self.assertAlmostEqual(low['pnl'], high['pnl'])
        self.assertGreater(low['initial_margin'], high['initial_margin'])

    def test_s9_features_are_causal(self):
        rng = np.random.default_rng(91)
        close = 100 + np.cumsum(rng.normal(0.001, 0.05, 18000))
        frame = candles(list(zip(close, close + .08, close - .08, close)))
        frame['volume'] = rng.uniform(5, 20, len(frame))
        frame['taker_buy_volume'] = frame.volume * rng.uniform(.2, .8, len(frame))
        full = session_momentum_features(frame, 5)
        prefix = session_momentum_features(frame.iloc[:15000], 5)

        assert_frame_equal(full.loc[prefix.index], prefix)

    def test_s9_requires_regime_location_trigger_and_x_of_y_score(self):
        index = pd.date_range('2026-01-01 08:00', periods=5, freq='5min', tz='UTC')
        bars = pd.DataFrame({
            'open': [100, 100, 100, 100.1, 100.2],
            'high': [100.4, 100.4, 100.4, 100.5, 101.2],
            'low': [99.8, 99.7, 99.5, 99.7, 100.1],
            'close': [100.1, 100.1, 100.0, 100.0, 101.0],
            'ema9': [100, 100, 100, 100.0, 100.5],
            'ema20': [100, 100, 100, 100.0, 100.2],
            'session_vwap': [100, 100, 100, 100.0, 100.2],
            'rsi5': [48, 49, 48, 45, 58],
            'delta_ratio': [0, 0, 0, -0.1, 0.2],
            'relative_volume': [1, 1, 1, .9, 1.4],
            'htf_bias': [1] * 5,
            'htf_adx': [25] * 5,
            'atr': [1] * 5,
            'prior_high3': [np.nan, np.nan, np.nan, 100.4, 100.5],
            'prior_low3': [np.nan, np.nan, np.nan, 99.5, 99.5],
        }, index=index)
        config = SessionMomentumConfig('test', minutes=5, min_score=3)
        records = session_momentum_signals(bars, config)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['timestamp'], index[-1])
        self.assertEqual(records[0]['side'], 1)
        self.assertGreaterEqual(records[0]['score'], 3)
        self.assertLess(records[0]['stop'], bars.close.iloc[-1])


if __name__ == '__main__':
    unittest.main()
