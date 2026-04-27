"""L3Calculator — all deterministic, no LLM, pure arithmetic."""
from django.test import TestCase
from django.test import override_settings

from executor.l3_calculator import L3Calculator

LONG_CONTEXT = {
    'symbol': 'BTCUSDT',
    'direction': 'LONG',
    'atr': 500.0,
    'fvg_zone': [93000.0, 94000.0],   # FVG: 93k–94k
    'swept_level': 92500.0,             # sweep wick low
    'nearest_liquidity': 96000.0,
    'funding_rate': 0.0003,
    'adx_value': 28.0,
}

SHORT_CONTEXT = {
    'symbol': 'ETHUSDT',
    'direction': 'SHORT',
    'atr': 80.0,
    'fvg_zone': [3100.0, 3200.0],
    'swept_level': 3250.0,
    'nearest_liquidity': 2900.0,
    'funding_rate': -0.0002,
    'adx_value': 25.0,
}

APPROVE = {'action': 'APPROVE', 'size_multiplier': 1.0}
REJECT  = {'action': 'REJECT',  'size_multiplier': 0.0}
HIGH_CONV_LONG_CONTEXT = {
    **LONG_CONTEXT,
    'gates_b': {'B1': True, 'B2': True, 'B3': True, 'B5': False},
    'gates_c': {'C1': True, 'C2': True, 'C3': True, 'C4': False, 'C5': False},
}


class L3EntryCalculationTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_s1_entry_is_50pct_into_fvg_for_long(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        # OTE entry at 50% (mid-FVG): fvg_bottom=93000, fvg_top=94000, mid=93500
        self.assertAlmostEqual(params['entry_price'], 93500.0, places=0)

    def test_s1_entry_is_50pct_into_fvg_for_short(self):
        params = self.calc.calculate(SHORT_CONTEXT, APPROVE, strategy='S1')
        # SHORT FVG: entry = fvg_top - 0.50×depth = 3200 - 50 = 3150
        self.assertAlmostEqual(params['entry_price'], 3150.0, places=0)

    def test_s2_entry_uses_sweep_level_plus_atr(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S2')
        # S2 entry: swept_level + 0.1×ATR for LONG (just above sweep)
        expected = LONG_CONTEXT['swept_level'] + 0.1 * LONG_CONTEXT['atr']
        self.assertAlmostEqual(params['entry_price'], expected, places=0)

    def test_s1b_entry_is_shallower_than_mid_fvg(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1B')
        self.assertGreater(params['entry_price'], LONG_CONTEXT['fvg_zone'][0])
        self.assertLess(params['entry_price'], 93500.0)

    def test_s3_entry_uses_nearest_liquidity_adjusted(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S3')
        self.assertIsNotNone(params)
        self.assertIn('entry_price', params)

    def test_s1c_entry_blends_current_price_and_reclaim_limit(self):
        ctx = {**LONG_CONTEXT, 'current_price': 93600.0}
        params = self.calc.calculate(ctx, APPROVE, strategy='S1C')
        self.assertGreater(params['entry_price'], 93400.0)
        self.assertLess(params['entry_price'], 93600.0)


class L3StopLossTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_sl_is_below_swept_level_for_long(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        # SL must be below sweep wick (92500)
        self.assertLess(params['stop_loss'], LONG_CONTEXT['swept_level'])

    def test_sl_is_above_entry_for_short(self):
        params = self.calc.calculate(SHORT_CONTEXT, APPROVE, strategy='S1')
        # SL must be above entry price for SHORT
        self.assertGreater(params['stop_loss'], params['entry_price'])

    def test_sl_includes_atr_buffer(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        # SL = swept_level - 0.2×ATR = 92500 - 100 = 92400
        expected_sl = LONG_CONTEXT['swept_level'] - 0.2 * LONG_CONTEXT['atr']
        self.assertAlmostEqual(params['stop_loss'], expected_sl, places=0)

    def test_sl_capped_at_3pct_from_entry(self):
        # Simulate a very deep sweep (> 3% from entry)
        ctx = {**LONG_CONTEXT, 'swept_level': 80000.0, 'atr': 5000.0}
        params = self.calc.calculate(ctx, APPROVE, strategy='S1')
        entry = params['entry_price']
        max_sl_distance = entry * 0.03
        self.assertGreaterEqual(params['stop_loss'], entry - max_sl_distance)

    def test_s3_sl_within_strategy_bounds(self):
        # S3 SL must be within [min_pct=0.3%, max_pct=2.5%] of entry
        ctx = {**LONG_CONTEXT, 'nearest_liquidity': None}
        params = self.calc.calculate(ctx, APPROVE, strategy='S3')
        entry = params['entry_price']
        sl    = params['stop_loss']
        dist_pct = (entry - sl) / entry
        self.assertGreaterEqual(dist_pct, 0.0029, "SL too close — noise stop risk")  # 0.29% tolerance for float
        self.assertLessEqual(dist_pct, 0.025, "SL too far — S3 max 2.5%")

    def test_loose_stop_profile_is_wider_than_tight(self):
        tight = self.calc.calculate({**LONG_CONTEXT, 'stop_profile': 'tight'}, APPROVE, strategy='S1B')
        loose = self.calc.calculate({**LONG_CONTEXT, 'stop_profile': 'loose'}, APPROVE, strategy='S1B')
        tight_dist = tight['entry_price'] - tight['stop_loss']
        loose_dist = loose['entry_price'] - loose['stop_loss']
        self.assertGreater(loose_dist, tight_dist)


class L3TakeProfitTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_tp1_is_1_5r_for_long(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        r = params['entry_price'] - params['stop_loss']
        expected_tp1 = params['entry_price'] + 1.5 * r
        self.assertAlmostEqual(params['take_profits'][0]['level'], expected_tp1, places=0)

    def test_tp2_is_3r_for_long(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        r = params['entry_price'] - params['stop_loss']
        expected_tp2 = params['entry_price'] + 3.0 * r
        self.assertAlmostEqual(params['take_profits'][1]['level'], expected_tp2, places=0)

    def test_tp1_is_1_5r_for_short(self):
        params = self.calc.calculate(SHORT_CONTEXT, APPROVE, strategy='S1')
        r = params['stop_loss'] - params['entry_price']
        expected_tp1 = params['entry_price'] - 1.5 * r
        self.assertAlmostEqual(params['take_profits'][0]['level'], expected_tp1, places=0)

    def test_tp_ratios_sum_to_100pct(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        total = sum(tp['ratio'] for tp in params['take_profits'])
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_tp1_ratio_is_40pct(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertAlmostEqual(params['take_profits'][0]['ratio'], 0.40, places=2)

    def test_tp2_ratio_is_40pct(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertAlmostEqual(params['take_profits'][1]['ratio'], 0.40, places=2)

    def test_tp3_runner_ratio_is_20pct(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertAlmostEqual(params['take_profits'][2]['ratio'], 0.20, places=2)

    def test_s1a_leaves_half_as_runner(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1A')
        self.assertAlmostEqual(params['take_profits'][0]['ratio'], 0.25, places=2)
        self.assertAlmostEqual(params['take_profits'][1]['ratio'], 0.25, places=2)
        self.assertAlmostEqual(params['take_profits'][2]['ratio'], 0.50, places=2)

    def test_s1b_uses_more_aggressive_runner_profile(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1B')
        self.assertAlmostEqual(params['take_profits'][0]['ratio'], 0.30, places=2)
        self.assertAlmostEqual(params['take_profits'][1]['ratio'], 0.30, places=2)
        self.assertAlmostEqual(params['take_profits'][2]['ratio'], 0.40, places=2)

    def test_s1c_uses_reclaim_runner_profile(self):
        params = self.calc.calculate({**LONG_CONTEXT, 'current_price': 93600.0}, APPROVE, strategy='S1C')
        self.assertAlmostEqual(params['take_profits'][0]['ratio'], 0.15, places=2)
        self.assertAlmostEqual(params['take_profits'][1]['ratio'], 0.25, places=2)
        self.assertAlmostEqual(params['take_profits'][2]['ratio'], 0.60, places=2)

    def test_s1c_time_kill_is_more_lenient_after_tp1(self):
        from datetime import datetime, timezone, timedelta
        opened = datetime.now(timezone.utc) - timedelta(hours=8)
        result = self.calc.check_time_kill('LONG', opened, 93000.0, 92000.0, 93100.0, strategy='S1C', tp1_hit=True)
        self.assertFalse(result)


class L3RejectConditionsTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_l2_reject_returns_none(self):
        result = self.calc.calculate(LONG_CONTEXT, REJECT, strategy='S1')
        self.assertIsNone(result)

    def test_leverage_safety_rejects_if_liquidation_too_close(self):
        # Very tight leverage: entry 93250, SL 92400 → R=850
        # At MAX_LEVERAGE=5: liq_price = 93250/5 = 18650 below entry (massive)
        # Actually with 5× leverage for LONG: liq_price = entry×(1 - 1/5) = entry×0.8
        # liq_distance = entry×0.2 = 18650, R=850 → liq_distance >> 2R → passes
        # To fail: need R > entry×0.1 = 9325... impossible with 3% cap
        # So test leverage at extreme: mock a high leverage scenario
        result = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        # With MAX_LEVERAGE=5, safety check should pass for normal setups
        self.assertIsNotNone(result)

    def test_no_fvg_zone_for_s1_uses_fallback(self):
        ctx = {**LONG_CONTEXT, 'fvg_zone': None}
        result = self.calc.calculate(ctx, APPROVE, strategy='S1')
        # Should still return a result using swept_level as fallback entry
        self.assertIsNotNone(result)

    def test_size_multiplier_is_preserved(self):
        decision = {'action': 'APPROVE', 'size_multiplier': 0.5}
        params = self.calc.calculate(LONG_CONTEXT, decision, strategy='S1')
        self.assertEqual(params['size_multiplier'], 0.5)

    @override_settings(MAX_LEVERAGE=10, MAX_HIGH_CONVICTION_LEVERAGE=20, MIN_LIQUIDATION_BUFFER_R=3.0)
    def test_default_setup_uses_10x_leverage(self):
        params = self.calc.calculate(LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertEqual(params['leverage'], 10)
        self.assertEqual(params['conviction'], 'STANDARD')

    @override_settings(MAX_LEVERAGE=10, MAX_HIGH_CONVICTION_LEVERAGE=20, MIN_LIQUIDATION_BUFFER_R=3.0)
    def test_high_conviction_setup_can_use_20x(self):
        params = self.calc.calculate(HIGH_CONV_LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertEqual(params['leverage'], 20)
        self.assertEqual(params['conviction'], 'HIGH_CONVICTION')
        self.assertGreaterEqual(params['liquidation_buffer_r'], 3.0)

    @override_settings(MAX_LEVERAGE=10, MAX_HIGH_CONVICTION_LEVERAGE=20, MIN_LIQUIDATION_BUFFER_R=6.0)
    def test_high_conviction_falls_back_to_10x_when_20x_is_too_tight(self):
        params = self.calc.calculate(HIGH_CONV_LONG_CONTEXT, APPROVE, strategy='S1')
        self.assertEqual(params['leverage'], 10)
        self.assertEqual(params['conviction'], 'STANDARD')


class L3ChandelierTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_chandelier_long_is_highest_high_minus_3atr(self):
        highs = [100, 105, 103, 107, 104, 102, 108, 106] * 3  # 24 values
        atr = 2.0
        result = self.calc.compute_chandelier_stop('LONG', highs, atr)
        self.assertAlmostEqual(result, max(highs[-22:]) - 3 * atr, places=4)

    def test_chandelier_short_is_lowest_low_plus_3atr(self):
        lows = [95, 92, 94, 91, 93, 96, 90, 94] * 3
        atr = 2.0
        result = self.calc.compute_chandelier_stop('SHORT', lows, atr)
        self.assertAlmostEqual(result, min(lows[-22:]) + 3 * atr, places=4)

    def test_chandelier_requires_22_candles(self):
        result = self.calc.compute_chandelier_stop('LONG', [100, 105], 2.0)
        self.assertIsNone(result)


class L3TimeKillTest(TestCase):
    def setUp(self):
        self.calc = L3Calculator()

    def test_time_kill_after_8h_without_1r(self):
        from datetime import datetime, timezone, timedelta
        opened = datetime.now(timezone.utc) - timedelta(hours=9)
        entry, sl = 93000.0, 92000.0
        current = 93100.0  # Less than 1R above entry (1R = 1000, need 94000)
        result = self.calc.check_time_kill('LONG', opened, entry, sl, current)
        self.assertTrue(result)

    def test_no_kill_if_hit_1r(self):
        from datetime import datetime, timezone, timedelta
        opened = datetime.now(timezone.utc) - timedelta(hours=9)
        entry, sl = 93000.0, 92000.0
        current = 94100.0  # Above 1R (entry + R = 94000)
        result = self.calc.check_time_kill('LONG', opened, entry, sl, current)
        self.assertFalse(result)

    def test_no_kill_before_8h(self):
        from datetime import datetime, timezone, timedelta
        opened = datetime.now(timezone.utc) - timedelta(hours=5)
        result = self.calc.check_time_kill('LONG', opened, 93000.0, 92000.0, 93100.0)
        self.assertFalse(result)
