from django.test import TestCase
from unittest.mock import patch
import numpy as np

from l1_filter.gates_c import (
    check_choch, check_momentum_divergence,
    check_ema_crossover, check_volume_spike, check_vwap, check_obv_confirmation, check_price_action_trigger,
)
from l1_filter.tests.helpers import make_candles, uptrend, downtrend, trending_with_spike_volume


def choch_long_candles():
    """Structure: lower lows then a higher low (CHoCH bullish)."""
    # Swing lows: 950, 940, 930 then 935 (higher low = CHoCH)
    closes = [1000, 970, 1010, 950, 1010, 940, 1010, 935, 1050, 1060]
    highs  = [1010, 980, 1020, 960, 1020, 950, 1020, 945, 1060, 1070]
    lows   = [990,  960, 1000, 945, 1000, 935, 1000, 930, 1040, 1050]
    return make_candles(closes, highs=highs, lows=lows)


def choch_short_candles():
    """Structure: higher highs then a lower high (CHoCH bearish)."""
    closes = [1000, 1030, 990, 1050, 990, 1060, 990, 1055, 950, 940]
    highs  = [1010, 1040, 1000, 1060, 1000, 1070, 1000, 1065, 960, 950]
    lows   = [990,  1020, 980,  1040, 980,  1050, 980,  1045, 940, 930]
    return make_candles(closes, highs=highs, lows=lows)


def bullish_divergence_candles():
    """Price makes lower low; RSI makes higher low — bullish divergence.

    Structure needed for detect_divergence(lookback=20):
    - First 10 of last-20 window: sharp drop (RSI hits floor ~5)
    - Last 10 of last-20 window: choppy slow decline to new price low (RSI ~20-30)
    RSI higher on second dip despite price being lower = bullish divergence.
    """
    preamble   = [1000.0] * 10                              # flat baseline → RSI ~50-100
    pre_drop   = [1000 - i * 5  for i in range(10)]        # gentle decline, RSI ~40
    sharp_drop = [950  - i * 12 for i in range(10)]        # sharp: 950→842, RSI → ~5
    # Choppy decline to new price low (842): mixed up/down → keeps RSI above first dip
    slow_drop  = [838, 835, 838, 832, 836, 829, 833, 826, 830, 820]
    return make_candles(preamble + pre_drop + sharp_drop + slow_drop)


def ema_crossover_long():
    """EMA9 crosses above EMA21: first ranging, then strong surge."""
    # Start with a flat/declining period, then strong uptrend forces EMA9 > EMA21
    flat_part = [1000.0] * 15
    surge_part = [1000 + i * 15 for i in range(15)]
    closes = flat_part + surge_part
    return make_candles(closes)


def ema_crossover_short():
    """EMA9 crosses below EMA21: surge up then strong drop."""
    surge_part = [1000 + i * 15 for i in range(15)]
    drop_part  = [1210 - i * 15 for i in range(15)]
    closes = surge_part + drop_part
    return make_candles(closes)


class ChoCHTest(TestCase):
    def test_bullish_choch_passes_for_long(self):
        passed, data = check_choch(choch_long_candles(), 'LONG')
        self.assertTrue(passed)

    def test_bearish_choch_passes_for_short(self):
        passed, data = check_choch(choch_short_candles(), 'SHORT')
        self.assertTrue(passed)

    def test_no_choch_fails(self):
        passed, _ = check_choch(uptrend(20), 'SHORT')
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_choch(uptrend(3), 'LONG')
        self.assertFalse(passed)


class MomentumDivergenceTest(TestCase):
    def test_bullish_divergence_passes_for_long(self):
        passed, _ = check_momentum_divergence(bullish_divergence_candles(), 'LONG')
        self.assertTrue(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_momentum_divergence(uptrend(10), 'LONG')
        self.assertFalse(passed)

    def test_hidden_bullish_divergence_passes_for_long(self):
        closes = [1000 - i * 5 for i in range(25)]
        candles = make_candles(closes)
        mocked_rsi = np.array([60, 58, 56, 54, 52, 50, 48, 46, 44, 42, 40])
        with patch('l1_filter.gates_c.compute_rsi', return_value=mocked_rsi), \
             patch('l1_filter.gates_c.detect_divergence', return_value=None), \
             patch('l1_filter.gates_c.detect_divergence_extended', return_value='bullish_hidden'):
            passed, data = check_momentum_divergence(candles, 'LONG')
        self.assertTrue(passed)
        self.assertIn('bullish_hidden', data['divergence'])


class DeltaCandleTest(TestCase):
    """C3 gate now uses Delta Candle (taker buy/sell pressure) instead of EMA crossover."""

    def _candles_with_buy_pressure(self, n=25):
        from l1_filter.tests.helpers import make_candles
        closes  = [1000 + i * 5 for i in range(n)]
        volumes = [1000.0] * n
        # taker_buy_volume > 50% → net buy delta positive
        buy_vols = [800.0] * n   # strong buyers
        candles = make_candles(closes, volumes=volumes)
        for i, c in enumerate(candles):
            c['taker_buy_volume'] = buy_vols[i]
        return candles

    def _candles_with_sell_pressure(self, n=25):
        from l1_filter.tests.helpers import make_candles
        closes  = [2000 - i * 5 for i in range(n)]
        volumes = [1000.0] * n
        candles = make_candles(closes, volumes=volumes)
        for i, c in enumerate(candles):
            c['taker_buy_volume'] = 200.0  # sellers dominate
        return candles

    def test_buy_pressure_passes_for_long(self):
        passed, data = check_ema_crossover(self._candles_with_buy_pressure(), 'LONG')
        self.assertTrue(passed)
        self.assertIn('net_delta', data)

    def test_sell_pressure_passes_for_short(self):
        passed, _ = check_ema_crossover(self._candles_with_sell_pressure(), 'SHORT')
        self.assertTrue(passed)

    def test_buy_pressure_fails_for_short(self):
        passed, _ = check_ema_crossover(self._candles_with_buy_pressure(), 'SHORT')
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_ema_crossover(uptrend(3), 'LONG')
        self.assertFalse(passed)


class VolumeSpikeTest(TestCase):
    def test_volume_spike_passes(self):
        passed, data = check_volume_spike(trending_with_spike_volume(30))
        self.assertTrue(passed)
        self.assertGreater(data['volume_ratio'], 1.5)

    def test_no_spike_fails(self):
        passed, _ = check_volume_spike(uptrend(30))
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_volume_spike(uptrend(5))
        self.assertFalse(passed)


class VWAPTest(TestCase):
    def test_price_above_vwap_passes_for_long(self):
        # Uptrend: last close above VWAP
        passed, data = check_vwap(uptrend(50), 'LONG')
        self.assertTrue(passed)
        self.assertIsNotNone(data.get('vwap'))

    def test_price_below_vwap_passes_for_short(self):
        passed, _ = check_vwap(downtrend(50), 'SHORT')
        self.assertTrue(passed)

    def test_price_below_vwap_fails_for_long(self):
        passed, _ = check_vwap(downtrend(50), 'LONG')
        self.assertFalse(passed)

    def test_insufficient_data_fails(self):
        passed, _ = check_vwap(uptrend(5), 'LONG')
        self.assertFalse(passed)


class OBVConfirmationTest(TestCase):
    def test_obv_confirms_long_trend(self):
        candles = trending_with_spike_volume(25)
        passed, data = check_obv_confirmation(candles, 'LONG')
        self.assertTrue(passed)
        self.assertEqual(data['signal'], 'bullish_obv')

    def test_obv_confirms_short_trend(self):
        candles = downtrend(25)
        for i, c in enumerate(candles):
            c['volume'] = 1000 + i * 50
        passed, data = check_obv_confirmation(candles, 'SHORT')
        self.assertTrue(passed)
        self.assertEqual(data['signal'], 'bearish_obv')

    def test_obv_fails_when_insufficient_data(self):
        passed, _ = check_obv_confirmation(uptrend(5), 'LONG')
        self.assertFalse(passed)


class PriceActionTriggerTest(TestCase):
    def test_bullish_displacement_close_passes(self):
        candles = make_candles(
            [100, 101, 110],
            opens=[99.5, 100.5, 102],
            highs=[100.5, 101.5, 111],
            lows=[99, 100, 101.5],
        )
        passed, data = check_price_action_trigger(candles, 'LONG')
        self.assertTrue(passed)
        self.assertEqual(data['signal'], 'bullish_displacement')

    def test_bearish_displacement_close_passes(self):
        candles = make_candles(
            [110, 109, 100],
            opens=[110.5, 109.5, 108],
            highs=[111, 110, 108.5],
            lows=[109.5, 108.5, 99],
        )
        passed, data = check_price_action_trigger(candles, 'SHORT')
        self.assertTrue(passed)
        self.assertEqual(data['signal'], 'bearish_displacement')
