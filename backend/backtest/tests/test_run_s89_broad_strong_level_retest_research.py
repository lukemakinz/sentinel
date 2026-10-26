import unittest

from backtest.run_s89_broad_strong_level_retest_research import _validation_pass


def summary(trades=10, pf=1.2, positive=3, share=49.0):
    return {
        'trades': trades,
        'profit_factor': pf,
        'positive_symbols': positive,
        'largest_symbol_gross_profit_share_pct': share,
    }


class S89ValidationGateTests(unittest.TestCase):
    def test_requires_three_symbols_and_no_half_profit_concentration(self):
        scenarios = {'base': summary(positive=2), 'stress': summary(pf=1.0)}
        self.assertFalse(_validation_pass(scenarios))
        scenarios['base'] = summary(positive=3, share=50.0)
        self.assertTrue(_validation_pass(scenarios))
        scenarios['base']['largest_symbol_gross_profit_share_pct'] = 50.1
        self.assertFalse(_validation_pass(scenarios))


if __name__ == '__main__':
    unittest.main()
