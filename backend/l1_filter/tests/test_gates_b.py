from django.test import TestCase

from l1_filter.gates_b import (
    check_liquidity_sweep, check_fvg_ob,
    check_premium_discount, check_classical_pattern, check_atr_squeeze,
)
from l1_filter.tests.helpers import make_candles, uptrend, downtrend


def sweep_candles_long():
    """Price sweeps below swing low then recovers — bullish sweep."""
    closes = [1000] * 15 + [985, 980, 975] + [1005, 1010, 1015]  # dip below then recovery
    lows   = [995]  * 15 + [980, 975, 970] + [990, 1000, 1010]
    highs  = [1005] * 15 + [990, 985, 980] + [1010, 1015, 1020]
    return make_candles(closes, highs=highs, lows=lows)


def sweep_candles_short():
    """Price sweeps above swing high then drops — bearish sweep."""
    closes = [1000] * 15 + [1015, 1020, 1025] + [995, 990, 985]
    highs  = [1005] * 15 + [1020, 1025, 1030] + [1010, 1000, 990]
    lows   = [995]  * 15 + [1010, 1015, 1020] + [985, 980, 975]
    return make_candles(closes, highs=highs, lows=lows)


def fvg_long_candles():
    """Three candles creating a bullish FVG: candle[0].high < candle[2].low."""
    # candle[i-2].high < candle[i].low  → bullish FVG
    highs  = [1000, 1005, 1015, 1020, 1025]
    lows   = [990,  995,  1008, 1012, 1016]
    closes = [995,  1000, 1014, 1018, 1022]
    return make_candles(closes, highs=highs, lows=lows)


class LiquiditySweepTest(TestCase):
    def test_sweep_below_swing_low_for_long(self):
        passed, data = check_liquidity_sweep(sweep_candles_long(), 'LONG')
        self.assertTrue(passed)
        self.assertIsNotNone(data.get('swept_level'))

    def test_sweep_above_swing_high_for_short(self):
        passed, data = check_liquidity_sweep(sweep_candles_short(), 'SHORT')
        self.assertTrue(passed)

    def test_no_sweep_fails(self):
        # Monotonic uptrend — no sweep
        passed, _ = check_liquidity_sweep(uptrend(30), 'LONG')
        self.assertFalse(passed)

    def test_insufficient_candles_fails(self):
        passed, _ = check_liquidity_sweep(uptrend(5), 'LONG')
        self.assertFalse(passed)


class FVGOBTest(TestCase):
    def test_bullish_fvg_passes_for_long(self):
        passed, data = check_fvg_ob(fvg_long_candles(), 'LONG')
        self.assertTrue(passed)
        self.assertIsNotNone(data.get('fvg_zone'))

    def test_wrong_direction_fails(self):
        passed, _ = check_fvg_ob(fvg_long_candles(), 'SHORT')
        self.assertFalse(passed)

    def test_no_fvg_fails(self):
        # Wide-range candles always overlap neighbours — impossible to create a price gap
        closes = [1000 + i * 5 for i in range(30)]
        highs  = [c + 50 for c in closes]   # span >> step → no FVG
        lows   = [c - 50 for c in closes]
        passed, _ = check_fvg_ob(make_candles(closes, highs=highs, lows=lows), 'LONG')
        self.assertFalse(passed)


class PremiumDiscountTest(TestCase):
    def test_discount_zone_for_long(self):
        # Price at bottom of range → discount zone
        closes = [1000] * 40 + [800, 810, 820]  # drops to discount
        passed, data = check_premium_discount(make_candles(closes), 'LONG')
        self.assertTrue(passed)

    def test_premium_zone_for_short(self):
        # Price at top of range → premium zone
        closes = [1000] * 40 + [1200, 1210, 1220]  # rises to premium
        passed, _ = check_premium_discount(make_candles(closes), 'SHORT')
        self.assertTrue(passed)

    def test_midpoint_fails_for_long(self):
        # Price exactly at midpoint → neither premium nor discount
        closes = [800] * 25 + [1200] * 25  # last close at midpoint boundary
        passed, _ = check_premium_discount(make_candles(closes), 'LONG')
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_premium_discount(uptrend(5), 'LONG')
        self.assertFalse(passed)


class ClassicalPatternTest(TestCase):
    def test_double_bottom_for_long(self):
        # Two similar lows followed by recovery
        closes = [1000, 950, 1000, 960, 1000, 1020, 1040]
        lows   = [995,  940, 995,  950, 995,  1010, 1030]
        passed, _ = check_classical_pattern(make_candles(closes, lows=lows), 'LONG')
        self.assertTrue(passed)

    def test_double_top_for_short(self):
        closes = [1000, 1050, 1000, 1040, 1000, 980, 960]
        highs  = [1005, 1060, 1005, 1050, 1005, 990, 970]
        passed, _ = check_classical_pattern(make_candles(closes, highs=highs), 'SHORT')
        self.assertTrue(passed)

    def test_no_pattern_fails(self):
        # Smooth monotonic uptrend — no double top/bottom
        passed, _ = check_classical_pattern(uptrend(30), 'LONG')
        self.assertFalse(passed)


class ATRSqueezeTest(TestCase):
    def test_squeeze_passes(self):
        # Candles with shrinking ATR (high-low range decreasing)
        n = 30
        closes = [1000.0] * n
        # First 20: high range, last 10: tight range (squeeze)
        highs  = [1010.0] * 20 + [1001.0] * 10
        lows   = [990.0]  * 20 + [999.0]  * 10
        passed, _ = check_atr_squeeze(make_candles(closes, highs=highs, lows=lows))
        self.assertTrue(passed)

    def test_no_squeeze_fails(self):
        # Consistent ATR — no squeeze
        passed, _ = check_atr_squeeze(uptrend(40))
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_atr_squeeze(uptrend(5))
        self.assertFalse(passed)
