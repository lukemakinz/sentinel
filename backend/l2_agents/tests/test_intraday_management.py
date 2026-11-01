from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from l2_agents.intraday_management import (
    P1_POLICY,
    P2_POLICY,
    simulate_intraday_policy,
)


COSTS = {
    'entry_taker_fee_bps': 5,
    'target_maker_fee_bps': 2,
    'stop_taker_fee_bps': 5,
    'market_slippage_bps': 5,
}
START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def row(minute, opened, high, low, close):
    return {
        'timestamp': START + timedelta(minutes=minute),
        'open': opened, 'high': high, 'low': low, 'close': close,
    }


class IntradayManagementTest(SimpleTestCase):
    def test_p1_scales_at_075r_and_protects_remaining_position(self):
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=[
                row(1, 100, 100.8, 99.8, 100.7),
                row(2, 100.7, 100.8, 100.0, 100.1),
            ],
            costs=COSTS, policy_id=P1_POLICY, opened_at=START,
        )

        self.assertTrue(result['complete'])
        self.assertTrue(result['tp1_hit'])
        self.assertEqual(result['partials'][0]['label'], 'TP1')
        self.assertEqual(result['partials'][0]['fraction'], 0.5)
        self.assertEqual(result['exit_reason'], 'PROTECTED_STOP')
        self.assertGreater(result['net_r'], 0)
        self.assertIn('TP1_COST_BE', result['stop_moves'][0]['reason'])

    def test_p2_cuts_open_risk_after_half_r_on_the_next_bar(self):
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=[
                row(1, 100, 100.6, 99.8, 100.5),
                row(2, 100.5, 100.55, 99.4, 99.5),
            ],
            costs=COSTS, policy_id=P2_POLICY, opened_at=START,
        )

        self.assertFalse(result['tp1_hit'])
        self.assertEqual(result['exit_reason'], 'STOP')
        self.assertGreater(result['gross_r'], -0.6)
        self.assertEqual(result['stop_moves'][0]['reason'], 'MFE_0_5R_RISK_CUT')

    def test_p2_takes_two_partials_and_trails_runner(self):
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=[
                row(1, 100, 101.3, 99.8, 101.2),
                row(2, 101.2, 101.4, 100.7, 100.8),
            ],
            costs=COSTS, policy_id=P2_POLICY, opened_at=START,
        )

        self.assertTrue(result['tp1_hit'])
        self.assertTrue(result['tp2_hit'])
        self.assertEqual([event['label'] for event in result['partials'][:2]], ['TP1', 'TP2'])
        self.assertEqual(result['exit_reason'], 'TRAILING_STOP')
        self.assertGreater(result['net_r'], 0)

    def test_stop_first_prevents_optimistic_same_bar_partial(self):
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=[row(1, 100, 101.5, 98.8, 100.5)],
            costs=COSTS, policy_id=P2_POLICY, opened_at=START,
        )

        self.assertEqual(result['exit_reason'], 'STOP')
        self.assertFalse(result['tp1_hit'])
        self.assertEqual(len(result['partials']), 1)

    def test_policy_flattens_when_candle_closes_beyond_new_protective_stop(self):
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=[row(1, 100, 100.8, 99.8, 100.0)],
            costs=COSTS, policy_id=P1_POLICY, opened_at=START,
        )

        self.assertTrue(result['tp1_hit'])
        self.assertEqual(
            result['exit_reason'],
            'TP1_COST_BE_OR_1M_STRUCTURE_MARKET_CLOSE',
        )

    def test_position_is_flattened_before_crossing_utc_day(self):
        opened = datetime(2026, 1, 1, 23, 58, tzinfo=timezone.utc)
        rows = [
            {**row(0, 100, 100.2, 99.8, 100.1), 'timestamp': opened + timedelta(minutes=1)},
            {**row(0, 100.1, 100.3, 100.0, 100.2), 'timestamp': opened + timedelta(minutes=2)},
        ]
        result = simulate_intraday_policy(
            direction='LONG', entry=100, initial_stop=99,
            rows=rows, costs=COSTS, policy_id=P1_POLICY, opened_at=opened,
        )

        self.assertEqual(result['exit_reason'], 'EOD_FLAT')
        self.assertTrue(result['flattened_at_utc_day_end'])
