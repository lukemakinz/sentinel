from decimal import Decimal
from datetime import datetime, timezone, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone as tz

from ingester.models import AggTrade, WhaleThreshold
from ingester.tasks import recalculate_whale_threshold


def make_trade(symbol, usd_value, minutes_ago=0):
    ts = tz.now() - timedelta(minutes=minutes_ago)
    return AggTrade.objects.create(
        symbol=symbol,
        timestamp=ts,
        price=Decimal('30000.00'),
        quantity=Decimal(str(round(float(usd_value) / 30000, 8))),
        usd_value=Decimal(str(usd_value)),
        is_buyer_maker=False,
    )


@override_settings(TRADING_PAIRS=['BTCUSDT', 'ETHUSDT'])
class RecalculateWhaleThresholdTest(TestCase):
    def test_creates_threshold_from_95th_percentile(self):
        # 100 trades with usd_values 100, 200, ..., 10000
        for i in range(1, 101):
            make_trade('BTCUSDT', i * 100)

        recalculate_whale_threshold()

        threshold = WhaleThreshold.objects.filter(symbol='BTCUSDT').latest('timestamp')
        # 95th percentile of [100, 200, ..., 10000] ≈ 9500
        self.assertGreater(float(threshold.threshold_usd), 9000)
        self.assertLess(float(threshold.threshold_usd), 10100)

    def test_creates_threshold_for_each_pair(self):
        for i in range(1, 20):
            make_trade('BTCUSDT', i * 1000)
            make_trade('ETHUSDT', i * 500)

        recalculate_whale_threshold()

        self.assertTrue(WhaleThreshold.objects.filter(symbol='BTCUSDT').exists())
        self.assertTrue(WhaleThreshold.objects.filter(symbol='ETHUSDT').exists())

    def test_skips_symbol_with_insufficient_data(self):
        # Only 5 trades — below minimum of 10
        for i in range(5):
            make_trade('BTCUSDT', i * 1000)

        recalculate_whale_threshold()

        self.assertFalse(WhaleThreshold.objects.filter(symbol='BTCUSDT').exists())

    def test_ignores_trades_older_than_24h(self):
        # 15 recent trades + 15 old trades (25h ago)
        for i in range(1, 16):
            make_trade('BTCUSDT', i * 1000, minutes_ago=10)          # recent
            make_trade('BTCUSDT', i * 100000, minutes_ago=25 * 60)   # old → ignored

        recalculate_whale_threshold()

        threshold = WhaleThreshold.objects.filter(symbol='BTCUSDT').latest('timestamp')
        # Should be based only on recent trades (max 15000), not old ones (max 1500000)
        self.assertLess(float(threshold.threshold_usd), 20000)

    def test_task_name_is_correct(self):
        self.assertEqual(recalculate_whale_threshold.name, 'ingester.recalculate_whale_threshold')
