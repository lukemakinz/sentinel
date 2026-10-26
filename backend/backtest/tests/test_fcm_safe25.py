from copy import deepcopy

from django.test import SimpleTestCase

from backtest.fcm_safe25 import evaluate_safe25_gate, safe25_configs


def _summary(net=1.0, episodes=8):
    return {
        'net_pnl': net,
        'episodes': episodes,
        'emergency_closes': 0,
        'unfilled_emergency_closes': 0,
        'modelled_liquidation_breaches': 0,
        'min_exit_ready_futures_equity_usd': 130.0,
        'max_high_mark_leverage': .5,
        'max_mtm_drawdown_pct': 1.0,
        'min_free_cash_after_entry_usd': 24.0,
        'ledger_reconciled': True,
    }


def _passing_inputs():
    replay = {
        'summary': _summary(3.0, 24),
        'episodes': [
            {'symbol': 'ETHUSDT', 'pnl': 1.0},
            {'symbol': 'SOLUSDT', 'pnl': 1.0},
            {'symbol': 'BNBUSDT', 'pnl': 1.0},
        ],
    }
    stress = {
        'development': {'summary': _summary()},
        'validation': {'summary': _summary()},
        'retrospective_evaluation': {'summary': _summary()},
        'all_available': replay,
    }
    results = {
        'stress': stress,
        'severe': {'all_available': {'summary': _summary(.5, 24)}},
    }
    leave_one_out = {
        symbol: {'summary': _summary(.1, 12)}
        for symbol in ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
    }
    return results, leave_one_out


class Safe25Tests(SimpleTestCase):
    def test_frozen_allocations_and_cost_cases(self):
        configs = safe25_configs()
        base = configs['base']
        self.assertEqual(
            base.spot_notional_usd + base.futures_margin_usd + base.reserve_usd,
            250,
        )
        self.assertEqual(base.emergency_futures_equity_floor_usd, 125)
        self.assertEqual(base.emergency_detection_delay_minutes, 1)
        self.assertEqual(dict(base.quantity_steps)['SOLUSDT'], .01)
        self.assertEqual(dict(base.minimum_futures_notionals)['ETHUSDT'], 20)
        self.assertEqual(configs['stress'].costs.round_trip_bps, 50)
        self.assertEqual(configs['severe'].costs.round_trip_bps, 80)
        for config in configs.values():
            config.validate(250)

    def test_every_frozen_gate_can_pass(self):
        results, leave_one_out = _passing_inputs()
        gate = evaluate_safe25_gate(results, leave_one_out)
        self.assertTrue(gate['passed'])
        self.assertEqual(
            gate['decision'], 'HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY')

    def test_negative_newest_stress_rejects_even_if_combined_is_positive(self):
        results, leave_one_out = _passing_inputs()
        results = deepcopy(results)
        results['stress']['retrospective_evaluation']['summary']['net_pnl'] = -.01
        gate = evaluate_safe25_gate(results, leave_one_out)
        self.assertFalse(gate['passed'])
        failed = {row['name'] for row in gate['checks'] if not row['passed']}
        self.assertIn('stress_positive_retrospective_evaluation', failed)

    def test_risk_or_concentration_failure_rejects(self):
        results, leave_one_out = _passing_inputs()
        results = deepcopy(results)
        combined = results['stress']['all_available']
        combined['summary']['min_exit_ready_futures_equity_usd'] = 124.99
        combined['episodes'] = [
            {'symbol': 'SOLUSDT', 'pnl': 9.0},
            {'symbol': 'ETHUSDT', 'pnl': 1.0},
        ]
        gate = evaluate_safe25_gate(results, leave_one_out)
        self.assertFalse(gate['passed'])
        failed = {row['name'] for row in gate['checks'] if not row['passed']}
        self.assertIn('exit_ready_futures_equity_buffer', failed)
        self.assertIn('top_symbol_concentration', failed)
