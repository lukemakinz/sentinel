from dataclasses import replace

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from backtest.funding_carry_v2 import (
    FCMConfig,
    FCMCosts,
    monthly_fcm_targets,
    simulate_fcm,
)


UTC = 'UTC'


def price_frame(index, values):
    values = np.asarray(values, dtype=float)
    return pd.DataFrame({
        'open': values,
        'high': values,
        'low': values,
        'close': values,
    }, index=index)


def rate_series(rows):
    return pd.Series(
        [value for _timestamp, value in rows],
        index=pd.DatetimeIndex([timestamp for timestamp, _value in rows], tz=UTC),
        dtype=float,
    )


class FundingCarryV2Tests(SimpleTestCase):
    def setUp(self):
        self.config = FCMConfig(
            return_lookback_days=5,
            ema_span_days=10,
            qualification_funding_bps=50,
        )

    def test_selection_requires_funding_return_and_ema_filters(self):
        index = pd.date_range('2026-01-01', '2026-03-02', freq='1D', tz=UTC)
        rising = price_frame(index, np.linspace(80, 120, len(index)))
        falling = price_frame(index, np.linspace(120, 80, len(index)))
        rates = {
            'ETH': rate_series([('2026-02-15', .006), ('2026-03-01', -.9)]),
            'SOL': rate_series([('2026-02-15', .009), ('2026-03-01', .9)]),
        }
        target = monthly_fcm_targets(
            {'ETH': rising, 'SOL': falling}, rates,
            '2026-03-01', '2026-04-01', self.config,
        )[0]
        self.assertEqual(target['target'], 'ETH')
        self.assertTrue(target['features']['ETH']['qualified'])
        self.assertFalse(target['features']['SOL']['qualified'])
        self.assertAlmostEqual(
            target['features']['ETH']['prior_month_funding_bps'], 60.0)

    def test_full_two_leg_ledger_exposes_basis_pnl(self):
        index = pd.date_range('2025-12-01', '2026-03-02', freq='1h', tz=UTC)
        spot_values = np.linspace(80, 100, len(index))
        entry = pd.Timestamp('2026-02-01 01:00', tz=UTC)
        exit_time = pd.Timestamp('2026-03-01 00:00', tz=UTC)
        spot_values[index >= entry] = 100.0
        spot_values[index >= exit_time] = 110.0
        spot = price_frame(index, spot_values)
        perpetual = price_frame(index, np.full(len(index), 101.0))
        perpetual.loc[index >= exit_time, :] = 109.0
        mark = price_frame(index, np.full(len(index), 101.0))
        mark.loc[pd.Timestamp('2026-02-15 00:00', tz=UTC), :] = 105.0
        rates = rate_series([
            ('2026-01-15 00:00', .006),
            ('2026-02-15 00:00', .001),
        ])
        config = replace(self.config, costs=FCMCosts(0, 0, 0, 0))
        result = simulate_fcm(
            {'ETH': spot}, {'ETH': perpetual}, {'ETH': mark}, {'ETH': rates},
            '2026-02-01', '2026-03-01', config,
        )
        episode = result['episodes'][0]
        self.assertAlmostEqual(episode['spot_pnl_after_slippage'], 10.0)
        self.assertAlmostEqual(episode['futures_pnl_after_slippage'], -8.0)
        self.assertAlmostEqual(episode['price_basis_pnl_before_costs'], 2.0)
        self.assertAlmostEqual(episode['funding_pnl'], .105)
        self.assertAlmostEqual(result['summary']['net_pnl'], 2.105)
        self.assertTrue(result['summary']['ledger_reconciled'])
        kinds = {row['kind'] for row in result['ledger']}
        self.assertTrue({
            'spot_purchase', 'spot_sale', 'futures_margin_lock',
            'futures_margin_release', 'futures_variation_pnl', 'funding',
        }.issubset(kinds))

    def test_stress_round_trip_is_fifty_bps(self):
        costs = FCMCosts(spot_fee_bps=10, futures_fee_bps=5,
                         spot_slippage_bps=5, futures_slippage_bps=5)
        self.assertEqual(costs.round_trip_bps, 50)

    def test_zero_decision_delay_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'lookahead'):
            replace(self.config, decision_delay_hours=0).validate(250)

    def test_monthly_reset_closes_and_reopens_same_selected_asset(self):
        index = pd.date_range('2025-12-01', '2026-04-02', freq='1h', tz=UTC)
        values = np.linspace(80, 120, len(index))
        spot = price_frame(index, values)
        perpetual = price_frame(index, values * 1.001)
        mark = perpetual.copy()
        rates = rate_series([
            ('2026-01-15', .006),
            ('2026-02-15', .006),
            ('2026-03-15', .001),
        ])
        config = replace(
            self.config, force_monthly_reset=True,
            spot_notional_usd=50, futures_margin_usd=190,
            reserve_usd=10, max_initial_futures_leverage=.30,
            costs=FCMCosts(0, 0, 0, 0),
        )
        result = simulate_fcm(
            {'ETH': spot}, {'ETH': perpetual}, {'ETH': mark}, {'ETH': rates},
            '2026-02-01', '2026-04-01', config,
        )
        self.assertEqual(result['summary']['episodes'], 2)
        self.assertEqual(result['episodes'][0]['closed_at'],
                         pd.Timestamp('2026-03-01 01:00', tz=UTC))
        self.assertEqual(result['episodes'][1]['opened_at'],
                         pd.Timestamp('2026-03-01 01:00', tz=UTC))

    def test_sub_one_futures_leverage_cap_is_valid(self):
        replace(self.config, max_initial_futures_leverage=.30).validate(250)

    def test_emergency_uses_minute_high_and_next_real_open(self):
        hourly_index = pd.date_range(
            '2025-12-01', '2026-03-02', freq='1h', tz=UTC)
        rising = price_frame(
            hourly_index, np.linspace(80, 100, len(hourly_index)))
        perpetual = price_frame(hourly_index, np.full(len(hourly_index), 100.0))
        mark = perpetual.copy()
        minute_index = pd.date_range(
            '2026-02-01 01:00', '2026-03-01 00:00',
            freq='1min', inclusive='left', tz=UTC)
        minute_spot = price_frame(minute_index, np.full(len(minute_index), 100.0))
        minute_perpetual = minute_spot.copy()
        minute_mark = minute_spot.copy()
        breach_bar = pd.Timestamp('2026-02-10 00:00', tz=UTC)
        minute_mark.at[breach_bar, 'high'] = 500.0
        rates = rate_series([
            ('2026-01-15', .006),
            # This large positive receipt must not conceal a safety breach.
            ('2026-02-10', 1.0),
        ])
        config = replace(
            self.config,
            spot_notional_usd=25,
            futures_margin_usd=200,
            reserve_usd=25,
            max_initial_futures_leverage=.15,
            emergency_futures_equity_floor_usd=125,
            emergency_max_mark_leverage=.75,
            emergency_detection_delay_minutes=1,
            costs=FCMCosts(0, 0, 0, 0),
        )
        result = simulate_fcm(
            {'ETH': rising}, {'ETH': perpetual}, {'ETH': mark}, {'ETH': rates},
            '2026-02-01', '2026-03-01', config,
            emergency_spot_prices={'ETH': minute_spot},
            emergency_perpetual_prices={'ETH': minute_perpetual},
            emergency_mark_prices={'ETH': minute_mark},
        )
        episode = result['episodes'][0]
        self.assertEqual(
            episode['closed_at'], breach_bar + pd.Timedelta(minutes=1))
        self.assertTrue(episode['close_reason'].startswith('emergency_'))
        self.assertEqual(result['summary']['emergency_closes'], 1)
        self.assertLess(episode['min_exit_ready_futures_equity_usd'], 125)
        # Hourly opens were flat, so an open-only audit would miss the squeeze.
        self.assertGreater(episode['min_futures_equity_usd'], 199)

    def test_both_legs_use_same_quantity_rounded_down_to_futures_step(self):
        index = pd.date_range('2025-12-01', '2026-03-02', freq='1h', tz=UTC)
        values = np.linspace(80, 100, len(index))
        entry = pd.Timestamp('2026-02-01 01:00', tz=UTC)
        values[index >= entry] = 100.0
        spot = price_frame(index, values)
        perpetual = price_frame(index, np.full(len(index), 100.0))
        rates = rate_series([('2026-01-15', .006)])
        config = replace(
            self.config,
            spot_notional_usd=25,
            futures_margin_usd=200,
            reserve_usd=25,
            max_initial_futures_leverage=.15,
            quantity_steps=(('ETH', .1),),
            minimum_futures_notionals=(('ETH', 20.0),),
            costs=FCMCosts(0, 0, 0, 0),
        )
        result = simulate_fcm(
            {'ETH': spot}, {'ETH': perpetual}, {'ETH': perpetual}, {'ETH': rates},
            '2026-02-01', '2026-03-01', config,
        )
        episode = result['episodes'][0]
        self.assertAlmostEqual(episode['raw_quantity_before_lot_rounding'], .25)
        self.assertAlmostEqual(episode['quantity'], .2)
        self.assertAlmostEqual(episode['initial_futures_notional'], 20.0)
        self.assertAlmostEqual(episode['unused_spot_notional_after_rounding'], 5.0)
