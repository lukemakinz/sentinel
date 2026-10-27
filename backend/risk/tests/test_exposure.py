import numpy as np
from django.test import TestCase

from risk.exposure import (
    ExposureLimits, _leg, beta_from_returns, check_new_trade, portfolio_exposure,
)


class ExposureTests(TestCase):
    def test_beta_estimate_recovers_known_slope(self):
        rng = np.random.default_rng(0)
        btc = rng.normal(0, 0.01, 500)
        alt = 1.4 * btc + rng.normal(0, 0.002, 500)
        self.assertAlmostEqual(beta_from_returns(alt, btc), 1.4, delta=0.05)
        self.assertIsNone(beta_from_returns(alt[:50], btc[:50]))

    def test_three_alt_longs_are_one_big_btc_bet_and_hedges_offset(self):
        longs = [_leg(s, 'LONG', 1.0, 100, 99, 100, 1.2) for s in ('A', 'B', 'C')]
        exposure = portfolio_exposure(longs, equity=250)
        self.assertAlmostEqual(exposure.net_beta_x, 3 * 120 / 250)
        hedge = _leg('BTCUSDT', 'SHORT', 3.6, 100, 101, 100, 1.0)
        self.assertAlmostEqual(portfolio_exposure(longs + [hedge], 250).net_beta_x, 0.0)

    def test_stop_in_profit_carries_no_open_risk(self):
        leg = _leg('A', 'LONG', 2.0, 100, 101, 105, 1.0)
        self.assertEqual(portfolio_exposure([leg], 1000).open_risk_pct, 0.0)

    def test_new_trade_rejected_when_open_risk_would_exceed_limit(self):
        limits = ExposureLimits(max_open_risk_pct=0.5, max_net_beta_x=10, max_gross_x=10)
        existing = [_leg('A', 'LONG', 1.0, 100, 99, 100, 1.0)]   # $1 risk = 0.4% of 250
        small = _leg('B', 'LONG', 0.2, 100, 99, 100, 1.0)          # +0.08%
        large = _leg('B', 'LONG', 1.0, 100, 99, 100, 1.0)          # +0.4%
        self.assertTrue(check_new_trade(existing, small, 250, limits)[0])
        ok, reason, _ = check_new_trade(existing, large, 250, limits)
        self.assertFalse(ok)
        self.assertIn('open risk', reason)
