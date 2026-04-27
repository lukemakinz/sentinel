from datetime import datetime, timezone
from django.test import TestCase

from l1_filter.gates_a import check_killzone, check_htf_trend, check_btc_correlation, check_funding_rate, check_adx
from l1_filter.tests.helpers import uptrend, downtrend, ranging


class KillzoneTest(TestCase):
    def test_london_open_fails(self):
        passed, data = check_killzone(datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc))
        self.assertFalse(passed)
        self.assertIsNone(data['session'])

    def test_ny_open_passes(self):
        passed, data = check_killzone(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertTrue(passed)
        self.assertEqual(data['session'], 'ny')

    def test_dead_zone_fails(self):
        passed, _ = check_killzone(datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc))
        self.assertFalse(passed)

    def test_london_boundary_start_fails(self):
        passed, _ = check_killzone(datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc))
        self.assertFalse(passed)

    def test_london_boundary_end_fails(self):
        passed, _ = check_killzone(datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc))
        self.assertFalse(passed)

    def test_ny_boundary_end_fails(self):
        passed, _ = check_killzone(datetime(2026, 1, 1, 16, 0, tzinfo=timezone.utc))
        self.assertFalse(passed)


class HTFTrendTest(TestCase):
    def test_uptrend_returns_long(self):
        passed, data = check_htf_trend(uptrend(250))
        self.assertTrue(passed)
        self.assertEqual(data['direction'], 'LONG')

    def test_downtrend_returns_short(self):
        passed, data = check_htf_trend(downtrend(250))
        self.assertTrue(passed)
        self.assertEqual(data['direction'], 'SHORT')

    def test_flat_fails(self):
        passed, _ = check_htf_trend(ranging(250))
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_htf_trend(uptrend(30))
        self.assertFalse(passed)

    def test_returns_direction_and_basis(self):
        _, data = check_htf_trend(uptrend(250))
        self.assertIn('direction', data)
        self.assertIn('basis', data)   # 'structure_HH_HL' or 'ema_fallback'


class BTCCorrelationTest(TestCase):
    def test_btc_itself_always_passes(self):
        passed, _ = check_btc_correlation(downtrend(50), 'LONG', 'BTCUSDT')
        self.assertTrue(passed)

    def test_btc_bullish_aligned_with_long(self):
        passed, _ = check_btc_correlation(uptrend(50), 'LONG', 'ETHUSDT')
        self.assertTrue(passed)

    def test_btc_bearish_opposing_long_fails(self):
        passed, _ = check_btc_correlation(downtrend(50), 'LONG', 'ETHUSDT')
        self.assertFalse(passed)

    def test_btc_bearish_aligned_with_short(self):
        passed, _ = check_btc_correlation(downtrend(50), 'SHORT', 'ETHUSDT')
        self.assertTrue(passed)

    def test_btc_bullish_opposing_short_fails(self):
        passed, _ = check_btc_correlation(uptrend(50), 'SHORT', 'ETHUSDT')
        self.assertFalse(passed)


class FundingRateTest(TestCase):
    def test_normal_funding_passes(self):
        passed, _ = check_funding_rate(0.0001, 'LONG')
        self.assertTrue(passed)

    def test_extreme_positive_fails(self):
        passed, _ = check_funding_rate(0.0015, 'LONG')
        self.assertFalse(passed)

    def test_extreme_negative_fails(self):
        passed, _ = check_funding_rate(-0.0015, 'LONG')
        self.assertFalse(passed)

    def test_zero_funding_passes(self):
        passed, _ = check_funding_rate(0.0, 'SHORT')
        self.assertTrue(passed)

    def test_returns_funding_value(self):
        _, data = check_funding_rate(0.0003, 'LONG')
        self.assertAlmostEqual(data['funding_rate'], 0.0003)


class ADXTest(TestCase):
    def test_strong_trend_passes(self):
        passed, data = check_adx(uptrend(60))
        self.assertTrue(passed)
        self.assertGreater(data['adx_value'], 20)

    def test_ranging_fails(self):
        passed, _ = check_adx(ranging(60))
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_adx(uptrend(10))
        self.assertFalse(passed)

    def test_returns_adx_value(self):
        _, data = check_adx(uptrend(60))
        self.assertIn('adx_value', data)
