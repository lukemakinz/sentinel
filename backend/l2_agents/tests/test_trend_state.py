from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase, TestCase

from l2_agents.market_intelligence import MarketSnapshotBuilder
from l2_agents.trend_state import (
    TREND_STATE_VERSION,
    build_trend_state,
    classify_timeframe,
    derive_closed_daily_rows,
)


def rows(direction=1, count=80, interval_minutes=60):
    start = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    result = []
    for index in range(count):
        close = 100.0 + direction * index if direction else 100.0
        result.append({
            'timestamp': start + timedelta(minutes=index * interval_minutes),
            'open': close - direction * 0.2,
            'high': close + 0.5,
            'low': close - 0.5,
            'close': close,
            'volume': 10.0 + index,
        })
    return result


class TrendStateUnitTest(SimpleTestCase):
    def test_classifies_up_down_and_range_from_closed_rows(self):
        self.assertEqual(classify_timeframe(rows(1), '1h')['direction'], 'UP')
        self.assertEqual(classify_timeframe(rows(-1), '1h')['direction'], 'DOWN')
        self.assertEqual(classify_timeframe(rows(0), '1h')['direction'], 'RANGE')

    def test_daily_aggregation_requires_all_six_closed_4h_bars(self):
        source = rows(1, count=11, interval_minutes=240)
        complete = derive_closed_daily_rows(source)
        self.assertEqual(len(complete), 1)
        self.assertEqual(complete[0]['close'], source[5]['close'])

    def test_multi_timeframe_state_has_fixed_contract_and_no_execution_authority(self):
        frames = {
            interval: {'_recent_rows': rows(1, interval_minutes=minutes)}
            for interval, minutes in (
                ('5m', 5), ('15m', 15), ('1h', 60), ('4h', 240), ('1d', 1440)
            )
        }
        state = build_trend_state(frames)

        self.assertEqual(state['version'], TREND_STATE_VERSION)
        self.assertEqual(state['alignment'], 'ALIGNED_UP')
        self.assertEqual(state['directional_bias'], 'LONG')
        self.assertFalse(state['execution_authorized'])
        self.assertEqual(set(state['timeframes']), {'5m', '15m', '1h', '4h', '1d'})


class TrendStateSnapshotTest(TestCase):
    def test_snapshot_always_contains_all_learning_timeframes(self):
        snapshot = MarketSnapshotBuilder().build('BTCUSDT')

        self.assertEqual(snapshot['trend_state']['version'], TREND_STATE_VERSION)
        self.assertFalse(snapshot['trend_state']['execution_authorized'])
        self.assertEqual(
            set(snapshot['trend_state']['timeframes']),
            {'5m', '15m', '1h', '4h', '1d'},
        )
        self.assertIn('1d', snapshot['instrument'])
        self.assertEqual(
            snapshot['instrument']['1d']['source'],
            'derived_from_six_closed_4h_bars_utc',
        )


class BreadthIsolationTest(TestCase):
    """Breadth alts must reach global_context (M3) but never M0's global_regime."""

    def test_breadth_alts_do_not_change_frozen_global_regime(self):
        from django.test import override_settings
        from django.utils import timezone
        from unittest.mock import patch

        from l2_agents import market_intelligence as mi

        def fake_summary(symbol, interval, limit=240):
            trend = 'DOWN' if symbol.startswith('ALT') else 'UP'
            return {'available': True, 'trend': trend, 'bars': limit,
                    'last_timestamp': timezone.now().isoformat(),
                    'return_20_pct': 0.0, '_recent_rows': []}

        captured = {}
        real_regime = mi._global_regime

        def spy_regime(summaries):
            captured['regime_symbols'] = set(summaries)
            return real_regime(summaries)

        alts = [f'ALT{i}USDT' for i in range(6)]
        with override_settings(BREADTH_PAIRS=alts, BREADTH_UNIVERSE_VERSION='u-test'), \
                patch.object(mi, '_timeframe_summary', side_effect=fake_summary), \
                patch.object(mi, '_global_regime', side_effect=spy_regime):
            snapshot = MarketSnapshotBuilder().build('SOLUSDT')

        self.assertTrue(captured['regime_symbols'].isdisjoint(alts))
        breadth = snapshot['global_context']['components']['alt_breadth_1h']
        self.assertEqual(breadth['symbols'], 6)
        self.assertEqual(breadth['down_share'], 1.0)
