"""Manual position creation and live monitoring logic."""
from django.test import TestCase
from executor.views import compute_liquidation_price, compute_live_pnl


class LiquidationPriceTest(TestCase):
    def test_long_liq_below_entry(self):
        liq = compute_liquidation_price('LONG', 93250.0, 10)
        # entry × (1 - 1/lev + 0.005) = 93250 × 0.905 = 84391.25
        self.assertAlmostEqual(liq, 84391.25, places=0)
        self.assertLess(liq, 93250.0)

    def test_short_liq_above_entry(self):
        liq = compute_liquidation_price('SHORT', 93250.0, 10)
        # entry × (1 + 1/lev - 0.005) = 93250 × 1.095 = 102108.75
        self.assertAlmostEqual(liq, 102108.75, places=0)
        self.assertGreater(liq, 93250.0)

    def test_1x_leverage_long_liq_very_low(self):
        liq = compute_liquidation_price('LONG', 1000.0, 1)
        self.assertLess(liq, 10.0)   # near zero — can't be liquidated easily

    def test_higher_leverage_liq_closer_to_entry(self):
        liq_10x = compute_liquidation_price('LONG', 1000.0, 10)
        liq_20x = compute_liquidation_price('LONG', 1000.0, 20)
        self.assertGreater(liq_20x, liq_10x)  # 20× closer to entry


class LivePnLTest(TestCase):
    def test_long_profitable(self):
        pnl = compute_live_pnl('LONG', 93250.0, 94000.0, 0.05, 500.0)
        # (94000 - 93250) × 0.05 = 750 × 0.05 = 37.5
        self.assertAlmostEqual(pnl['pnl_usd'], 37.5, places=1)
        self.assertGreater(pnl['pnl_pct_margin'], 0)

    def test_long_losing(self):
        pnl = compute_live_pnl('LONG', 93250.0, 92500.0, 0.05, 500.0)
        self.assertLess(pnl['pnl_usd'], 0)
        self.assertLess(pnl['pnl_pct_margin'], 0)

    def test_short_profitable(self):
        pnl = compute_live_pnl('SHORT', 3200.0, 3100.0, 1.0, 500.0)
        # (3200 - 3100) × 1.0 = 100
        self.assertAlmostEqual(pnl['pnl_usd'], 100.0, places=1)

    def test_pnl_contains_required_fields(self):
        pnl = compute_live_pnl('LONG', 93250.0, 94000.0, 0.05, 500.0)
        for field in ('pnl_usd', 'pnl_pct_margin', 'sl_progress_pct', 'liq_distance_pct'):
            self.assertIn(field, pnl)

    def test_sl_progress_between_0_and_100_when_in_profit(self):
        # Entry 93250, TP1 94525 (1.5R where R=850), current 93820
        pnl = compute_live_pnl('LONG', 93250.0, 93820.0, 0.05, 500.0,
                                stop_loss=92400.0, take_profit_1=94525.0)
        self.assertGreater(pnl['sl_progress_pct'], 0)
        self.assertLess(pnl['sl_progress_pct'], 100)
