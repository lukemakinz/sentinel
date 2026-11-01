from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from l2_agents.strategies.h3b_trend_double_bottom import (
    STRATEGY_PLUGIN, detect, pivots, rsi, trend_4h,
)

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def rows_from(closes, step_hours=1, spikes=None):
    spikes = spikes or {}
    out = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        out.append({'timestamp': T0 + timedelta(hours=step_hours * i), 'open': prev,
                    'high': max(prev, c) + 0.3, 'low': spikes.get(i, min(prev, c) - 0.3),
                    'close': c, 'volume': 1.0})
    return out


def uptrend_4h(n=80):
    return rows_from([100 + i * 0.5 for i in range(n)], step_hours=4)


def double_bottom_closes(break_now=True):
    closes = [100 + 0.05 * i for i in range(100)]             # warm-up, ~105
    closes += [105 - 0.5 * i for i in range(1, 9)]            # sharp drop to 101 (low RSI)
    closes += [101 + 0.3 * i for i in range(1, 9)]            # rally to 103.4 (neckline ~103.7)
    closes += [103.4 - 0.15 * i for i in range(1, 17)]        # slow drop to 101 (higher RSI)
    closes += [101 + 0.25 * i for i in range(1, 10)]          # recovery to 103.25, below neckline
    closes += [104.2 if break_now else 103.3]                 # first close above the neckline
    return closes


class H3BDetectTest(SimpleTestCase):
    def test_detects_with_trend_double_bottom_with_divergence(self):
        closes = double_bottom_closes()
        setup = detect(rows_from(closes), uptrend_4h())
        self.assertIsNotNone(setup)
        self.assertEqual(setup['direction'], 'LONG')
        self.assertLess(setup['stop'], 101 - 0.3)
        self.assertGreater(setup['divergence'], 2)
        self.assertTrue(1.0 <= setup['risk_pct'] <= 6.0)

    def test_counter_trend_is_ignored(self):
        downtrend = rows_from([140 - i * 0.5 for i in range(80)], step_hours=4)
        self.assertIsNone(detect(rows_from(double_bottom_closes()), downtrend))

    def test_no_signal_without_break_or_on_second_close_above(self):
        self.assertIsNone(detect(rows_from(double_bottom_closes(break_now=False)), uptrend_4h()))
        closes = double_bottom_closes() + [103.0]  # second bar above the neckline
        self.assertIsNone(detect(rows_from(closes), uptrend_4h()))

    def test_causal_signal_depends_only_on_closed_bars(self):
        closes = double_bottom_closes()
        rows = rows_from(closes)
        # Signal on bar N is unaffected by any later bar (none is supplied).
        self.assertEqual(detect(rows, uptrend_4h()), detect(list(rows), uptrend_4h()))
        # And the bar before the break gives no signal.
        self.assertIsNone(detect(rows[:-1], uptrend_4h()))


class H3BHelpersTest(SimpleTestCase):
    def test_pivots_exclude_unconfirmed_tail(self):
        values = [5, 4, 3, 1, 3, 4, 5, 6, 0]
        self.assertEqual(pivots(values, 'low'), [3])

    def test_rsi_bounds_and_trend(self):
        r = rsi([float(i) for i in range(1, 40)])
        self.assertEqual(r[-1], 100.0)
        self.assertEqual(trend_4h(uptrend_4h()), 'UP')


class H3BPluginTest(SimpleTestCase):
    def test_scan_emits_candidate_with_plugin_geometry(self):
        snapshot = {'data_quality': {'tradable': True},
                    'recent_bars': {'1h': rows_from(double_bottom_closes()), '4h': uptrend_4h()}}
        scan = STRATEGY_PLUGIN.scan(snapshot)
        self.assertEqual(len(scan.candidates), 1)
        cand = scan.candidates[0]
        self.assertEqual(cand.target_r, 2.0)
        self.assertEqual(cand.max_hold_minutes, 72 * 60)
        self.assertLess(cand.stop_price, cand.entry_zone[0])

    def test_live_snapshot_without_bars_is_safe(self):
        scan = STRATEGY_PLUGIN.scan({'data_quality': {'tradable': True}})
        self.assertEqual(scan.candidates, ())

    def test_research_plugin_is_not_enabled_for_live(self):
        from l2_agents.strategies import strategy_registry
        self.assertIn('H3B_TREND_DOUBLE_BOTTOM_V1', strategy_registry.ids())
        self.assertNotIn('H3B_TREND_DOUBLE_BOTTOM_V1', strategy_registry.enabled_ids())
