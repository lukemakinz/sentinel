from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from l2_agents.global_context import (
    EXTERNAL_INDICATORS,
    MIN_BREADTH_SYMBOLS,
    GLOBAL_CONTEXT_VERSION,
    build_global_context,
    candidate_alignment,
)
from l2_agents.mechanical_baseline import (
    global_context_filter_assessment,
    global_context_filtered_decision,
    mechanical_decision,
)
from l2_agents.tests.test_auction_adjudicator import baseline_snapshot


def frames(trend_1h, trend_4h, return_20_pct=0.0):
    return {
        '1h': {'available': True, 'trend': trend_1h,
               'return_20_pct': return_20_pct, 'bars': 220},
        '4h': {'available': True, 'trend': trend_4h, 'bars': 220},
    }


def market(btc, eth, alts, eth_ret=0.0, btc_ret=0.0):
    summaries = {
        'BTCUSDT': frames(*btc, return_20_pct=btc_ret),
        'ETHUSDT': frames(*eth, return_20_pct=eth_ret),
    }
    for index, trend in enumerate(alts):
        summaries[f'ALT{index}USDT'] = frames(trend, trend)
    return summaries


class GlobalContextUnitTest(SimpleTestCase):
    def test_external_indicators_are_explicitly_unavailable_never_inferred(self):
        context = build_global_context(market(('UP', 'UP'), ('UP', 'UP'), ['UP']), 'SOLUSDT')
        self.assertEqual(context['version'], GLOBAL_CONTEXT_VERSION)
        self.assertFalse(context['external_data_used'])
        self.assertFalse(context['execution_authorized'])
        self.assertEqual(set(context['external_indicators']), set(EXTERNAL_INDICATORS))
        for slot in context['external_indicators'].values():
            self.assertFalse(slot['available'])
            self.assertFalse(slot['used_in_score'])

    def test_broad_risk_on_for_alt(self):
        context = build_global_context(
            market(('UP', 'UP'), ('UP', 'UP'), ['UP'] * 6, eth_ret=4, btc_ret=1),
            'SOLUSDT',
        )
        self.assertEqual(context['state'], 'ALT_RISK_ON')
        self.assertEqual(context['target_class'], 'ALT')
        self.assertEqual(context['target_data_coverage_0_1'], 1.0)
        self.assertGreater(context['target_bias_score_minus100_100'], 35)

    def test_btc_led_alt_headwind(self):
        # BTC up, alts bleeding, ETH lagging BTC: the "great chart, bad tape" case.
        context = build_global_context(
            market(('UP', 'UP'), ('DOWN', 'DOWN'), ['DOWN'] * 6,
                   eth_ret=-3, btc_ret=2),
            'SOLUSDT',
        )
        self.assertEqual(context['state'], 'BTC_LED_ALT_HEADWIND')
        self.assertEqual(candidate_alignment(context, 'LONG')['status'], 'OPPOSED')
        self.assertEqual(candidate_alignment(context, 'SHORT')['status'], 'ALIGNED')

    def test_breadth_excludes_target_and_needs_minimum_alts(self):
        summaries = market(('UP', 'UP'), ('UP', 'UP'), ['UP'] * (MIN_BREADTH_SYMBOLS - 1))
        summaries['SOLUSDT'] = frames('UP', 'UP')
        context = build_global_context(summaries, 'SOLUSDT')
        breadth = context['components']['alt_breadth_1h']
        self.assertFalse(breadth['available'])
        self.assertEqual(breadth['symbols'], MIN_BREADTH_SYMBOLS - 1)
        self.assertLess(context['target_data_coverage_0_1'], 1.0)

    def test_missing_data_is_unknown_not_neutral(self):
        context = build_global_context({}, 'SOLUSDT')
        self.assertEqual(context['state'], 'UNKNOWN')
        self.assertIsNone(context['target_bias_score_minus100_100'])
        self.assertEqual(candidate_alignment(context, 'LONG')['status'], 'UNKNOWN')

    def test_btc_target_uses_only_btc_trend(self):
        context = build_global_context(
            market(('UP', 'UP'), ('DOWN', 'DOWN'), ['DOWN']), 'BTCUSDT',
        )
        self.assertEqual(context['target_class'], 'BTC')
        self.assertEqual(context['target_bias_score_minus100_100'], 100.0)

    def test_stale_and_underwarmed_breadth_are_excluded_not_neutral(self):
        now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        summaries = market(('UP', 'UP'), ('UP', 'UP'), ['UP'] * 6)
        for frames_by_interval in summaries.values():
            frames_by_interval['1h']['last_timestamp'] = (
                now - timedelta(hours=1)
            ).isoformat()
            frames_by_interval['4h']['last_timestamp'] = (
                now - timedelta(hours=4)
            ).isoformat()
        summaries['ALT0USDT']['1h']['bars'] = 3
        summaries['ALT1USDT']['1h']['last_timestamp'] = (
            now - timedelta(hours=6)
        ).isoformat()

        context = build_global_context(summaries, 'SOLUSDT', as_of=now)
        breadth = context['components']['alt_breadth_1h']

        self.assertFalse(breadth['available'])
        self.assertEqual(breadth['symbols'], 4)
        self.assertEqual(breadth['excluded_by_quality']['insufficient_history'], 1)
        self.assertEqual(breadth['excluded_by_quality']['stale'], 1)


class GlobalContextFilterTest(SimpleTestCase):
    def setUp(self):
        self.snapshot = baseline_snapshot('TREND_UP', 100.5)
        self.baseline = mechanical_decision(self.snapshot)
        self.assertEqual(self.baseline.action, 'ARM')

    def _with(self, summaries):
        return {**self.snapshot, 'global_context': build_global_context(summaries, 'SOLUSDT')}

    def test_keeps_candidate_when_context_supports_it(self):
        snap = self._with(market(('UP', 'UP'), ('UP', 'UP'), ['UP'] * 6))
        decision = global_context_filtered_decision(snap, self.baseline)
        self.assertEqual(decision.action, 'ARM')
        self.assertEqual(decision.direction, self.baseline.direction)
        self.assertEqual(decision.entry_zone, self.baseline.entry_zone)

    def test_vetoes_long_into_strong_global_headwind(self):
        snap = self._with(market(('DOWN', 'DOWN'), ('DOWN', 'DOWN'),
                                 ['DOWN'] * 6, eth_ret=-3))
        decision = global_context_filtered_decision(snap, self.baseline)
        self.assertEqual(decision.action, 'PASS')
        self.assertIn('vetoed', decision.counter_thesis[0])
        self.assertEqual(
            global_context_filter_assessment(snap, self.baseline.direction)['reason_code'],
            'GLOBAL_HEADWIND_VETO',
        )

    def test_missing_context_fails_closed(self):
        decision = global_context_filtered_decision(self.snapshot, self.baseline)
        self.assertEqual(decision.action, 'PASS')
        self.assertIn('unavailable', decision.counter_thesis[0])
        self.assertIn('M3_REASON_CODE=DATA_INELIGIBLE', decision.risk_notes)


class FrozenBreadthUniverseTest(SimpleTestCase):
    def test_breadth_counts_only_frozen_universe_and_records_version(self):
        summaries = market(('UP', 'UP'), ('UP', 'UP'), ['DOWN'] * 6)
        universe = {'version': 'u-test', 'symbols': [f'ALT{i}USDT' for i in range(5)]}
        summaries['EXTRAUSDT'] = frames('UP', 'UP')  # watched later, not in universe
        context = build_global_context(summaries, 'SOLUSDT', breadth_universe=universe)
        breadth = context['components']['alt_breadth_1h']
        self.assertEqual(breadth['symbols'], 5)
        self.assertEqual(breadth['down_share'], 1.0)
        self.assertEqual(context['breadth_universe']['version'], 'u-test')
