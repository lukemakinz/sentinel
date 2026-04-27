"""Simulator tests — mock L1Scanner and verify trade lifecycle."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings

from backtest.simulator import BacktestSimulator, BacktestConfig


def make_candle(close, high=None, low=None, volume=1000, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return {
        'open':   close * 0.999,
        'high':   high or close * 1.002,
        'low':    low  or close * 0.998,
        'close':  close,
        'volume': volume,
        'timestamp': ts,
    }


TRADE_CONTEXT = {
    'symbol': 'BTCUSDT', 'direction': 'LONG',
    'atr': 500.0, 'fvg_zone': [93000.0, 94000.0],
    'swept_level': 92500.0, 'funding_rate': 0.0003, 'adx_value': 28.0,
}

TRADE_PARAMS = {
    'symbol': 'BTCUSDT', 'side': 'LONG',
    'entry_price': 93250.0, 'stop_loss': 92400.0,
    'take_profits': [
        {'level': 94525.0, 'ratio': 0.40, 'label': 'TP1', 'runner': False},
        {'level': 95800.0, 'ratio': 0.40, 'label': 'TP2', 'runner': False},
        {'level': None,    'ratio': 0.20, 'label': 'TP3', 'runner': True},
    ],
    'r_value': 850.0, 'size_multiplier': 1.0, 'strategy': 'S1',
}


@override_settings(INITIAL_BALANCE=10000, MAX_RISK_PER_TRADE=0.005, MAX_LEVERAGE=10, MAX_MARGIN_PER_TRADE_PCT=0.15)
class SimulatorTradeLifecycleTest(TestCase):
    def setUp(self):
        self.config = BacktestConfig(
            symbol='BTCUSDT', strategy='S1',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 3, tzinfo=timezone.utc),
            initial_capital=10000.0,
            risk_per_trade=0.005,
        )
        self.sim = BacktestSimulator(self.config)

    def test_sl_hit_closes_position_with_loss(self):
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        self.assertEqual(len(self.sim.open_positions), 1)

        # Price drops to SL
        candle = make_candle(92000, low=92000)
        self.sim._update_positions(candle)
        self.assertEqual(len(self.sim.open_positions), 0)
        self.assertEqual(len(self.sim.closed_trades), 1)
        self.assertLess(self.sim.closed_trades[0]['pnl'], 0)

    def test_tp1_hit_closes_configured_ratio_and_moves_sl(self):
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        pos = self.sim.open_positions[0]
        initial_qty = pos['quantity']

        # Price reaches TP1
        candle = make_candle(95000, high=95000)
        self.sim._update_positions(candle)
        pos = self.sim.open_positions[0]  # still open (runner left)

        self.assertTrue(pos['tp1_hit'])
        self.assertAlmostEqual(pos['quantity'], initial_qty * 0.60, places=6)
        self.assertGreaterEqual(pos['stop_loss'], TRADE_PARAMS['entry_price'])

    def test_tp2_hit_leaves_runner_from_configured_ratios(self):
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        pos = self.sim.open_positions[0]
        original_qty = pos['quantity']

        # Hit TP1
        self.sim._update_positions(make_candle(95000, high=95000))
        # Hit TP2
        self.sim._update_positions(make_candle(96000, high=96000))

        pos = self.sim.open_positions[0]
        self.assertTrue(pos['tp2_hit'])
        self.assertAlmostEqual(pos['quantity'], original_qty * 0.20, places=6)
        self.assertAlmostEqual(pos['stop_loss'], TRADE_PARAMS['take_profits'][0]['level'], places=0)

    def test_partial_realization_is_recorded_in_closed_trade(self):
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        self.sim._update_positions(make_candle(95000, high=95000))
        self.sim._update_positions(make_candle(96000, high=96000))
        self.sim._update_positions(make_candle(94500, low=94400))

        self.assertEqual(len(self.sim.closed_trades), 1)
        trade = self.sim.closed_trades[0]
        self.assertEqual(len(trade['partials']), 2)
        self.assertGreater(trade['pnl'], 0)

    def test_s1c_runner_trailing_can_raise_stop_after_tp1(self):
        s1c_params = {
            **TRADE_PARAMS,
            'strategy': 'S1C',
            'take_profits': [
                {'level': 94000.0, 'ratio': 0.15, 'label': 'TP1', 'runner': False},
                {'level': 95000.0, 'ratio': 0.25, 'label': 'TP2', 'runner': False},
                {'level': None, 'ratio': 0.60, 'label': 'TP3', 'runner': True},
            ],
        }
        self.sim._open_position(s1c_params, datetime.now(timezone.utc))
        self.sim._update_positions(make_candle(94100, high=94100))
        pos = self.sim.open_positions[0]
        self.assertTrue(pos['tp1_hit'])
        self.assertGreaterEqual(pos['stop_loss'], pos['entry_price'])

    def test_stop_loss_has_priority_over_time_kill_when_same_candle_hits_both(self):
        opened_at = datetime.now(timezone.utc) - timedelta(hours=9)
        self.sim._open_position(TRADE_PARAMS, opened_at)

        candle = make_candle(92000, low=92350)
        self.sim._update_positions(candle)

        self.assertEqual(len(self.sim.closed_trades), 1)
        self.assertEqual(self.sim.closed_trades[0]['close_reason'], 'STOP_LOSS')

    def test_time_kill_closes_position_after_8h(self):
        opened_at = datetime.now(timezone.utc) - timedelta(hours=9)
        self.sim._open_position(TRADE_PARAMS, opened_at)

        # Price barely moved (no 1R hit)
        candle = make_candle(93300)
        self.sim._update_positions(candle)

        self.assertEqual(len(self.sim.open_positions), 0)
        self.assertEqual(self.sim.closed_trades[0]['close_reason'], 'TIME_KILL')

    def test_limit_order_fills_when_price_reaches_entry(self):
        self.sim._add_pending_order(TRADE_PARAMS, datetime.now(timezone.utc))
        self.assertEqual(len(self.sim.pending_orders), 1)

        # Candle low touches entry price
        candle = make_candle(93500, low=93200)
        self.sim._check_pending_fills(candle, datetime.now(timezone.utc))

        self.assertEqual(len(self.sim.pending_orders), 0)
        self.assertEqual(len(self.sim.open_positions), 1)

    def test_pending_order_does_not_fill_outside_entry_session(self):
        created_at = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)
        self.sim._add_pending_order(TRADE_PARAMS, created_at)
        self.assertEqual(self.sim.pending_orders[0]['entry_session'], 'ny')

        candle = make_candle(93500, low=93200, ts=datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc))
        self.sim._check_pending_fills(candle, candle['timestamp'])

        self.assertEqual(len(self.sim.pending_orders), 1)
        self.assertEqual(len(self.sim.open_positions), 0)

    def test_position_size_respects_risk_per_trade(self):
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        pos = self.sim.open_positions[0]

        # Max loss should be ~0.5% of capital = 50 USD
        r = TRADE_PARAMS['entry_price'] - TRADE_PARAMS['stop_loss']
        max_loss = pos['quantity'] * r
        self.assertAlmostEqual(max_loss, 10000 * 0.005, delta=5)

    def test_position_margin_respects_cap(self):
        aggressive = {**TRADE_PARAMS, 'leverage': 10, 'size_multiplier': 5.0}
        self.sim._open_position(aggressive, datetime.now(timezone.utc))
        pos = self.sim.open_positions[0]
        self.assertLessEqual(pos['margin_used'], 10000 * 0.15 + 1e-6)
        self.assertEqual(pos['margin_mode'], 'isolated')

    def test_no_position_opened_without_capital(self):
        self.sim.current_capital = 0
        self.sim._open_position(TRADE_PARAMS, datetime.now(timezone.utc))
        self.assertEqual(len(self.sim.open_positions), 0)


@override_settings(INITIAL_BALANCE=10000, MAX_RISK_PER_TRADE=0.005)
class SimulatorRunTest(TestCase):
    def test_run_with_no_candles_returns_empty_result(self):
        config = BacktestConfig(
            symbol='BTCUSDT', strategy='S1',
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        sim = BacktestSimulator(config)
        with patch.object(sim, '_load_candles', return_value=[]):
            result = sim.run()
        self.assertEqual(result.total_trades, 0)

    def test_run_returns_backtest_metrics(self):
        from backtest.metrics import BacktestMetrics
        config = BacktestConfig(symbol='BTCUSDT', strategy='S1',
                                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc))
        sim = BacktestSimulator(config)
        with patch.object(sim, '_load_candles', return_value=[]), \
             patch.object(sim, '_scan_l1', return_value=None):
            result = sim.run()
        self.assertIsInstance(result, BacktestMetrics)
