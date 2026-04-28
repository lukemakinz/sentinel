from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from l1_filter.scanner import L1Scanner
from l1_filter.models import L1Result


MOCK_LONG = (True, {'direction': 'LONG', 'ema50': 1500, 'ema200': 1200})
MOCK_PASS = (True, {})
MOCK_FAIL = (False, {})
MOCK_KILLZONE = (True, {'session': 'ny'})
MOCK_BTC      = (True, {'btc_trend': 'bullish'})
MOCK_FUNDING  = (True, {'funding_rate': 0.0001})
MOCK_ADX      = (True, {'adx_value': 28.5, 'atr': 50.0})
MOCK_CVD      = (True, {'fvg_zone': (1490, 1510)})
MOCK_SWEEP    = (True, {'swept_level': 1480.0, 'nearest_liquidity': 1480.0, 'htf_poi_confluence': True})
MOCK_PREMIUM  = (True, {'in_ote': True})
MOCK_PATTERN  = (True, {})
MOCK_SQUEEZE  = (True, {})
MOCK_CHOCH    = (True, {'type': 'CHoCH'})
MOCK_DIVERG   = (True, {})
MOCK_EMA_X    = (True, {})
MOCK_VOLSPIKE = (True, {'volume_ratio': 2.1})
MOCK_VWAP     = (True, {'vwap': 1495.0})
MOCK_OBV      = (True, {'signal': 'bullish_obv'})
MOCK_PA       = (True, {'signal': 'bullish_displacement'})

ALL_PASS_PATCHES = {
    'l1_filter.scanner.check_killzone':          MOCK_KILLZONE,
    'l1_filter.scanner.check_htf_trend':         MOCK_LONG,
    'l1_filter.scanner.check_btc_correlation':   MOCK_BTC,
    'l1_filter.scanner.check_funding_rate':      MOCK_FUNDING,
    'l1_filter.scanner.check_adx':               MOCK_ADX,
    'l1_filter.scanner.check_liquidity_sweep':   MOCK_SWEEP,
    'l1_filter.scanner.check_fvg_ob':            MOCK_CVD,
    'l1_filter.scanner.check_premium_discount':  MOCK_PREMIUM,
    # check_classical_pattern (B4) removed — redundant gate
    'l1_filter.scanner.check_atr_squeeze':       MOCK_SQUEEZE,
    'l1_filter.scanner.check_choch':             MOCK_CHOCH,
    'l1_filter.scanner.check_momentum_divergence': MOCK_DIVERG,
    'l1_filter.scanner.check_ema_crossover':     MOCK_EMA_X,
    'l1_filter.scanner.check_volume_spike':      MOCK_VOLSPIKE,
    'l1_filter.scanner.check_vwap':              MOCK_VWAP,
    'l1_filter.scanner.check_obv_confirmation':  MOCK_OBV,
    'l1_filter.scanner.check_price_action_trigger': MOCK_PA,
}


def apply_patches(test_func):
    """Stack all gate patches onto a test method."""
    for target, val in reversed(list(ALL_PASS_PATCHES.items())):
        test_func = patch(target, return_value=val)(test_func)
    return test_func


@override_settings(TRADING_PAIRS=['BTCUSDT'])
class L1ScannerTest(TestCase):
    def setUp(self):
        self.scanner = L1Scanner()
        self.scanner._get_candles = MagicMock(return_value=[
            {'open': 1000, 'high': 1010, 'low': 990, 'close': 1005, 'volume': 1000}
        ] * 30)
        self.scanner._get_latest_funding_rate = MagicMock(return_value=0.0001)

    @staticmethod
    def _s4_candles(now: datetime) -> list[dict]:
        base = now.replace(hour=12, minute=0, second=0, microsecond=0)
        candles = []
        price = 1000.0
        for idx in range(12):
            ts = base.replace(hour=12 + ((idx * 15) // 60), minute=(idx * 15) % 60)
            open_price = price
            high = price + 8
            low = price - 8
            close = price + 1
            if ts.hour == 13 and ts.minute == 0:
                open_price, high, low, close = 1000.0, 1003.0, 999.0, 1001.0
            if ts.hour == 13 and ts.minute == 15:
                open_price, high, low, close = 1001.0, 1004.0, 1000.0, 1002.0
            if ts.hour == 14 and ts.minute == 0:
                open_price, high, low, close = 1002.0, 1012.0, 1001.0, 1009.0
                volume = 3200.0
            else:
                volume = 1000.0 + idx * 20
            candles.append({
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'timestamp': ts,
            })
            price = close
        return candles

    @staticmethod
    def _s5_15m_candles(now: datetime) -> list[dict]:
        base = now.replace(hour=9, minute=0, second=0, microsecond=0)
        candles = []
        price = 1000.0
        for idx in range(21):
            total_minutes = idx * 15
            ts = base.replace(hour=9 + (total_minutes // 60), minute=total_minutes % 60)
            open_price = price
            close = price + 1
            high = max(open_price, close) + 5
            low = min(open_price, close) - 5
            volume = 1100.0
            candles.append({'open': open_price, 'high': high, 'low': low, 'close': close, 'volume': volume, 'timestamp': ts})
            price = close
        # 3-candle pullback
        for idx in range(3):
            ts = now.replace(hour=14, minute=idx * 15, second=0, microsecond=0)
            open_price = price
            close = price - 3
            high = open_price + 1
            low = close - 2
            candles.append({'open': open_price, 'high': high, 'low': low, 'close': close, 'volume': 1000.0, 'timestamp': ts})
            price = close
        # Rebound candle
        ts = now.replace(second=0, microsecond=0)
        prev_high = candles[-1]['high']
        candles.append({
            'open': price,
            'high': prev_high + 3,
            'low': price - 1,
            'close': prev_high + 1.5,
            'volume': 2800.0,
            'timestamp': ts,
        })
        return candles

    @staticmethod
    def _s5_4h_candles(now: datetime) -> list[dict]:
        candles = []
        price = 800.0
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for idx in range(60):
            ts = base
            open_price = price
            close = price + 8
            candles.append({
                'open': open_price,
                'high': close + 4,
                'low': open_price - 4,
                'close': close,
                'volume': 5000.0,
                'timestamp': ts,
            })
            price = close
        return candles

    @apply_patches
    def test_all_gates_pass_returns_trade_context(self, *mocks):
        ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['symbol'], 'BTCUSDT')
        self.assertEqual(ctx['direction'], 'LONG')
        self.assertEqual(ctx['strategy'], 'S1A')
        self.assertIn('S1A', ctx['strategy_candidates'])
        self.assertIn('gates_a', ctx)
        self.assertIn('gates_b', ctx)
        self.assertIn('gates_c', ctx)

    @apply_patches
    def test_all_gates_pass_saves_l1result(self, *mocks):
        self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        result = L1Result.objects.get(symbol='BTCUSDT')
        self.assertTrue(result.passed)

    def test_htf_trend_fail_returns_none(self):
        with patch('l1_filter.scanner.check_htf_trend', return_value=MOCK_FAIL):
            ctx = self.scanner.scan('BTCUSDT')
        self.assertIsNone(ctx)

    def test_htf_trend_fail_saves_failed_l1result(self):
        with patch('l1_filter.scanner.check_htf_trend', return_value=MOCK_FAIL):
            self.scanner.scan('BTCUSDT')
        result = L1Result.objects.get(symbol='BTCUSDT')
        self.assertFalse(result.passed)

    @patch('l1_filter.scanner.check_htf_trend', return_value=MOCK_LONG)
    @patch('l1_filter.scanner.check_killzone', return_value=MOCK_FAIL)
    def test_killzone_fail_returns_none(self, *_):
        ctx = self.scanner.scan('BTCUSDT')
        self.assertIsNone(ctx)

    @apply_patches
    def test_b_mandatory_gates_fail_no_s1_strategy(self, *mocks):
        # B1+B2 mandatory for S1. If they fail, S1 should not be in passing strategies.
        with patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_fvg_ob', return_value=MOCK_FAIL):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        # Scanner may return context (shadow tracking), but S1 strategy should fail
        from l1_filter.strategies import evaluate_strategies
        if ctx:
            passing = evaluate_strategies(ctx.get('gates_a',{}), ctx.get('gates_b',{}), ctx.get('gates_c',{}))
            self.assertNotIn('S1', passing)

    @apply_patches
    def test_c_gates_below_min_returns_none(self, *mocks):
        # S1 now requires CHoCH plus one secondary confirmation.
        with patch('l1_filter.scanner.check_choch', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_momentum_divergence', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_ema_crossover', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_volume_spike', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_vwap', return_value=MOCK_FAIL):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertIsNone(ctx)

    @apply_patches
    def test_requires_secondary_c_confirmation(self, *mocks):
        with patch('l1_filter.scanner.check_momentum_divergence', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_ema_crossover', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_volume_spike', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_vwap', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_obv_confirmation', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_price_action_trigger', return_value=MOCK_FAIL):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertIsNone(ctx)

    @apply_patches
    def test_requires_htf_poi_confluence_when_available(self, *mocks):
        with patch('l1_filter.scanner.check_liquidity_sweep',
                   return_value=(True, {'swept_level': 1480.0, 'nearest_liquidity': 1480.0, 'htf_poi_confluence': False})):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S1C')

    @apply_patches
    def test_requires_premium_discount_alignment(self, *mocks):
        with patch('l1_filter.scanner.check_premium_discount', return_value=MOCK_FAIL):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S1C')

    @apply_patches
    def test_trade_context_contains_required_fields(self, *mocks):
        ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
        for field in ('symbol', 'timestamp', 'direction', 'adx_value', 'funding_rate', 'regime', 'strategy'):
            self.assertIn(field, ctx, f"Missing field: {field}")

    @apply_patches
    def test_requested_s1b_strategy_selects_continuation_profile(self, *mocks):
        with patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S1B')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S1B')

    @apply_patches
    def test_requested_s1a_rejects_continuation_only_profile(self, *mocks):
        with patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S1A')
        self.assertIsNone(ctx)

    @apply_patches
    def test_requested_s1c_selects_reclaim_profile(self, *mocks):
        ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S1C')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S1C')
        self.assertEqual(ctx['entry_mode'], 'HYBRID')

    @apply_patches
    def test_requested_s2_selects_flow_momentum_profile(self, *mocks):
        with patch.object(self.scanner, '_get_volume_flow_signal', return_value={
            'score': 42.0,
            'confidence': 0.7,
            'bias': 'LONG',
            'reasoning': 'test',
            'metadata': {},
        }):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S2')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S2')
        self.assertEqual(ctx['entry_mode'], 'MARKET')
        self.assertIn('flow_signal', ctx)

    @apply_patches
    def test_requested_s2_rejects_without_flow_alignment(self, *mocks):
        with patch.object(self.scanner, '_get_volume_flow_signal', return_value={
            'score': 5.0,
            'confidence': 0.2,
            'bias': 'NEUTRAL',
            'reasoning': 'test',
            'metadata': {},
        }):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S2')
        self.assertIsNone(ctx)

    @apply_patches
    def test_requested_s3_selects_breakout_pullback_profile(self, *mocks):
        with patch.object(self.scanner, '_get_volume_flow_signal', return_value={
            'score': 0.0,
            'confidence': 0.0,
            'bias': 'NEUTRAL',
            'reasoning': 'test',
            'metadata': {},
        }), patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BNBUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S3')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S3')
        self.assertIn(ctx['entry_mode'], {'MARKET', 'HYBRID'})

    @apply_patches
    def test_requested_s3_can_pass_without_btc_correlation(self, *mocks):
        with patch.object(self.scanner, '_get_volume_flow_signal', return_value={
            'score': 0.0,
            'confidence': 0.0,
            'bias': 'NEUTRAL',
            'reasoning': 'test',
            'metadata': {},
        }), patch('l1_filter.scanner.check_btc_correlation', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BNBUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S3')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S3')

    @apply_patches
    def test_requested_s3_rejects_btc_symbol(self, *mocks):
        with patch.object(self.scanner, '_get_volume_flow_signal', return_value={
            'score': 0.0,
            'confidence': 0.0,
            'bias': 'NEUTRAL',
            'reasoning': 'test',
            'metadata': {},
        }), patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BTCUSDT', now=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), strategy='S3')
        self.assertIsNone(ctx)

    @apply_patches
    def test_requested_s4_selects_opening_range_breakout_profile(self, *mocks):
        now = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)

        def get_candles(_symbol, interval, _limit):
            if interval == '15m':
                return self._s4_candles(now)
            if interval == '1h':
                return self._s4_candles(now)[-12:]
            return self._s4_candles(now)

        self.scanner._get_candles = MagicMock(side_effect=get_candles)
        with patch('l1_filter.scanner.build_top_down_context', return_value={
                'allow_continuation': True,
                'state_1h': {'state': 'aligned_continuation'},
                'state_4h': {'divergence_aligned': False},
                'timing_15m': {'divergence_aligned': False},
            }), \
             patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('ETHUSDT', now=now, strategy='S4')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S4')
        self.assertEqual(ctx['entry_mode'], 'HYBRID')
        self.assertEqual(ctx['opening_range_breakout'], 'LONG')
        self.assertEqual(ctx['opening_range_high'], 1004.0)

    @apply_patches
    def test_requested_s4_rejects_without_breakout(self, *mocks):
        now = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
        flat_candles = self._s4_candles(now)
        for idx, candle in enumerate(flat_candles):
            if candle['timestamp'].hour == 14 and candle['timestamp'].minute == 0:
                flat_candles[idx] = {
                    **candle,
                    'close': 1003.0,
                    'high': 1004.0,
                }
                break

        def get_candles(_symbol, interval, _limit):
            if interval == '15m':
                return flat_candles
            if interval == '1h':
                return flat_candles[-12:]
            return flat_candles

        self.scanner._get_candles = MagicMock(side_effect=get_candles)
        with patch('l1_filter.scanner.build_top_down_context', return_value={
                'allow_continuation': True,
                'state_1h': {'state': 'aligned_continuation'},
                'state_4h': {'divergence_aligned': False},
                'timing_15m': {'divergence_aligned': False},
            }), \
             patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('ETHUSDT', now=now, strategy='S4')
        self.assertIsNone(ctx)

    @apply_patches
    def test_requested_s5_selects_trend_pullback_profile(self, *mocks):
        now = datetime(2026, 1, 1, 14, 45, tzinfo=timezone.utc)
        candles_15m = self._s5_15m_candles(now)
        candles_4h = self._s5_4h_candles(now)

        def get_candles(_symbol, interval, _limit):
            if interval == '4h':
                return candles_4h
            if interval == '15m':
                return candles_15m
            if interval == '1h':
                return candles_15m[-60:]
            return candles_4h

        self.scanner._get_candles = MagicMock(side_effect=get_candles)
        with patch('l1_filter.scanner.build_top_down_context', return_value={
                'allow_continuation': True,
                'state_1h': {'state': 'aligned_pullback'},
                'state_4h': {'divergence_aligned': False},
                'timing_15m': {'divergence_aligned': False},
            }), patch.object(L1Scanner, '_get_s5_candidate', return_value={
                'trigger_high': 1024.5,
                'trigger_low': 1012.0,
                'atr_15m': 12.0,
                'pullback_depth_atr': 0.65,
                'pullback_len': 3,
                'direction_override': 'LONG',
                'reclaim_price': 1020.0,
                'symbol_profile': 'BTCUSDT',
            }), patch('l1_filter.scanner.check_liquidity_sweep', return_value=MOCK_FAIL), \
             patch('l1_filter.scanner.check_choch', return_value=(True, {'type': 'BOS'})):
            ctx = self.scanner.scan('BTCUSDT', now=now, strategy='S5')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['strategy'], 'S5')
        self.assertEqual(ctx['entry_mode'], 'MARKET')
        self.assertIsNotNone(ctx['s5_trigger_high'])

    def test_s5_candidate_rejects_without_crsi_alignment(self):
        now = datetime(2026, 1, 1, 14, 45, tzinfo=timezone.utc)
        candles_15m = self._s5_15m_candles(now)
        candles_4h = self._s5_4h_candles(now)

        with patch('l1_filter.scanner.compute_connors_rsi', return_value=[72.0, 69.0]):
            candidate = self.scanner._get_s5_candidate(
                'BTCUSDT',
                'LONG',
                {'A2': True},
                {},
                {'state_1h': {'state': 'aligned_pullback'}},
                candles_4h,
                candles_15m,
                now,
            )

        self.assertIsNone(candidate)
