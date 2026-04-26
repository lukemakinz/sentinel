"""Liquidity level tracker tests."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from django.test import TestCase
from ingester.models import Candle
from l1_filter.liquidity import (
    compute_pdh_pdl, compute_pwh_pwl, compute_asian_range,
    detect_equal_levels, get_nearest_liquidity,
    LiquiditySnapshot,
)


def make_candle(symbol, interval, high, low, close, ts):
    return Candle.objects.create(
        symbol=symbol, interval=interval, timestamp=ts,
        open=Decimal(str(close * 0.999)),
        high=Decimal(str(high)), low=Decimal(str(low)),
        close=Decimal(str(close)), volume=Decimal('1000'),
        is_closed=True,
    )


class PDHPDLTest(TestCase):
    def setUp(self):
        now = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)  # Saturday 12:00
        # Yesterday (Friday): high=100, low=90
        for h in range(24):
            make_candle('BTCUSDT', '1h', 100, 90, 95,
                        datetime(2026, 1, 2, h, 0, tzinfo=timezone.utc))
        # Today (partial): high=95, low=92
        for h in range(12):
            make_candle('BTCUSDT', '1h', 95, 92, 93,
                        datetime(2026, 1, 3, h, 0, tzinfo=timezone.utc))

    def test_pdh_is_yesterday_high(self):
        now = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        pdh, pdl = compute_pdh_pdl('BTCUSDT', now)
        self.assertAlmostEqual(pdh, 100.0, places=1)

    def test_pdl_is_yesterday_low(self):
        now = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        pdh, pdl = compute_pdh_pdl('BTCUSDT', now)
        self.assertAlmostEqual(pdl, 90.0, places=1)

    def test_returns_none_when_no_data(self):
        pdh, pdl = compute_pdh_pdl('XYZUSDT', datetime.now(timezone.utc))
        self.assertIsNone(pdh)
        self.assertIsNone(pdl)


class AsianRangeTest(TestCase):
    def test_asian_range_from_22_to_00_utc(self):
        # Asian session: 22:00-00:00 UTC previous day
        # Create 2 candles in asian session window
        make_candle('BTCUSDT', '1h', 103, 97, 100,
                    datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc))
        make_candle('BTCUSDT', '1h', 101, 96, 99,
                    datetime(2026, 1, 2, 23, 0, tzinfo=timezone.utc))

        now = datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc)
        hi, lo = compute_asian_range('BTCUSDT', now)
        self.assertAlmostEqual(hi, 103.0, places=1)
        self.assertAlmostEqual(lo, 96.0, places=1)

    def test_returns_none_when_no_asian_data(self):
        hi, lo = compute_asian_range('XYZUSDT', datetime.now(timezone.utc))
        self.assertIsNone(hi)
        self.assertIsNone(lo)


class EqualLevelsTest(TestCase):
    def test_detects_equal_highs(self):
        # Three touches of ~100 within 0.2%
        prices = [100.0, 99.8, 100.1, 98.5, 100.05, 97.0, 100.2]
        highs = detect_equal_levels(prices, tolerance_pct=0.3)
        self.assertGreater(len(highs), 0)
        # The level should be near 100
        self.assertTrue(any(99.5 < l < 100.5 for l in highs))

    def test_no_equal_levels_in_trending_data(self):
        prices = [100, 102, 104, 106, 108, 110, 112]
        levels = detect_equal_levels(prices, tolerance_pct=0.3)
        self.assertEqual(len(levels), 0)


class NearestLiquidityTest(TestCase):
    def test_nearest_above_for_long(self):
        levels = [90.0, 95.0, 100.0, 105.0, 110.0]
        current = 96.0
        nearest = get_nearest_liquidity(current, levels, direction='LONG')
        self.assertAlmostEqual(nearest, 100.0)  # nearest ABOVE for TP

    def test_nearest_below_for_short(self):
        levels = [90.0, 95.0, 100.0, 105.0, 110.0]
        current = 104.0
        nearest = get_nearest_liquidity(current, levels, direction='SHORT')
        self.assertAlmostEqual(nearest, 100.0)  # nearest BELOW for TP

    def test_returns_none_when_no_levels(self):
        result = get_nearest_liquidity(100.0, [], direction='LONG')
        self.assertIsNone(result)


class LiquiditySnapshotTest(TestCase):
    def test_snapshot_builds_all_levels(self):
        # Create minimal candle data
        for h in range(24):
            make_candle('BTCUSDT', '1h', 100 + h * 0.1, 90 + h * 0.1, 95,
                        datetime(2026, 1, 2, h, 0, tzinfo=timezone.utc))
        now = datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc)
        snap = LiquiditySnapshot.build('BTCUSDT', now)
        self.assertIsInstance(snap.all_levels(), list)
        # Has at least PDH/PDL
        self.assertGreater(len(snap.all_levels()), 0)
