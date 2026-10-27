import unittest

import numpy as np

from backtest.sharpe_stats import (
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe,
    sharpe_moments,
)


class SharpeStatsTests(unittest.TestCase):
    def test_expected_max_sharpe_matches_published_value(self):
        # Bailey & Lopez de Prado (2014): 1000 trials, unit variance -> ~3.26.
        self.assertAlmostEqual(expected_max_sharpe(1000, 1.0), 3.26, places=2)

    def test_psr_is_half_at_benchmark_and_grows_with_sample(self):
        m = {'sr': 0.1, 't': 100, 'skew': 0.0, 'kurt': 3.0}
        self.assertAlmostEqual(probabilistic_sharpe(m, 0.1), 0.5)
        longer = dict(m, t=1000)
        self.assertGreater(probabilistic_sharpe(longer), probabilistic_sharpe(m))

    def test_more_trials_lower_the_deflated_sharpe(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0.002, 0.01, 365)
        few = deflated_sharpe(returns, trials=2)
        many = deflated_sharpe(returns, trials=133)
        self.assertLess(many['dsr'], few['dsr'])
        self.assertGreater(many['psr_vs_zero'], many['dsr'])

    def test_flat_series_is_handled(self):
        self.assertEqual(sharpe_moments(np.zeros(10))['sr'], 0.0)
