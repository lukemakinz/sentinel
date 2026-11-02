from backtest.run_s120_s20_entry_lab_v1 import (
    ENTRY_POLICIES,
    _eligible,
    _passes_oos,
    _select,
)
from django.test import SimpleTestCase


def _summary(trades=50, pnl=1.0, pf=1.2, mean_r=0.05):
    return {
        'trades': trades,
        'net_pnl': pnl,
        'profit_factor': pf,
        'mean_net_r': mean_r,
    }


class S120SelectionTests(SimpleTestCase):
    def test_train_selection_chooses_cash_when_no_policy_passes_every_gate(self):
        rows = {policy: _summary(pnl=-1.0) for policy in ENTRY_POLICIES}
        self.assertEqual(_select(rows), 'CASH')

    def test_train_selection_uses_mean_r_only_after_eligibility(self):
        rows = {policy: _summary() for policy in ENTRY_POLICIES}
        rows['MSS_BREAK'] = _summary(mean_r=0.10, pf=1.10)
        rows['MSS_RETEST'] = _summary(trades=20, mean_r=0.50, pf=3.0)
        self.assertEqual(_select(rows), 'MSS_BREAK')

    def test_oos_gate_requires_both_fold_pnls_and_corrected_bootstrap_lower(self):
        row = {
            **_summary(),
            'test_fold_pnl': [0.5, 0.5],
            'bootstrap_day_lower_98_75_pct': 0.01,
        }
        self.assertTrue(_eligible(row))
        self.assertTrue(_passes_oos(row))
        row['test_fold_pnl'][1] = -0.01
        self.assertFalse(_passes_oos(row))
