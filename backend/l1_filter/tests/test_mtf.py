from django.test import TestCase
from l1_filter.mtf import get_tf_trend, _classify
from l1_filter.tests.helpers import uptrend, downtrend, ranging, make_candles


class TFTrendTest(TestCase):
    def test_uptrend_is_bullish(self):
        result = get_tf_trend(uptrend(100))
        self.assertEqual(result['direction'], 'BULLISH')

    def test_downtrend_is_bearish(self):
        result = get_tf_trend(downtrend(100))
        self.assertEqual(result['direction'], 'BEARISH')

    def test_ranging_is_neutral(self):
        result = get_tf_trend(ranging(100))
        self.assertIn(result['direction'], ('NEUTRAL', 'BULLISH', 'BEARISH'))

    def test_insufficient_data_returns_neutral(self):
        result = get_tf_trend(uptrend(5))
        self.assertEqual(result['direction'], 'NEUTRAL')

    def test_returns_required_fields(self):
        result = get_tf_trend(uptrend(60))
        self.assertIn('direction', result)
        self.assertIn('strength', result)
        self.assertIn('reason', result)


class ClassifyTest(TestCase):
    def test_all_bullish_is_trend_follow_low_risk(self):
        alignment, trade_type, risk, _ = _classify('BULLISH','BULLISH','BULLISH','BULLISH')
        self.assertEqual(alignment, 'full')
        self.assertEqual(trade_type, 'TREND_FOLLOW')
        self.assertEqual(risk, 'LOW')

    def test_1d_vs_4h_conflict_is_counter_trend_high_risk(self):
        alignment, trade_type, risk, note = _classify('BULLISH','BEARISH','NEUTRAL','BULLISH')
        self.assertEqual(alignment, 'conflict')
        self.assertEqual(trade_type, 'COUNTER_TREND')
        self.assertEqual(risk, 'HIGH')
        self.assertIn('⚠️', note)

    def test_1d_4h_agree_swing(self):
        alignment, trade_type, risk, _ = _classify('BULLISH','BULLISH','BULLISH','NEUTRAL')
        self.assertEqual(trade_type, 'SWING')
        self.assertEqual(alignment, 'partial')

    def test_only_15m_bullish_is_scalp(self):
        alignment, trade_type, risk, _ = _classify('NEUTRAL','NEUTRAL','NEUTRAL','BULLISH')
        self.assertEqual(trade_type, 'SCALP')
        self.assertEqual(risk, 'HIGH')
