from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .candle_sync import sync_minute_candles
from .models import ScalpDecisionLog, ScalpPaperTrade
from .oi_history import fetch_recent_open_interest
from .tasks import CONFIG, evaluate_signal, manage_open_position


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class CandleSyncTests(TestCase):
    @patch('scalp_monitor.candle_sync.requests.get')
    def test_writes_new_candles_and_skips_existing(self, mock_get):
        from ingester.models import Candle

        now = timezone.now().replace(second=0, microsecond=0)
        last_closed = now - timedelta(minutes=1)
        open_ms = int((last_closed - timedelta(minutes=1)).timestamp() * 1000)
        mock_get.return_value = _FakeResponse([
            [open_ms, '100.0', '101.0', '99.0', '100.5', '10.0',
             open_ms + 59999, '1000.0', 5, '5.0', '500.0', '0'],
        ])
        Candle.objects.all().delete()
        written = sync_minute_candles('ETHUSDT', lookback_days=1)
        self.assertGreaterEqual(written, 1)
        self.assertTrue(Candle.objects.filter(symbol='ETHUSDT', interval='1m').exists())

    @patch('scalp_monitor.candle_sync.requests.get')
    def test_noop_when_already_up_to_date(self, mock_get):
        from ingester.models import Candle

        now = timezone.now().replace(second=0, microsecond=0)
        last_closed = now - timedelta(minutes=1)
        Candle.objects.create(
            symbol='ETHUSDT', interval='1m', timestamp=last_closed,
            open=1, high=1, low=1, close=1, volume=1, is_closed=True)
        written = sync_minute_candles('ETHUSDT', lookback_days=1)
        self.assertEqual(written, 0)
        mock_get.assert_not_called()


class OpenInterestHistoryTests(TestCase):
    @patch('scalp_monitor.oi_history.requests.get')
    def test_parses_into_expected_schema(self, mock_get):
        mock_get.return_value = _FakeResponse([
            {'symbol': 'ETHUSDT', 'sumOpenInterest': '123.4', 'timestamp': 1735689600000},
        ])
        frame = fetch_recent_open_interest('ETHUSDT', hours=1)
        self.assertEqual(list(frame.columns), [
            'open_interest', 'open_interest_value', 'toptrader_account_ratio',
            'toptrader_position_ratio', 'retail_account_ratio', 'taker_buy_sell_vol_ratio'])
        self.assertAlmostEqual(frame.open_interest.iloc[0], 123.4)

    @patch('scalp_monitor.oi_history.requests.get')
    def test_raises_on_empty_response(self, mock_get):
        mock_get.return_value = _FakeResponse([])
        with self.assertRaises(ValueError):
            fetch_recent_open_interest('ETHUSDT', hours=1)


class EvaluateSignalTests(TestCase):
    def test_blocks_when_a_position_is_already_open(self):
        ScalpPaperTrade.objects.create(
            symbol='ETHUSDT', side='LONG', status='OPEN', opened_at=timezone.now(),
            entry_price=100, initial_stop=99, stop_loss=99, atr_at_entry=1.0,
            r_value=1.0, best_price=100, quantity=0.5, notional_usd=50,
        )
        result = evaluate_signal()
        self.assertEqual(result['action'], 'blocked_open_position')
        self.assertEqual(ScalpDecisionLog.objects.count(), 1)

    @patch('scalp_monitor.tasks.sync_minute_candles')
    @patch('scalp_monitor.tasks._load_minutes', return_value=None)
    def test_logs_insufficient_history_and_moves_on(self, mock_minutes, mock_sync):
        result = evaluate_signal()
        self.assertEqual(result['action'], 'no_signal')
        self.assertEqual(
            ScalpDecisionLog.objects.filter(action='insufficient_history').count(), 3)

    @patch('scalp_monitor.tasks.get_perp_mark_price', return_value=2500.0)
    @patch('scalp_monitor.tasks.generate_order_block_oi_signals')
    @patch('scalp_monitor.tasks.oi_features')
    @patch('scalp_monitor.tasks.fetch_recent_open_interest')
    @patch('scalp_monitor.tasks._load_minutes')
    @patch('scalp_monitor.tasks.sync_minute_candles')
    def test_opens_a_trade_when_the_latest_bar_has_a_signal(
            self, mock_sync, mock_minutes, mock_oi, mock_features, mock_signals, mock_price):
        import pandas as pd
        index = pd.date_range('2026-01-01', periods=2, freq='15min', tz='UTC')
        mock_minutes.return_value = pd.DataFrame({'close': [1, 1]}, index=[index[0], index[0]])
        bars = pd.DataFrame({'close': [100.0, 101.0]}, index=index)
        mock_features.return_value = bars
        mock_signals.return_value = [{
            'timestamp': index[-1], 'side': 1, 'stop': 95.0, 'atr': 2.0,
            'setup_id': 'test-setup',
        }]
        result = evaluate_signal()
        self.assertEqual(result['action'], 'opened')
        trade = ScalpPaperTrade.objects.get(status='OPEN')
        self.assertEqual(trade.symbol, 'ETHUSDT')
        self.assertEqual(trade.side, 'LONG')
        self.assertEqual(trade.entry_price, 2500.0)
        self.assertEqual(trade.initial_stop, 95.0)
        self.assertAlmostEqual(trade.quantity, 0.50 / (2500.0 - 95.0))


class ManageOpenPositionTests(TestCase):
    def _trade(self, side='LONG', entry=100.0, stop=99.0, atr=1.0, **overrides):
        defaults = dict(
            symbol='ETHUSDT', side=side, status='OPEN', opened_at=timezone.now(),
            entry_price=entry, initial_stop=stop, stop_loss=stop, atr_at_entry=atr,
            r_value=abs(entry - stop), best_price=entry, quantity=0.5, notional_usd=50,
        )
        defaults.update(overrides)
        return ScalpPaperTrade.objects.create(**defaults)

    def test_noop_without_an_open_trade(self):
        result = manage_open_position()
        self.assertEqual(result['action'], 'no_open_position')

    @patch('scalp_monitor.tasks.get_perp_mark_price', return_value=98.5)
    def test_stop_loss_closes_the_trade(self, mock_price):
        trade = self._trade()
        result = manage_open_position()
        self.assertEqual(result['reason'], 'STOP')
        trade.refresh_from_db()
        self.assertEqual(trade.status, 'CLOSED')
        self.assertEqual(trade.exit_reason, 'STOP')
        self.assertLess(trade.realized_pnl_usd, 0)

    @patch('scalp_monitor.tasks.get_perp_mark_price', return_value=108.0)
    def test_target_r_closes_the_trade(self, mock_price):
        # target = entry + target_r * r_value = 100 + 8*1 = 108
        trade = self._trade()
        result = manage_open_position()
        self.assertEqual(result['reason'], 'TARGET')
        trade.refresh_from_db()
        self.assertEqual(trade.status, 'CLOSED')
        self.assertGreater(trade.realized_pnl_usd, 0)

    @patch('scalp_monitor.tasks.get_perp_mark_price', return_value=100.2)
    def test_time_stop_closes_after_max_hold(self, mock_price):
        old = timezone.now() - timedelta(minutes=CONFIG.max_hold_minutes + 5)
        trade = self._trade(opened_at=old)
        result = manage_open_position()
        self.assertEqual(result['reason'], 'TIME')
        trade.refresh_from_db()
        self.assertEqual(trade.status, 'CLOSED')

    @patch('scalp_monitor.tasks.get_perp_mark_price', return_value=101.6)
    def test_breakeven_activates_at_partial_r_and_moves_stop_up(self, mock_price):
        # partial_r=1.5 -> activation at entry+1.5*r = 101.5; price 101.6 clears it.
        trade = self._trade()
        result = manage_open_position()
        self.assertEqual(result['action'], 'held')
        trade.refresh_from_db()
        self.assertTrue(trade.breakeven_activated)
        self.assertGreater(trade.stop_loss, trade.initial_stop)
        self.assertEqual(trade.best_price, 101.6)

    @patch('scalp_monitor.tasks.get_perp_mark_price')
    def test_chandelier_trail_only_moves_favorably(self, mock_price):
        trade = self._trade(breakeven_activated=True, best_price=105.0, stop_loss=102.0)
        mock_price.return_value = 103.0  # below best_price; trail must not retreat
        manage_open_position()
        trade.refresh_from_db()
        self.assertEqual(trade.best_price, 105.0)  # unchanged, not lowered
        self.assertGreaterEqual(trade.stop_loss, 102.0)  # never loosened
