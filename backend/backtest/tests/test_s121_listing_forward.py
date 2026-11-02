import pandas as pd
from django.test import SimpleTestCase

from backtest import s121_listing_forward as s

NOW = pd.Timestamp('2026-12-31', tz='UTC')


def bars(rows, start='2026-11-05'):
    idx = pd.date_range(start, periods=len(rows), freq='D', tz='UTC')
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=idx)


def funding(points):
    return pd.Series([v for _, v in points], index=pd.to_datetime([t for t, _ in points], utc=True))


EMPTY = pd.Series(dtype=float)


class SimulateGuardedTest(SimpleTestCase):
    def test_pending_until_second_bar(self):
        self.assertEqual(s.simulate_guarded(bars([(1, 1, 1, 1)]), EMPTY, NOW)['status'], 'PENDING')

    def test_entry_guard_skips_crowded_short(self):
        f = funding([('2026-11-05 08:00', -0.0008), ('2026-11-05 16:00', -0.0005)])
        r = s.simulate_guarded(bars([(10, 10, 10, 10)] * 3), f, NOW)
        self.assertEqual((r['status'], r['reason']), ('SKIPPED', 'entry_guard_day1_funding'))

    def test_funding_exit(self):
        f = funding([('2026-11-06 08:00', -0.02), ('2026-11-07 08:00', -0.015)])
        r = s.simulate_guarded(bars([(10, 10, 10, 10), (10, 10.5, 9.5, 10), (10, 10.5, 9.5, 9.8),
                                     (9.8, 10, 9, 9)]), f, NOW)
        self.assertEqual((r['status'], r['reason']), ('CLOSED', 'FUNDING_EXIT'))
        self.assertAlmostEqual(r['funding'], -0.035)

    def test_stop_and_time_exit(self):
        stopped = s.simulate_guarded(bars([(10, 10, 10, 10), (10, 14, 9, 13)]), EMPTY, NOW)
        self.assertEqual(stopped['reason'], 'STOP')
        self.assertEqual(stopped['raw_exit'], 13.5)
        rows = [(10, 10, 10, 10)] + [(10, 10.2, 9, 9)] * 14
        timed = s.simulate_guarded(bars(rows), EMPTY, NOW)
        self.assertEqual(timed['reason'], 'TIME')
        self.assertGreater(timed['net'], 0)

    def test_open_position_is_marked(self):
        r = s.simulate_guarded(bars([(10, 10, 10, 10), (10, 10.5, 9, 9.5)]), EMPTY, NOW)
        self.assertEqual(r['status'], 'OPEN')
        self.assertGreater(r['unrealized_net'], 0)

    def test_concurrency_cap(self):
        t0 = pd.Timestamp('2026-11-10', tz='UTC')
        trades = [{'status': 'OPEN', 'entry_time': t0 + pd.Timedelta(days=i), 'exit_time': None}
                  for i in range(7)]
        result = s.apply_concurrency(trades)
        self.assertEqual(sum(t['status'] == 'SKIPPED' for t in result), 2)
