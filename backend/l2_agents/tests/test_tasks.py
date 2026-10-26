from unittest.mock import patch

from django.test import TestCase, override_settings

from l2_agents.tasks import run_l2_analysis


CONTEXT = {
    'symbol': 'ETHUSDT', 'direction': 'LONG', 'strategy': 'S12AI',
    'shadow_only': True,
}
PARAMS = {
    'symbol': 'ETHUSDT', 'entry_price': 100.0, 'stop_loss': 99.0,
    'take_profits': [{'level': 101.0, 'ratio': 1.0}], 'r_value': 1.0,
}


class L2TaskShadowTests(TestCase):
    @patch('evaluator.tracker.create_signal')
    @patch('executor.l3_calculator.L3Calculator.calculate', return_value=PARAMS)
    @patch('l2_agents.orchestrator.L2Orchestrator.run', return_value={
        'action': 'REJECT', 'size_multiplier': 0.0,
        'veto_reason': 'conservative_ai_quorum', 'agents_summary': {},
    })
    def test_rejected_candidate_gets_same_counterfactual_geometry(
            self, _run, calculate, create_signal):
        result = run_l2_analysis.run(CONTEXT)
        self.assertEqual(result['action'], 'REJECT')
        geometry_decision = calculate.call_args.args[1]
        self.assertEqual(geometry_decision['action'], 'APPROVE')
        create_signal.assert_called_once_with(
            CONTEXT, result, trade_params=PARAMS, executed=False)

    @patch('evaluator.tracker.create_signal')
    @patch('executor.l3_calculator.L3Calculator.calculate', return_value=PARAMS)
    @patch('l2_agents.orchestrator.L2Orchestrator.run', return_value={
        'action': 'APPROVE', 'size_multiplier': 0.5, 'agents_summary': {},
    })
    def test_shadow_approval_calculates_but_does_not_publish_executable_params(
            self, _run, calculate, create_signal):
        result = run_l2_analysis.run(CONTEXT)
        self.assertEqual(result['action'], 'APPROVE')
        calculate.assert_called_once()
        create_signal.assert_called_once_with(
            CONTEXT, result, trade_params=PARAMS, executed=False)


class AuctionShadowCycleCostTests(TestCase):
    @override_settings(AUCTION_SHADOW_ENABLED=True, AUCTION_SHADOW_AI_ENABLED=False)
    @patch('ingester.models.WatchedPair.get_active_symbols', return_value=['BTCUSDT'])
    def test_cycle_reports_cost_last(self, _symbols):
        from l2_agents.tasks import run_auction_shadow_cycle
        results = run_auction_shadow_cycle()

        self.assertEqual(results['created'], 1)
        self.assertEqual(list(results)[-1], 'analysis_cost')
        self.assertEqual(results['analysis_cost']['estimated_usd_known'], 0.0)
