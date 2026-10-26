from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase, TestCase

from .shadow_resolver import replay_one_r_barrier
from .models import Signal
from .stats import get_stats


START = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
END = START + timedelta(minutes=3)


def candles(*values):
    return [{
        'timestamp': START + timedelta(minutes=index),
        'high': high,
        'low': low,
        'close': close,
    } for index, (high, low, close) in enumerate(values)]


class ShadowResolverTests(SimpleTestCase):
    def test_long_limit_reaches_one_r(self):
        result = replay_one_r_barrier(
            'LONG', 100, 99, START, END,
            candles((100.2, 99.8, 100.1), (101.1, 100.0, 101.0), (101, 100, 100.5)),
        )
        self.assertEqual(result.outcome, 'WIN')
        self.assertEqual(result.exit_reason, 'TP1')
        self.assertEqual(result.pnl_r, 1.0)

    def test_ambiguous_bar_is_stop_first(self):
        result = replay_one_r_barrier(
            'LONG', 100, 99, START, END,
            candles((101.2, 98.8, 100), (100, 100, 100), (100, 100, 100)),
        )
        self.assertEqual(result.outcome, 'LOSS')
        self.assertEqual(result.exit_reason, 'SL')

    def test_unfilled_limit_expires(self):
        result = replay_one_r_barrier(
            'LONG', 100, 99, START, END,
            candles((102, 101, 101.5), (103, 101, 102), (102, 101, 101.5)),
        )
        self.assertEqual(result.outcome, 'EXPIRED')
        self.assertIsNone(result.pnl_r)

    def test_incomplete_future_window_is_not_labeled(self):
        result = replay_one_r_barrier(
            'LONG', 100, 99, START, END,
            candles((100.2, 99.8, 100.1)),
        )
        self.assertIsNone(result)


class AISelectorStatsTests(TestCase):
    def test_approved_and_rejected_cohorts_are_compared(self):
        for action, pnl in (('APPROVE', 1.0), ('APPROVE', -1.0), ('REJECT', -1.0)):
            Signal.objects.create(
                symbol='ETHUSDT', direction='LONG', strategy='S12AI',
                state='CLOSED', outcome='WIN' if pnl > 0 else 'LOSS',
                pnl_r=pnl, l2_action=action, shadow=True,
            )
        stats = get_stats()['ai_selector']
        self.assertEqual(stats['total_resolved'], 3)
        self.assertEqual(stats['approved']['raw_profit_factor'], 1.0)
        self.assertGreater(stats['selection_lift_avg_r'], 0)
        self.assertFalse(stats['sample_ready'])
