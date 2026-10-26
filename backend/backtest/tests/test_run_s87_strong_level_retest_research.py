import unittest

from backtest.run_s87_strong_level_retest_research import (
    _development_pass,
    _validation_pass,
)


def summary(trades=20, pf=1.2, pnl=1.0, positive=2, share=50.0):
    return {
        'trades': trades,
        'profit_factor': pf,
        'net_pnl': pnl,
        'positive_symbols': positive,
        'largest_symbol_gross_profit_share_pct': share,
    }


class S87ResearchGateTests(unittest.TestCase):
    def test_development_requires_stress_survival(self):
        scenarios = {'base': summary(), 'stress': summary(pf=0.94)}
        self.assertFalse(_development_pass(scenarios))
        scenarios['stress'] = summary(pf=0.95)
        self.assertTrue(_development_pass(scenarios))

    def test_validation_rejects_single_symbol_concentration(self):
        scenarios = {
            'base': summary(trades=10, pf=1.15, positive=2, share=66.0),
            'stress': summary(trades=10, pf=1.00),
        }
        self.assertFalse(_validation_pass(scenarios))
        scenarios['base']['largest_symbol_gross_profit_share_pct'] = 65.0
        self.assertTrue(_validation_pass(scenarios))


if __name__ == '__main__':
    unittest.main()
