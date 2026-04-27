"""Tests for proper FVG: displacement candle + mitigation tracking."""
from django.test import TestCase
from l1_filter.fvg import find_fvgs_with_displacement, FVGZone, is_fvg_mitigated, get_active_fvgs


def make_candle(o, h, l, c, v=1000):
    return {'open': float(o), 'high': float(h), 'low': float(l),
            'close': float(c), 'volume': float(v)}


class FVGDisplacementTest(TestCase):

    def test_gap_without_displacement_rejected(self):
        """Small gap candle without strong body → NOT a real FVG."""
        # Gap exists (c[0].high < c[2].low) but no displacement (tiny body)
        candles = [
            make_candle(100, 102, 98, 101),   # normal candle
            make_candle(102, 103, 101, 102, 500),  # tiny body — no displacement
            make_candle(103, 105, 103, 104),  # gap above c[0].high
        ]
        atr = 5.0  # large ATR → candle body 1.0 << 1.5 × ATR
        fvgs = find_fvgs_with_displacement(candles, atr)
        self.assertEqual(len(fvgs), 0)

    def test_gap_with_displacement_accepted(self):
        """Strong displacement candle with gap → real FVG."""
        candles = [
            make_candle(100, 102, 98,  101),
            make_candle(101, 115, 100, 114, 3000),  # big body 13 >> 1.5 × ATR(5)
            make_candle(115, 118, 115, 117),         # gap above c[0].high=102
        ]
        atr = 5.0
        fvgs = find_fvgs_with_displacement(candles, atr)
        self.assertEqual(len(fvgs), 1)
        self.assertEqual(fvgs[0].direction, 'bullish')
        self.assertAlmostEqual(fvgs[0].top,    115.0)
        self.assertAlmostEqual(fvgs[0].bottom, 102.0)

    def test_volume_spike_required(self):
        """Displacement candle must have volume spike > 1.2× avg."""
        avg_volume = 1000.0
        candles = [
            make_candle(100, 102, 98, 101, 1000),
            make_candle(101, 115, 100, 114, 800),   # below-avg volume
            make_candle(115, 118, 115, 117, 900),
        ]
        atr = 3.0
        # body=13, 1.5×ATR=4.5 → displacement OK by body size but volume too low
        fvgs = find_fvgs_with_displacement(candles, atr, avg_volume=avg_volume, vol_multiplier=1.5)
        self.assertEqual(len(fvgs), 0)

    def test_bearish_fvg_detected(self):
        """Bearish FVG: c[0].low > c[2].high."""
        candles = [
            make_candle(120, 122, 115, 116),
            make_candle(116, 117, 103, 104, 3000),  # big bearish body
            make_candle(103, 103, 98,  100),
        ]
        atr = 4.0
        fvgs = find_fvgs_with_displacement(candles, atr)
        bearish = [f for f in fvgs if f.direction == 'bearish']
        self.assertGreater(len(bearish), 0)

    def test_fvg_mitigation_tracking(self):
        """
        Bullish FVG (bottom=100, top=110, mid=105):
        Mitigated when price returns DOWN to mid or below.
        low=106 → only 40% of gap filled from top (60% still open) → NOT mitigated
        low=105 → exactly at mid (50%) → mitigated
        low=104 → past mid → also mitigated
        """
        fvg = FVGZone(bottom=100.0, top=110.0, direction='bullish')
        self.assertFalse(fvg.mitigated)

        # Price only dips to 106 (fills 40% from top) → NOT mitigated
        self.assertFalse(is_fvg_mitigated(fvg, low=106.0))

        # Price reaches exactly mid=105 → mitigated
        self.assertTrue(is_fvg_mitigated(fvg, low=105.0))

        # Price goes deeper to 104 → also mitigated (past mid)
        self.assertTrue(is_fvg_mitigated(fvg, low=104.0))

    def test_fvg_mid_entry_point(self):
        """Mid-FVG (50%) is the OTE entry — better than 25%."""
        fvg = FVGZone(bottom=100.0, top=110.0, direction='bullish')
        self.assertAlmostEqual(fvg.mid, 105.0)
        self.assertAlmostEqual(fvg.ote_entry, 105.0)  # 50% = mid

    def test_active_fvg_marks_partial_fill(self):
        candles = [
            make_candle(100, 102, 98, 101, 1000),
            make_candle(101, 115, 100, 114, 3000),
            make_candle(115, 118, 115, 117, 1000),
            make_candle(117, 118, 112, 116, 1000),  # shallow return into gap
        ]
        active = get_active_fvgs(candles, atr=5.0, direction='bullish')
        self.assertEqual(len(active), 1)
        self.assertIn(active[0].status, {'fresh', 'partial'})
        self.assertLess(active[0].fill_ratio, 0.5)

    def test_active_fvg_drops_stale_gap(self):
        candles = [
            make_candle(100, 102, 98, 101, 1000),
            make_candle(101, 115, 100, 114, 3000),
            make_candle(115, 118, 115, 117, 1000),
            make_candle(117, 118, 104, 106, 1000),  # deep mitigation beyond 50%
        ]
        active = get_active_fvgs(candles, atr=5.0, direction='bullish')
        self.assertEqual(len(active), 0)
