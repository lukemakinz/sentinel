from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from l2_agents.auction_adjudicator import (
    AuctionAdjudicator,
    AuctionDecision,
    estimate_openai_analysis_cost,
)
from l2_agents.market_intelligence import MarketSnapshotBuilder, deterministic_preflight
from l2_agents.models import AuctionAnalysis


def complete_snapshot():
    return {
        'data_quality': {'tradable': True, 'score': 1.0, 'hard_failures': []},
        'strategy_registry': {
            'SAI1_FAILED_AUCTION': 'SHADOW_ONLY',
            'SAI1_IFVG_FLIP': 'SHADOW_ONLY',
            'SAI1_TREND_RETEST': 'SHADOW_ONLY',
        },
        'allowed_management_policies': [
            'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID',
        ],
        'zones': [
            {'kind': 'RECENT_SUPPORT', 'low': 99.0, 'high': 99.0},
            {'kind': 'RECENT_RESISTANCE', 'low': 100.0, 'high': 101.0},
        ],
        'execution_authorized': False,
    }


class AuctionAdjudicatorSafetyTest(TestCase):
    def test_missing_market_data_fails_preflight_closed(self):
        snapshot = MarketSnapshotBuilder().build('BTCUSDT')
        decision = deterministic_preflight(snapshot)

        self.assertEqual(decision['action'], 'PASS')
        self.assertEqual(decision['direction'], 'NONE')
        self.assertTrue(snapshot['data_quality']['hard_failures'])
        self.assertFalse(snapshot['execution_authorized'])

    @override_settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY='')
    def test_no_provider_fails_closed_even_with_complete_snapshot(self):
        decision, runtime = AuctionAdjudicator().analyze(complete_snapshot())

        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(runtime['reason'], 'no_api_key')

    @override_settings(
        AUCTION_AI_PROVIDER='openai',
        AUCTION_OPENAI_MODEL='gpt-6.1-sol',
        OPENAI_API_KEY='sk-test',
        ANTHROPIC_API_KEY='sk-ant-test',
    )
    def test_auction_explicitly_prefers_openai_when_both_keys_exist(self):
        model_decision = AuctionDecision(
            action='WAIT', direction='NONE', strategy_id='NONE', confidence=0.5,
            data_quality=1.0, thesis=['No trigger yet'], counter_thesis=['Could break'],
            entry_zone=None, trigger_conditions=[], invalidation_conditions=[],
            management_policy='NONE', ttl_minutes=15,
            recheck_condition='next close', risk_notes=['shadow'],
        )
        with patch.object(
            AuctionAdjudicator, '_call_openai', return_value=(model_decision, {}),
        ) as openai_call, patch.object(AuctionAdjudicator, '_call_anthropic') as anthropic_call:
            decision, runtime = AuctionAdjudicator().analyze(complete_snapshot())

        self.assertEqual(decision.action, 'WAIT')
        self.assertEqual(runtime['provider'], 'openai')
        self.assertEqual(runtime['model'], 'gpt-6.1-sol')
        openai_call.assert_called_once()
        anthropic_call.assert_not_called()

    @override_settings(
        AUCTION_OPENAI_MODEL='gpt-6.1-sol',
        AUCTION_OPENAI_REASONING_EFFORT='high',
        AUCTION_OPENAI_INPUT_USD_PER_MILLION=2.0,
        AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION=0.10,
        AUCTION_OPENAI_OUTPUT_USD_PER_MILLION=10.0,
        OPENAI_API_KEY='sk-test',
    )
    @patch('openai.OpenAI')
    def test_openai_responses_function_call_is_parsed(self, openai_cls):
        payload = {
            'action': 'PASS', 'direction': 'NONE', 'strategy_id': 'NONE',
            'confidence': 0.4, 'data_quality': 1.0, 'thesis': ['No edge'],
            'counter_thesis': ['A later trigger may form'], 'entry_zone': None,
            'trigger_conditions': [], 'invalidation_conditions': [],
            'management_policy': 'NONE', 'ttl_minutes': 15,
            'recheck_condition': 'next close', 'risk_notes': ['shadow only'],
        }
        openai_cls.return_value.responses.create.return_value = SimpleNamespace(
            output=[SimpleNamespace(
                type='function_call', name='submit_auction_decision',
                arguments=json.dumps(payload),
            )],
            usage=SimpleNamespace(
                input_tokens=123,
                input_tokens_details=SimpleNamespace(cached_tokens=23),
                output_tokens=45,
                output_tokens_details=SimpleNamespace(reasoning_tokens=12),
            ),
        )

        decision, usage = AuctionAdjudicator()._call_openai(complete_snapshot())

        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(usage['input_tokens'], 123)
        self.assertEqual(usage['cached_input_tokens'], 23)
        self.assertEqual(usage['output_tokens'], 45)
        self.assertEqual(usage['reasoning_tokens'], 12)
        self.assertEqual(usage['analysis_cost']['estimated_usd'], 0.0006523)
        self.assertEqual(usage['analysis_cost']['display'], '$0.00065230 USD')
        kwargs = openai_cls.return_value.responses.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'gpt-6.1-sol')
        self.assertEqual(kwargs['reasoning'], {'effort': 'high'})
        self.assertEqual(kwargs['tools'][0]['name'], 'submit_auction_decision')

    @override_settings(
        AUCTION_OPENAI_INPUT_USD_PER_MILLION=2.0,
        AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION=0.10,
        AUCTION_OPENAI_OUTPUT_USD_PER_MILLION=10.0,
    )
    def test_cost_uses_long_context_multipliers(self):
        cost = estimate_openai_analysis_cost(
            model='gpt-6.1-sol', input_tokens=300_000,
            cached_input_tokens=100_000, output_tokens=10_000,
        )

        self.assertEqual(cost['pricing_tier'], 'standard_long_context')
        self.assertEqual(cost['estimated_usd'], 0.97)

    def test_arm_requires_zone_trigger_and_invalidation(self):
        decision = AuctionDecision(
            action='ARM', direction='LONG', strategy_id='SAI1_TREND_RETEST',
            confidence=0.8, data_quality=1.0, thesis=['trend'], counter_thesis=['failure'],
            entry_zone=None, trigger_conditions=[], invalidation_conditions=[],
            management_policy='P0_INITIAL_STOP', ttl_minutes=15,
            recheck_condition='on retest', risk_notes=[],
        )
        with self.assertRaises(ValueError):
            AuctionAdjudicator._validate_against_snapshot(decision, complete_snapshot())

    def test_valid_arm_is_still_shadow_only(self):
        decision = AuctionDecision(
            action='ARM', direction='SHORT', strategy_id='SAI1_FAILED_AUCTION',
            confidence=0.8, data_quality=1.0, thesis=['failed auction'],
            counter_thesis=['trend continuation'], entry_zone=[100.0, 101.0],
            trigger_conditions=['15m close below 100'],
            invalidation_conditions=['15m close above 101'],
            management_policy='P0_INITIAL_STOP', ttl_minutes=15,
            recheck_condition='next 15m close', risk_notes=['shadow'],
        )
        AuctionAdjudicator._validate_against_snapshot(decision, complete_snapshot())

    def test_arm_cannot_invent_a_nearby_zone(self):
        decision = AuctionDecision(
            action='ARM', direction='SHORT', strategy_id='SAI1_FAILED_AUCTION',
            confidence=0.8, data_quality=1.0, thesis=['failed auction'],
            counter_thesis=['trend continuation'], entry_zone=[100.0, 100.9],
            trigger_conditions=['15m close below 100'],
            invalidation_conditions=['15m close above 101'],
            management_policy='P0_INITIAL_STOP', ttl_minutes=15,
            recheck_condition='next 15m close', risk_notes=['shadow'],
        )
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            AuctionAdjudicator._validate_against_snapshot(decision, complete_snapshot())

    def test_ifvg_strategy_requires_fvg_zone(self):
        decision = AuctionDecision(
            action='ARM', direction='SHORT', strategy_id='SAI1_IFVG_FLIP',
            confidence=0.8, data_quality=1.0, thesis=['flip'],
            counter_thesis=['reclaim'], entry_zone=[100.0, 101.0],
            trigger_conditions=['close below zone'],
            invalidation_conditions=['close above zone'],
            management_policy='P0_INITIAL_STOP', ttl_minutes=15,
            recheck_condition='next close', risk_notes=['shadow'],
        )
        with self.assertRaisesRegex(ValueError, 'requires a supplied FVG'):
            AuctionAdjudicator._validate_against_snapshot(decision, complete_snapshot())


class AnalyzeMarketCommandTest(TestCase):
    def test_command_saves_fail_closed_shadow_audit(self):
        output = StringIO()
        call_command('analyze_market', 'BTCUSDT', stdout=output)

        record = AuctionAnalysis.objects.get()
        self.assertEqual(record.action, 'PASS')
        self.assertTrue(record.shadow_only)
        self.assertFalse(record.snapshot['execution_authorized'])
        self.assertIn('"execution_authorized": false', output.getvalue())
        parsed = json.loads(output.getvalue())
        self.assertEqual(list(parsed)[-1], 'analysis_cost')
        self.assertEqual(parsed['analysis_cost']['estimated_usd'], 0.0)

    def test_no_save_leaves_database_untouched(self):
        call_command('analyze_market', 'ETHUSDT', no_save=True, compact=True, stdout=StringIO())
        self.assertEqual(AuctionAnalysis.objects.count(), 0)


def billed_openai_response(arguments):
    return SimpleNamespace(
        output=[SimpleNamespace(
            type='function_call', name='submit_auction_decision',
            arguments=arguments,
        )],
        usage=SimpleNamespace(
            input_tokens=1000,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=1000,
            output_tokens_details=SimpleNamespace(reasoning_tokens=500),
        ),
    )


@override_settings(
    AUCTION_AI_PROVIDER='openai', OPENAI_API_KEY='sk-test',
    AUCTION_OPENAI_INPUT_USD_PER_MILLION=2.0,
    AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION=0.10,
    AUCTION_OPENAI_OUTPUT_USD_PER_MILLION=10.0,
    AUCTION_AI_DAILY_BUDGET_USD=1.0,
)
class AuctionAnalysisCostAccountingTest(TestCase):
    unlisted_arm = {
        'action': 'ARM', 'direction': 'SHORT', 'strategy_id': 'SAI1_FAILED_AUCTION',
        'confidence': 0.8, 'data_quality': 1.0, 'thesis': ['t'],
        'counter_thesis': ['c'], 'entry_zone': [100.0, 100.5],
        'trigger_conditions': ['x'], 'invalidation_conditions': ['y'],
        'management_policy': 'P0_INITIAL_STOP', 'ttl_minutes': 15,
        'recheck_condition': 'r', 'risk_notes': ['s'],
    }

    candidate = {'strategy_id': 'SAI1_FAILED_AUCTION', 'direction': 'SHORT',
                 'entry_zone': [100.0, 101.0], 'management_policy': 'P0_INITIAL_STOP',
                 'thesis': ['t'], 'key': 'XUSDT:SHORT:SAI1_FAILED_AUCTION:100:101'}

    def _analyze(self, response):
        from l2_agents.auction_service import decide_snapshot
        wait = {**self.unlisted_arm, 'action': 'WAIT'}
        with patch('l2_agents.auction_adjudicator.deterministic_preflight', return_value=wait), \
                patch('l2_agents.auction_service.deterministic_preflight', return_value=wait), \
                patch('l2_agents.auction_service.mechanical_candidate', return_value=self.candidate), \
                patch('openai.OpenAI') as openai_cls:
            openai_cls.return_value.responses.create.return_value = response
            result = decide_snapshot(complete_snapshot(), use_ai=True)
        return result, openai_cls

    def test_rejected_arm_keeps_billed_cost(self):
        (decision, runtime), _ = self._analyze(
            billed_openai_response(json.dumps(self.unlisted_arm)),
        )

        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(runtime['error_type'], 'ValueError')
        self.assertEqual(runtime['analysis_cost']['estimated_usd'], 0.012)
        self.assertEqual(runtime['analysis_cost']['reason'], 'billed_response_rejected')

    def test_unparseable_response_keeps_billed_cost(self):
        (decision, runtime), _ = self._analyze(billed_openai_response('{not json'))

        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(runtime['analysis_cost']['estimated_usd'], 0.012)

    def test_exhausted_daily_budget_skips_api_call(self):
        AuctionAnalysis.objects.create(
            symbol='SOLUSDT', snapshot_hash='h', snapshot_version='v',
            action='PASS', direction='NONE', strategy_id='NONE',
            snapshot={}, decision={}, shadow_only=True,
            runtime={'analysis_cost': {'estimated_usd': 1.25}},
        )
        (decision, runtime), openai_cls = self._analyze(
            billed_openai_response(json.dumps(self.unlisted_arm)),
        )

        openai_cls.return_value.responses.create.assert_not_called()
        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(runtime['reason'], 'ai_daily_budget_exhausted')
        self.assertEqual(runtime['analysis_cost']['estimated_usd'], 0.0)

    def test_deduplicated_result_is_not_billed_again(self):
        from l2_agents.auction_service import analyze_symbol
        paid = {'status': 'estimated', 'estimated_usd': 0.02, 'display': '$0.02000000 USD'}
        with patch('l2_agents.auction_service.decide_snapshot') as decide:
            decide.return_value = (
                AuctionDecision(**{**self.unlisted_arm, 'action': 'PASS',
                                   'direction': 'NONE', 'strategy_id': 'NONE'}),
                {'provider': 'openai', 'model': 'gpt-6.1-sol', 'analysis_cost': paid},
            )
            first = analyze_symbol('BTCUSDT', use_ai=True, deduplicate_bar=True)
            second = analyze_symbol('BTCUSDT', use_ai=True, deduplicate_bar=True)

        self.assertEqual(decide.call_count, 1)
        self.assertEqual(first['analysis_cost']['estimated_usd'], 0.02)
        self.assertFalse(second['created'])
        self.assertEqual(second['analysis_cost']['estimated_usd'], 0.0)
        self.assertEqual(second['runtime']['analysis_cost']['estimated_usd'], 0.02)


class ManagementPolicyRegistryTest(TestCase):
    def test_snapshot_only_offers_policies_the_resolver_simulates(self):
        snapshot = MarketSnapshotBuilder().build('BTCUSDT')
        self.assertEqual(snapshot['allowed_management_policies'], ['P0_INITIAL_STOP'])

    def test_unsimulated_policy_is_rejected(self):
        snapshot = {**complete_snapshot(), 'allowed_management_policies': ['P0_INITIAL_STOP']}
        decision = AuctionDecision(
            action='ARM', direction='SHORT', strategy_id='SAI1_FAILED_AUCTION',
            confidence=0.8, data_quality=1.0, thesis=['failed auction'],
            counter_thesis=['trend continuation'], entry_zone=[100.0, 101.0],
            trigger_conditions=['15m close below 100'],
            invalidation_conditions=['15m close above 101'],
            management_policy='P2_HYBRID', ttl_minutes=15,
            recheck_condition='next 15m close', risk_notes=['shadow'],
        )
        with self.assertRaisesRegex(ValueError, 'Unknown management policy'):
            AuctionAdjudicator._validate_against_snapshot(decision, snapshot)


def baseline_snapshot(regime, close):
    return {
        **complete_snapshot(),
        'data_quality': {'tradable': True, 'score': 1.0, 'hard_failures': []},
        'allowed_management_policies': ['P0_INITIAL_STOP'],
        'global_regime': {'state': regime},
        'instrument': {'15m': {'close': close, 'atr14': 1.0}},
    }


class MechanicalBaselineTest(TestCase):
    def test_trend_up_arms_long_failed_auction_at_support(self):
        from l2_agents.mechanical_baseline import mechanical_decision
        decision = mechanical_decision(baseline_snapshot('TREND_UP', 100.5))

        self.assertEqual(decision.action, 'ARM')
        self.assertEqual(decision.direction, 'LONG')
        self.assertEqual(decision.entry_zone, [99.0, 99.0])
        self.assertEqual(decision.management_policy, 'P0_INITIAL_STOP')

    def test_trend_down_never_longs(self):
        from l2_agents.mechanical_baseline import mechanical_decision
        decision = mechanical_decision(baseline_snapshot('TREND_DOWN', 99.5))

        self.assertEqual(decision.direction, 'SHORT')
        self.assertEqual(decision.entry_zone, [100.0, 101.0])

    def test_transition_and_far_extremes_pass(self):
        from l2_agents.mechanical_baseline import mechanical_decision
        self.assertEqual(mechanical_decision(baseline_snapshot('TRANSITION', 100.0)).action, 'PASS')
        self.assertEqual(mechanical_decision(baseline_snapshot('TREND_UP', 105.0)).action, 'PASS')

    def test_baseline_is_recorded_once_per_bar_at_zero_cost(self):
        from l2_agents.auction_service import record_mechanical_baseline
        snapshot = {
            **baseline_snapshot('TRANSITION', 100.0),
            'version': 'v', 'symbol': 'SOLUSDT', 'snapshot_hash': 'h',
            'as_of': '2026-10-26T12:07:00+00:00',
        }
        first = record_mechanical_baseline(snapshot)
        second = record_mechanical_baseline(snapshot)

        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        record = AuctionAnalysis.objects.get()
        self.assertEqual(record.provider, 'mechanical')
        self.assertEqual(record.runtime['analysis_cost']['estimated_usd'], 0.0)

    def test_baseline_arm_creates_shadow_plan_reported_as_baseline(self):
        from l2_agents.auction_service import record_mechanical_baseline
        from l2_agents.management.commands.auction_shadow_report import build_report
        snapshot = {
            **baseline_snapshot('TREND_UP', 100.5),
            'version': 'v', 'symbol': 'SOLUSDT', 'snapshot_hash': 'h',
            'as_of': '2026-10-26T12:07:00+00:00',
        }
        result = record_mechanical_baseline(snapshot)

        self.assertEqual(result['action'], 'ARM')
        plan = AuctionAnalysis.objects.get().shadow_plan
        self.assertEqual(plan.direction, 'LONG')
        report = build_report()
        self.assertEqual(report['paired_comparison']['mechanical_baseline']['plans'], 1)
        self.assertEqual(report['paired_comparison']['ai']['plans'], 0)



class CandidateGateTest(TestCase):
    candidate = AuctionAnalysisCostAccountingTest.candidate

    @override_settings(AUCTION_AI_PROVIDER='openai', OPENAI_API_KEY='sk-test')
    def test_no_candidate_means_no_api_call(self):
        from l2_agents.auction_service import decide_snapshot
        wait = {**AuctionAnalysisCostAccountingTest.unlisted_arm, 'action': 'WAIT'}
        with patch('l2_agents.auction_service.deterministic_preflight', return_value=wait), \
                patch('l2_agents.auction_service.mechanical_candidate', return_value=None), \
                patch('openai.OpenAI') as openai_cls:
            decision, runtime = decide_snapshot(complete_snapshot(), use_ai=True)

        openai_cls.assert_not_called()
        self.assertEqual(runtime['reason'], 'no_mechanical_candidate')
        self.assertEqual(runtime['analysis_cost']['estimated_usd'], 0.0)

    @override_settings(AUCTION_AI_PROVIDER='openai', OPENAI_API_KEY='sk-test')
    def test_same_candidate_is_paid_for_once_per_window(self):
        from l2_agents.auction_service import decide_snapshot
        AuctionAnalysis.objects.create(
            symbol='XUSDT', snapshot_hash='h', snapshot_version='v', provider='openai',
            action='PASS', direction='NONE', strategy_id='NONE', snapshot={}, shadow_only=True,
            decision={**AuctionAnalysisCostAccountingTest.unlisted_arm, 'action': 'PASS',
                      'direction': 'NONE', 'strategy_id': 'NONE', 'entry_zone': None,
                      'management_policy': 'NONE'},
            runtime={'candidate_key': self.candidate['key'],
                     'analysis_cost': {'estimated_usd': 0.02}})
        wait = {**AuctionAnalysisCostAccountingTest.unlisted_arm, 'action': 'WAIT'}
        with patch('l2_agents.auction_service.deterministic_preflight', return_value=wait), \
                patch('l2_agents.auction_service.mechanical_candidate', return_value=self.candidate), \
                patch('openai.OpenAI') as openai_cls:
            decision, runtime = decide_snapshot(complete_snapshot(), use_ai=True)

        openai_cls.assert_not_called()
        self.assertEqual(decision.action, 'PASS')
        self.assertEqual(runtime['reason'], 'candidate_already_adjudicated')

    def test_arm_must_confirm_the_candidate_unchanged(self):
        changed = AuctionDecision(**{**AuctionAnalysisCostAccountingTest.unlisted_arm,
                                     'entry_zone': [100.0, 101.0], 'direction': 'LONG'})
        with self.assertRaisesRegex(ValueError, 'unchanged'):
            AuctionAdjudicator._validate_against_candidate(changed, self.candidate)
        same = AuctionDecision(**{**AuctionAnalysisCostAccountingTest.unlisted_arm,
                                  'entry_zone': [100.0, 101.0]})
        AuctionAdjudicator._validate_against_candidate(same, self.candidate)

    def test_candidate_is_the_baseline_arm(self):
        from l2_agents.auction_service import mechanical_candidate
        snapshot = {**baseline_snapshot('TREND_UP', 100.5), 'symbol': 'XUSDT'}
        candidate = mechanical_candidate(snapshot)

        self.assertEqual(candidate['direction'], 'LONG')
        self.assertEqual(candidate['entry_zone'], [99.0, 99.0])
        self.assertIsNone(mechanical_candidate({**baseline_snapshot('TRANSITION', 100.0), 'symbol': 'X'}))
