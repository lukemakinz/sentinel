"""Tests for the improved order-block detector (detect_order_blocks_v2) and
its S1CF_OB gate (check_fvg_ob_v2): ATR-normalized displacement, structure
break requirement, volume filter, and mitigation tracking.
"""
from django.test import TestCase

from analysts.structure import detect_order_blocks_v2
from l1_filter.gates_b import check_fvg_ob_v2
from l1_filter.tests.helpers import make_candles


def _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0, break_structure=True,
                       mitigate=False):
    """
    30 flat baseline candles (high=1005/low=995, volume=1000) with one
    isolated swing high of 1030 at index 8, then a bearish OB candle at
    index 20 (close 990), followed by 3 displacement candles closing up to
    990 + disp_move, then a flat tail. `break_structure=False` keeps the
    displacement below the 1030 swing high. `mitigate=True` appends candles
    that trade back down through the block after it forms.
    """
    n_head = 20
    closes = [1000.0] * n_head
    highs  = [1005.0] * n_head
    lows   = [995.0] * n_head
    volumes = [1000.0] * n_head
    highs[8] = 1030.0  # isolated swing high

    # OB candle (bearish): open 1000, close 990
    ob_open, ob_close = 1000.0, 990.0
    closes.append(ob_close)
    highs.append(1005.0)
    lows.append(985.0)
    volumes.append(1000.0)
    opens = [c * 0.999 for c in closes[:-1]] + [ob_open]

    target = ob_close + disp_move if break_structure else ob_close + 5.0
    disp_closes = [ob_close + (target - ob_close) * f for f in (0.4, 0.7, 1.0)]
    for c in disp_closes:
        closes.append(c)
        highs.append(c + 5)
        lows.append(c - 5)
        volumes.append(disp_volume)
        opens.append(c - 2)

    if mitigate:
        # Trade back down through the whole OB zone (below ob_close).
        for c in (target - 10, ob_close - 20, ob_close - 40):
            closes.append(c)
            highs.append(c + 5)
            lows.append(c - 5)
            volumes.append(1000.0)
            opens.append(c + 2)
    else:
        for c in (target, target, target):
            closes.append(c)
            highs.append(c + 5)
            lows.append(c - 5)
            volumes.append(1000.0)
            opens.append(c - 2)

    candles = make_candles(closes, highs=highs, lows=lows, volumes=volumes, opens=opens)
    return candles


class DetectOrderBlocksV2Tests(TestCase):
    def _arrays(self, candles):
        opens  = [c['open']  for c in candles]
        closes = [c['close'] for c in candles]
        highs  = [c['high']  for c in candles]
        lows   = [c['low']   for c in candles]
        vols   = [c['volume'] for c in candles]
        return opens, closes, highs, lows, vols

    def test_detects_bullish_ob_on_structure_break_with_volume(self):
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0)
        opens, closes, highs, lows, vols = self._arrays(candles)
        blocks = detect_order_blocks_v2(opens, closes, highs, lows, vols, atr=10.0)
        bullish = [b for b in blocks if b['type'] == 'bullish_ob']
        self.assertTrue(bullish, 'expected a qualifying bullish OB')
        self.assertEqual(bullish[0]['status'], 'fresh')

    def test_rejects_when_volume_too_low(self):
        candles = _bullish_ob_setup(disp_volume=1000.0, disp_move=70.0)  # no volume spike
        opens, closes, highs, lows, vols = self._arrays(candles)
        blocks = detect_order_blocks_v2(opens, closes, highs, lows, vols, atr=10.0)
        self.assertFalse([b for b in blocks if b['type'] == 'bullish_ob'],
                          'weak-volume displacement should not qualify as an OB')

    def test_rejects_when_displacement_below_atr_threshold(self):
        # move of 5 with atr=10 and mult=1.5 needs >=15 -> should not qualify
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=5.0)
        opens, closes, highs, lows, vols = self._arrays(candles)
        blocks = detect_order_blocks_v2(opens, closes, highs, lows, vols, atr=10.0)
        self.assertFalse([b for b in blocks if b['type'] == 'bullish_ob'],
                          'sub-ATR displacement should not qualify as an OB')

    def test_rejects_when_structure_not_broken(self):
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0, break_structure=False)
        opens, closes, highs, lows, vols = self._arrays(candles)
        blocks = detect_order_blocks_v2(opens, closes, highs, lows, vols, atr=10.0)
        self.assertFalse([b for b in blocks if b['type'] == 'bullish_ob'],
                          'displacement that stays below the prior swing high should not qualify')

    def test_marks_block_mitigated_once_price_returns_through_it(self):
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0, mitigate=True)
        opens, closes, highs, lows, vols = self._arrays(candles)
        blocks = detect_order_blocks_v2(opens, closes, highs, lows, vols, atr=10.0)
        bullish = [b for b in blocks if b['type'] == 'bullish_ob']
        self.assertTrue(bullish)
        self.assertEqual(bullish[0]['status'], 'mitigated')


class CheckFvgObV2Tests(TestCase):
    def test_parallel_mode_ignores_mitigated_order_block(self):
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0, mitigate=True)
        passed, data = check_fvg_ob_v2(candles, 'LONG', ob_mode='parallel')
        if passed:
            self.assertNotEqual(data.get('fvg_type'), 'order_block_v2')

    def test_fallback_mode_uses_fresh_order_block_when_no_fvg(self):
        candles = _bullish_ob_setup(disp_volume=2000.0, disp_move=70.0)
        passed, data = check_fvg_ob_v2(candles, 'LONG', ob_mode='fallback')
        self.assertTrue(passed)
        self.assertEqual(data['fvg_type'], 'order_block_v2')
        self.assertEqual(data['fvg_status'], 'fresh')
        self.assertIn('entry_ote', data)
