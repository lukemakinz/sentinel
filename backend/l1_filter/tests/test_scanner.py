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
