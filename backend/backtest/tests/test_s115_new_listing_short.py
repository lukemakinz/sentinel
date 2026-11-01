import pandas as pd
from django.test import SimpleTestCase

from backtest.run_s115_new_listing_short import max_concurrency, simulate_short


def bars(rows):
    index = pd.date_range('2025-01-01', periods=len(rows), freq='D', tz='UTC')
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=index)


NO_FUNDING = pd.Series(dtype=float)


class SimulateShortTest(SimpleTestCase):
    def test_time_exit_profit_with_costs(self):
        b = bars([(10, 11, 9, 10), (10, 10.5, 9, 9), (9, 9.5, 8, 8), (8, 8.5, 7, 7)])
        t = simulate_short(b, NO_FUNDING, entry_index=1, hold_days=3, stop_pct=0.35,
                           slippage_bps=0, fee_bps=0)
        self.assertEqual(t['reason'], 'TIME')
        self.assertAlmostEqual(t['gross'], 0.3)
        costed = simulate_short(b, NO_FUNDING, entry_index=1, hold_days=3, stop_pct=0.35,
                                slippage_bps=30, fee_bps=5)
        self.assertLess(costed['net'], t['net'])

    def test_stop_and_gap_fill_at_worse_open(self):
        b = bars([(10, 10, 10, 10), (10, 12, 9, 11), (15, 16, 14, 15)])
        t = simulate_short(b, NO_FUNDING, entry_index=1, hold_days=5, stop_pct=0.35,
                           slippage_bps=0, fee_bps=0)
        self.assertEqual(t['reason'], 'STOP')
        self.assertEqual(t['raw_exit'], 15)  # gapped above the 13.5 stop
        self.assertAlmostEqual(t['net'], -0.5)

    def test_funding_sign_and_window(self):
        b = bars([(10, 10, 10, 10)] * 4)
        funding = pd.Series([0.001, -0.004, 0.002], index=pd.to_datetime(
            ['2025-01-01 08:00', '2025-01-02 08:00', '2025-01-05 08:00'], utc=True))
        t = simulate_short(b, funding, entry_index=1, hold_days=2, stop_pct=0.35,
                           slippage_bps=0, fee_bps=0)
        # Only the 2025-01-02 settlement lies inside [entry, exit): short pays it.
        self.assertAlmostEqual(t['funding'], -0.004)
        self.assertAlmostEqual(t['net'], -0.004)

    def test_data_end_exits_at_last_close(self):
        b = bars([(10, 10, 10, 10), (10, 10, 8, 8)])
        t = simulate_short(b, NO_FUNDING, entry_index=1, hold_days=14, stop_pct=0.35,
                           slippage_bps=0, fee_bps=0)
        self.assertEqual(t['reason'], 'DATA_END')
        self.assertAlmostEqual(t['gross'], 0.2)

    def test_not_enough_bars(self):
        self.assertIsNone(simulate_short(bars([(1, 1, 1, 1)]), NO_FUNDING, entry_index=1,
                                         hold_days=3, stop_pct=0.3, slippage_bps=0))

    def test_concurrency(self):
        t = pd.to_datetime(['2025-01-01', '2025-01-05', '2025-01-02', '2025-01-03',
                            '2025-01-04', '2025-01-06'], utc=True)
        df = pd.DataFrame({'entry_time': t[[0, 2, 4]], 'exit_time': t[[1, 3, 5]]})
        self.assertEqual(max_concurrency(df), 2)
