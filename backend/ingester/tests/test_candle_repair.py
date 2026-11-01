import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from ingester.models import Candle
from ingester.tasks import backfill_candles, repair_missed_candle_closes


def candle(symbol, interval, ts, closed):
    return Candle.objects.create(
        symbol=symbol, interval=interval, timestamp=ts, open=Decimal('1'),
        high=Decimal('1'), low=Decimal('1'), close=Decimal('1'),
        volume=Decimal('1'), is_closed=closed,
    )


class CandleRepairTest(TestCase):
    def test_only_bars_past_close_plus_grace_are_refetched(self):
        now = timezone.now().replace(second=0, microsecond=0)
        candle('BTCUSDT', '15m', now - timedelta(minutes=45), False)  # lost close
        candle('BTCUSDT', '15m', now - timedelta(minutes=5), False)   # still forming
        candle('ETHUSDT', '1h', now - timedelta(hours=3), True)       # fine

        with patch('ingester.binance_rest.BinanceRESTClient.fetch_historical_candles') as fetch:
            result = repair_missed_candle_closes()

        self.assertEqual(result['repaired_series'], 1)
        symbol, interval, limit = fetch.call_args.args
        self.assertEqual((symbol, interval, limit), ('BTCUSDT', '15m', 1500))
        start_ms = fetch.call_args.kwargs['start_ms']
        self.assertEqual(start_ms, int((now - timedelta(minutes=45)).timestamp() * 1000))

    def test_nothing_stale_makes_no_requests(self):
        with patch('ingester.binance_rest.BinanceRESTClient.fetch_historical_candles') as fetch:
            self.assertEqual(repair_missed_candle_closes()['repaired_series'], 0)
        fetch.assert_not_called()


class RestClosedFlagTest(TestCase):
    def test_in_progress_bar_is_not_marked_closed(self):
        from ingester.binance_rest import BinanceRESTClient

        now_ms = int(time.time() * 1000)
        hour = 3_600_000
        start = now_ms - now_ms % hour

        def k(open_ms):
            return [open_ms, '1', '2', '0.5', '1.5', '10', open_ms + hour - 1,
                    '15', 3, '5', '7', '0']

        with patch.object(BinanceRESTClient, '_get', return_value=[k(start - hour), k(start)]):
            BinanceRESTClient().fetch_historical_candles('XRPUSDT', '1h', 2)

        flags = dict(Candle.objects.filter(symbol='XRPUSDT').values_list('timestamp', 'is_closed'))
        self.assertEqual(sorted(flags.values()), [False, True])


class BreadthBackfillTest(TestCase):
    @override_settings(
        TRADING_PAIRS=['BTCUSDT'], GLOBAL_CONTEXT_PAIRS=['BTCUSDT'],
        BREADTH_PAIRS=['BTCUSDT', 'XRPUSDT'],
        BREADTH_INTERVALS=['15m', '1h', '4h'],
    )
    def test_startup_warms_breadth_before_m3_can_use_it(self):
        with patch(
            'ingester.binance_rest.BinanceRESTClient.fetch_historical_candles',
        ) as fetch:
            backfill_candles()

        calls = [call.args for call in fetch.call_args_list]
        self.assertIn(('XRPUSDT', '15m', 100), calls)
        self.assertIn(('XRPUSDT', '1h', 220), calls)
        self.assertIn(('XRPUSDT', '4h', 220), calls)
