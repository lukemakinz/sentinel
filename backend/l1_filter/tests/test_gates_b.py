from django.test import TestCase

from l1_filter.gates_b import (
    check_liquidity_sweep, check_fvg_ob,
    check_premium_discount, check_atr_squeeze,
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
    """FVG with proper displacement: body > 1.5×ATR + volume spike + gap."""
    # 17 stable pre-candles for ATR baseline (~10 range each)
    pre_closes = [1000 + i * 0.5 for i in range(17)]
    pre_highs  = [c + 5 for c in pre_closes]
    pre_lows   = [c - 5 for c in pre_closes]
    pre_vols   = [800.0] * 17

    # 3-candle FVG setup: gap between c0.high=1010 and c2.low=1012
    fvg_closes = [1009, 1040, 1043]
    fvg_highs  = [1010, 1042, 1045]
    fvg_lows   = [1005, 1007, 1012]   # c2.low=1012 > c0.high=1010 → bullish FVG!
    fvg_opens  = [1008, 1009, 1041]   # c1 body=1040-1009=31 >> 1.5×ATR(10)=15
    fvg_vols   = [800.0, 5000.0, 900.0]  # vol spike on displacement

    # Pre opens: close - tiny offset
    pre_opens = [c - 0.1 for c in pre_closes]
    fvg_opens = [1008.0, 1009.0, 1041.0]  # c1 body = 1040-1009 = 31

    all_closes = pre_closes + fvg_closes
    all_highs  = pre_highs  + fvg_highs
    all_lows   = pre_lows   + fvg_lows
    all_vols   = pre_vols   + fvg_vols
    all_opens  = pre_opens  + fvg_opens
    return make_candles(all_closes, highs=all_highs, lows=all_lows,
                        volumes=all_vols, opens=all_opens)


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


# ClassicalPatternTest removed — B4 gate deleted from pipeline


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
