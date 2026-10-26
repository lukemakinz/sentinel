from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from ingester.models import Candle
from l2_agents.auction_service import analysis_cycle_key, analyze_symbol
from l2_agents.models import AuctionAnalysis, AuctionShadowPlan
from l2_agents.shadow_auction import create_shadow_plan, resolve_plan


def snapshot():
    return {
        'version': 'auction-snapshot-v1',
        'symbol': 'BTCUSDT',
        'snapshot_hash': 'abc',
        'instrument': {'15m': {'atr14': 10.0}},
        'zones': [
            {'kind': 'RECENT_SUPPORT', 'low': 100.0, 'high': 100.0,
             'source': 'test'},
        ],
        'execution_authorized': False,
    }


def decision():
    return {
        'action': 'ARM', 'direction': 'LONG',
        'strategy_id': 'SAI1_TREND_RETEST',
        'confidence': 0.8, 'data_quality': 1.0,
        'thesis': ['trend'], 'counter_thesis': ['breakdown'],
        'entry_zone': [100.0, 100.0],
        'trigger_conditions': ['bullish reclaim'],
        'invalidation_conditions': ['close below structural stop'],
        'management_policy': 'P0_INITIAL_STOP', 'ttl_minutes': 15,
        'recheck_condition': 'next closed candle', 'risk_notes': ['shadow'],
    }


def analysis_record():
    return AuctionAnalysis.objects.create(
        symbol='BTCUSDT', snapshot_hash='abc',
        snapshot_version='auction-snapshot-v1', prompt_version='v1',
        action='ARM', direction='LONG', strategy_id='SAI1_TREND_RETEST',
        snapshot=snapshot(), decision=decision(), runtime={}, shadow_only=True,
    )


def candle(ts, opened, high, low, close):
    return Candle.objects.create(
        symbol='BTCUSDT', interval='1m', timestamp=ts,
        open=opened, high=high, low=low, close=close, volume=1,
        is_closed=True,
    )


@override_settings(
    PAPER_MARKET_SLIPPAGE_BPS=5,
    PAPER_TAKER_FEE_BPS=5,
    PAPER_MAKER_FEE_BPS=2,
    AUCTION_SHADOW_TARGET_R=1.5,
)
class AuctionShadowPlanTest(TestCase):
    def test_arm_materializes_structural_geometry(self):
        plan = create_shadow_plan(analysis_record())

        self.assertEqual(plan.state, 'ARMED')
        self.assertEqual(plan.structural_stop, 98.5)
        self.assertEqual(plan.target_r, 1.5)
        self.assertFalse(plan.analysis.snapshot['execution_authorized'])

    def test_trigger_then_target_is_scored_net_of_costs(self):
        plan = create_shadow_plan(analysis_record())
        trigger_ts = plan.armed_at + timedelta(minutes=1)
        candle(trigger_ts, 99.5, 101.0, 99.0, 100.5)
        resolve_plan(plan, now=trigger_ts + timedelta(seconds=50))
        plan.refresh_from_db()
        self.assertEqual(plan.state, 'TRIGGERED')
        self.assertGreater(plan.entry_price, 100.5)

        candle(trigger_ts + timedelta(minutes=1), 101.0, plan.target_price + 1, 100.8, 103.0)
        resolve_plan(plan, now=trigger_ts + timedelta(minutes=2, seconds=50))
        plan.refresh_from_db()
        self.assertEqual(plan.exit_reason, 'TARGET')
        self.assertLess(plan.net_r, 1.5)
        self.assertGreater(plan.net_r, 1.0)

    def test_same_bar_stop_and_target_resolves_stop_first(self):
        plan = create_shadow_plan(analysis_record())
        trigger_ts = plan.armed_at + timedelta(minutes=1)
        candle(trigger_ts, 99.5, 101.0, 99.0, 100.5)
        resolve_plan(plan, now=trigger_ts + timedelta(seconds=50))
        plan.refresh_from_db()
        candle(
            trigger_ts + timedelta(minutes=1), 100.5,
            plan.target_price + 1, plan.structural_stop - 1, 100.0,
        )

        resolve_plan(plan, now=trigger_ts + timedelta(minutes=2, seconds=50))
        plan.refresh_from_db()
        self.assertEqual(plan.exit_reason, 'STOP')
        self.assertLess(plan.net_r, -1.0)

    def test_close_beyond_stop_before_trigger_invalidates_without_loss(self):
        plan = create_shadow_plan(analysis_record())
        ts = plan.armed_at + timedelta(minutes=1)
        candle(ts, 99.0, 99.5, 97.0, 98.0)

        resolve_plan(plan, now=ts + timedelta(seconds=50))
        plan.refresh_from_db()
        self.assertEqual(plan.state, 'INVALID')
        self.assertEqual(plan.exit_reason, 'PRE_INVALIDATION')
        self.assertIsNone(plan.net_r)


class AuctionCycleIdempotencyTest(TestCase):
    def test_same_missing_data_bar_is_persisted_once(self):
        first = analyze_symbol(
            'BTCUSDT', use_ai=False, persist=True, deduplicate_bar=True,
        )
        second = analyze_symbol(
            'BTCUSDT', use_ai=False, persist=True, deduplicate_bar=True,
        )

        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(AuctionAnalysis.objects.count(), 1)
        self.assertEqual(AuctionShadowPlan.objects.count(), 0)

    def test_quality_transition_gets_a_new_cycle_key(self):
        base = {
            'version': 'auction-snapshot-v1',
            'symbol': 'SOLUSDT',
            'as_of': timezone.now().isoformat(),
            'instrument': {'15m': {'last_timestamp': '2026-10-26T09:15:00+00:00'}},
            'data_quality': {'tradable': False},
        }

        unready = analysis_cycle_key(base, use_ai=True)
        ready = analysis_cycle_key(
            {**base, 'data_quality': {'tradable': True}}, use_ai=True,
        )

        self.assertNotEqual(unready, ready)
