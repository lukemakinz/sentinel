from dataclasses import replace

import pandas as pd
from django.test import SimpleTestCase

from backtest.funding_carry import (
    FundingCarryConfig,
    FundingCarryCosts,
    decide_target,
    monthly_targets,
    simulate_monthly_carry,
)


UTC = 'UTC'


def rate_series(rows):
    return pd.Series(
        [value for _timestamp, value in rows],
        index=pd.DatetimeIndex([timestamp for timestamp, _value in rows], tz=UTC),
        dtype=float,
    )


class FundingCarryTests(SimpleTestCase):
    def test_monthly_choice_uses_only_completed_previous_month(self):
        rates = {
            'ETH': rate_series([('2026-01-15', .002), ('2026-02-15', -.500)]),
            'BNB': rate_series([('2026-01-15', .0005), ('2026-02-15', .500)]),
        }
        target = monthly_targets(
            rates, '2026-02-01', '2026-03-01', FundingCarryConfig())[0]
        self.assertEqual(target['target'], 'ETH')
        self.assertEqual(target['previous_month_scores_bps'], {'ETH': 20.0, 'BNB': 5.0})

    def test_switch_hysteresis_covers_round_trip_cost(self):
        rates = {
            'ETH': rate_series([('2026-01-15', .002), ('2026-02-15', .0015)]),
            'BNB': rate_series([('2026-01-15', .001), ('2026-02-15', .0040)]),
        }
        schedule = monthly_targets(
            rates, '2026-02-01', '2026-04-01', FundingCarryConfig())
        self.assertEqual([row['target'] for row in schedule], ['ETH', 'ETH'])
        cheaper = replace(FundingCarryConfig(), switch_hurdle_bps=20.0,
                          costs=FundingCarryCosts(5, 2, 1, 1))
        schedule = monthly_targets(rates, '2026-02-01', '2026-04-01', cheaper)
        self.assertEqual([row['target'] for row in schedule], ['ETH', 'BNB'])

    def test_equal_quantity_hedge_books_funding_and_both_leg_costs(self):
        index = pd.DatetimeIndex([
            '2026-02-01 00:01', '2026-02-15 00:00', '2026-03-01 00:00'], tz=UTC)
        frame = pd.DataFrame({'open': [100.0, 100.0, 100.0],
                              'high': [100.0, 100.0, 100.0]}, index=index)
        rates = {'ETH': rate_series([
            ('2026-01-15', .002),
            ('2026-02-15', .001),
        ])}
        result = simulate_monthly_carry(
            {'ETH': frame}, rates, '2026-02-01', '2026-03-01',
            FundingCarryConfig(), initial_capital=250)
        summary = result['summary']
        self.assertAlmostEqual(summary['gross_funding_pnl'], .1)
        self.assertAlmostEqual(summary['costs'], .28)
        self.assertAlmostEqual(summary['net_pnl'], -.18)
        self.assertEqual(summary['funding_settlements'], 1)

    def test_rejects_more_than_one_x_futures_leg(self):
        config = FundingCarryConfig(notional_usd=101, futures_margin_usd=100)
        with self.assertRaisesMessage(ValueError, '1x'):
            config.validate(250)

    def test_decide_target_is_the_single_source_of_truth_for_the_live_monitor(self):
        config = FundingCarryConfig()
        # No position yet, leader clears the entry threshold.
        self.assertEqual(decide_target(None, {'ETH': 20.0, 'BNB': 5.0}, config),
                         ('ETH', 'enter_leader'))
        # No position, nobody clears the entry threshold.
        self.assertEqual(decide_target(None, {'ETH': 5.0}, config), (None, 'hold_cash'))
        # Held symbol's own score turned non-positive; a qualifying leader replaces it.
        self.assertEqual(decide_target('ETH', {'ETH': -1.0, 'BNB': 15.0}, config),
                         ('BNB', 'replace_nonpositive'))
        # Held symbol's score non-positive, nothing else qualifies either.
        self.assertEqual(decide_target('ETH', {'ETH': -1.0, 'BNB': 5.0}, config),
                         (None, 'exit_nonpositive'))
        # Held symbol still positive; leader change too small to cover the switch hurdle.
        self.assertEqual(decide_target('ETH', {'ETH': 15.0, 'BNB': 20.0}, config),
                         ('ETH', 'hold_position'))
        # Held symbol still positive; leader change clears the switch hurdle.
        self.assertEqual(decide_target('ETH', {'ETH': 15.0, 'BNB': 50.0}, config),
                         ('BNB', 'switch_after_cost_hurdle'))
