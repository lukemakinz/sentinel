from decimal import Decimal
from datetime import datetime, timezone

from django.test import TestCase

from ingester.models import AggTrade, WhaleThreshold, WhaleCVD, RetailCVD


class AggTradeModelTest(TestCase):
    def test_create_aggtrade(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        trade = AggTrade.objects.create(
            symbol='BTCUSDT',
            timestamp=ts,
            price=Decimal('30000.00'),
            quantity=Decimal('0.50000000'),
            usd_value=Decimal('15000.00'),
            is_buyer_maker=False,
        )
        self.assertEqual(trade.symbol, 'BTCUSDT')
        self.assertEqual(trade.usd_value, Decimal('15000.00'))
        self.assertFalse(trade.is_buyer_maker)

    def test_str_representation(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        trade = AggTrade(symbol='BTCUSDT', timestamp=ts, price=Decimal('30000'), quantity=Decimal('1'), usd_value=Decimal('30000'), is_buyer_maker=True)
        self.assertIn('BTCUSDT', str(trade))


class WhaleThresholdModelTest(TestCase):
    def test_create_whale_threshold(self):
        threshold = WhaleThreshold.objects.create(
            symbol='BTCUSDT',
            threshold_usd=Decimal('10000.00'),
        )
        self.assertEqual(threshold.symbol, 'BTCUSDT')
        self.assertEqual(threshold.threshold_usd, Decimal('10000.00'))

    def test_latest_threshold_per_symbol(self):
        WhaleThreshold.objects.create(symbol='BTCUSDT', threshold_usd=Decimal('8000.00'))
        WhaleThreshold.objects.create(symbol='BTCUSDT', threshold_usd=Decimal('12000.00'))
        latest = WhaleThreshold.objects.filter(symbol='BTCUSDT').latest('timestamp')
        self.assertEqual(latest.threshold_usd, Decimal('12000.00'))


class WhaleCVDModelTest(TestCase):
    def test_create_whale_cvd(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cvd = WhaleCVD.objects.create(
            symbol='BTCUSDT',
            timestamp=ts,
            cumulative_delta=Decimal('150000.00'),
        )
        self.assertEqual(cvd.cumulative_delta, Decimal('150000.00'))

    def test_cvd_can_be_negative(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cvd = WhaleCVD.objects.create(symbol='BTCUSDT', timestamp=ts, cumulative_delta=Decimal('-50000.00'))
        self.assertLess(cvd.cumulative_delta, 0)


class RetailCVDModelTest(TestCase):
    def test_create_retail_cvd(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cvd = RetailCVD.objects.create(
            symbol='ETHUSDT',
            timestamp=ts,
            cumulative_delta=Decimal('-2500.00'),
        )
        self.assertEqual(cvd.symbol, 'ETHUSDT')
        self.assertLess(cvd.cumulative_delta, 0)
