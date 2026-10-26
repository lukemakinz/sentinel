from dataclasses import replace
import unittest

import pandas as pd

from backtest.sweep_reclaim_orders import (
    materialize_sweep_reclaims,
    stress_target_price,
)
from l1_filter.fresh_level_sweep_reclaim import FreshLevelSweepReclaimConfig


def _minutes(periods=240):
    index = pd.date_range('2026-01-01', periods=periods, freq='1min', tz='UTC')
    return pd.DataFrame({
        'open': 105.0, 'high': 105.1, 'low': 104.9, 'close': 105.0,
        'volume': 10.0, 'taker_buy_volume': 5.0,
    }, index=index)


def _level(minutes, setup_id='level', side=1, created_minute=60):
    created = minutes.index[created_minute]
    return {
        'timestamp': created,
        'created_at': created,
        'ob_close_time': minutes.index[0],
        'side': side,
        'reference': 105.0,
        'atr': 2.0,
        'score': 90.0,
        'setup': 'test',
        'setup_id': setup_id,
        'order_block': [100.0, 101.0],
        'limit_ttl_minutes': 120,
        'target_boundary': None,
        'evidence': {},
    }


def _add_long_departure(frame):
    frame.loc[frame.index[1]:frame.index[59], ['open', 'high', 'low', 'close']] = [102.0, 103.0, 101.5, 102.5]


class SweepReclaimOrderTests(unittest.TestCase):
    def test_premitigated_level_never_becomes_fresh(self):
        frame = _minutes()
        _add_long_departure(frame)
        frame.loc[frame.index[30], ['open', 'high', 'low', 'close']] = [102, 102, 100.5, 101]
        signals, audit = materialize_sweep_reclaims(
            frame, [_level(frame)], FreshLevelSweepReclaimConfig())
        self.assertEqual(signals, [])
        self.assertEqual(audit['counts']['PREMITIGATED'], 1)

    def test_overlap_is_merged_without_refreshing_old_level(self):
        frame = _minutes()
        _add_long_departure(frame)
        first = _level(frame, 'old')
        second = _level(frame, 'new', created_minute=70)
        second['order_block'] = [100.8, 101.2]
        second['ob_close_time'] = frame.index[60]
        frame.loc[frame.index[61]:frame.index[69], ['open', 'high', 'low', 'close']] = [102, 103, 101.5, 102.5]
        _, audit = materialize_sweep_reclaims(
            frame, [second, first], FreshLevelSweepReclaimConfig())
        aliases = [row for row in audit['levels'] if row['status'] == 'MERGED_ALIAS']
        self.assertEqual(aliases, [{'setup_id': 'new', 'status': 'MERGED_ALIAS', 'level_id': 'old'}])

    def test_sweep_reclaim_enters_on_next_minute_open(self):
        frame = _minutes()
        _add_long_departure(frame)
        # First contact and distal sweep occur in the 01:05-01:10 5m bar.
        frame.loc[frame.index[65]:frame.index[69], ['open', 'high', 'low', 'close']] = [101.2, 101.4, 99.8, 100.7]
        frame.loc[frame.index[69], 'close'] = 101.2
        frame.loc[frame.index[70], ['open', 'high', 'low', 'close']] = [101.25, 101.4, 101.1, 101.3]
        signals, audit = materialize_sweep_reclaims(
            frame, [_level(frame)], FreshLevelSweepReclaimConfig())
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['timestamp'], frame.index[70])
        self.assertEqual(signals[0]['reference'], 101.25)
        self.assertEqual(audit['counts']['TRIGGERED'], 1)

    def test_first_shallow_touch_consumes_level(self):
        frame = _minutes()
        _add_long_departure(frame)
        frame.loc[frame.index[65]:frame.index[69], ['open', 'high', 'low', 'close']] = [101.2, 101.3, 100.5, 101.1]
        signals, audit = materialize_sweep_reclaims(
            frame, [_level(frame)], FreshLevelSweepReclaimConfig())
        self.assertEqual(signals, [])
        self.assertEqual(audit['counts']['SHALLOW_TOUCH_CONSUMED'], 1)

    def test_gap_through_is_seen_and_invalidated(self):
        frame = _minutes()
        _add_long_departure(frame)
        frame.loc[frame.index[65], ['open', 'high', 'low', 'close']] = [98.5, 99.0, 98.0, 98.5]
        signals, audit = materialize_sweep_reclaims(
            frame, [_level(frame)], FreshLevelSweepReclaimConfig())
        self.assertEqual(signals, [])
        self.assertEqual(audit['counts']['INVALIDATED'], 1)

    def test_target_is_two_net_r_under_stress_costs(self):
        target, entry, loss = stress_target_price(1, 101.0, 99.0, 8.0, 5.0, 2.0)
        fee, slip = 8 / 10000, 5 / 10000
        target_fill = target * (1 - slip)
        net = target_fill - entry - fee * entry - fee * target_fill
        self.assertAlmostEqual(net / loss, 2.0, places=10)

    def test_short_target_is_two_net_r_under_stress_costs(self):
        target, entry, loss = stress_target_price(-1, 99.0, 101.0, 8.0, 5.0, 2.0)
        fee, slip = 8 / 10000, 5 / 10000
        target_fill = target * (1 + slip)
        net = entry - target_fill - fee * entry - fee * target_fill
        self.assertAlmostEqual(net / loss, 2.0, places=10)

    def test_opposing_level_before_target_rejects_trade(self):
        frame = _minutes()
        _add_long_departure(frame)
        frame.loc[frame.index[65]:frame.index[69], ['open', 'high', 'low', 'close']] = [101.2, 101.4, 99.8, 100.7]
        frame.loc[frame.index[69], 'close'] = 101.2
        frame.loc[frame.index[70], ['open', 'high', 'low', 'close']] = [101.25, 101.4, 101.1, 101.3]
        level = _level(frame)
        level['target_boundary'] = 102.0
        signals, audit = materialize_sweep_reclaims(
            frame, [level], FreshLevelSweepReclaimConfig())
        self.assertEqual(signals, [])
        self.assertEqual(audit['counts']['TARGET_BLOCKED'], 1)

    def test_gap_after_reclaim_consumes_without_entry(self):
        frame = _minutes()
        _add_long_departure(frame)
        frame.loc[frame.index[65]:frame.index[69], ['open', 'high', 'low', 'close']] = [101.2, 101.4, 99.8, 100.7]
        frame.loc[frame.index[69], 'close'] = 101.2
        frame.loc[frame.index[70], ['open', 'high', 'low', 'close']] = [100.8, 101.0, 100.5, 100.9]
        signals, audit = materialize_sweep_reclaims(
            frame, [_level(frame)], FreshLevelSweepReclaimConfig())
        self.assertEqual(signals, [])
        self.assertEqual(audit['counts']['ENTRY_LOST_RECLAIM'], 1)

    def test_future_append_does_not_change_existing_trigger(self):
        frame = _minutes(120)
        _add_long_departure(frame)
        frame.loc[frame.index[65]:frame.index[69], ['open', 'high', 'low', 'close']] = [101.2, 101.4, 99.8, 100.7]
        frame.loc[frame.index[69], 'close'] = 101.2
        frame.loc[frame.index[70], ['open', 'high', 'low', 'close']] = [101.25, 101.4, 101.1, 101.3]
        config = replace(FreshLevelSweepReclaimConfig(), validity_hours=1)
        original, _ = materialize_sweep_reclaims(frame, [_level(frame)], config)
        future = _minutes(240).loc[_minutes(240).index >= frame.index[-1] + pd.Timedelta(minutes=1)]
        appended = pd.concat([frame, future])
        later, _ = materialize_sweep_reclaims(appended, [_level(appended)], config)
        self.assertEqual(original, later)


if __name__ == '__main__':
    unittest.main()
