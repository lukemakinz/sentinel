from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from ingester.models import Candle
from l2_agents.auction_service import analysis_cycle_key, analyze_symbol
from l2_agents.models import AuctionAnalysis, AuctionShadowPlan
from l2_agents.auction_learning import build_postmortem, ensure_postmortem
from l2_agents.shadow_auction import create_shadow_plan, resolve_open_plans, resolve_plan


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

    @override_settings(AUCTION_SHADOW_MAX_HOLD_MINUTES=60)
    def test_late_trigger_keeps_full_post_entry_holding_window(self):
        plan = create_shadow_plan(analysis_record())
        trigger_ts = plan.armed_at + timedelta(minutes=14)
        candle(trigger_ts, 99.5, 101.0, 99.0, 100.5)
        resolve_plan(plan, now=trigger_ts + timedelta(seconds=50))
        plan.refresh_from_db()

        self.assertEqual(plan.state, 'TRIGGERED')
        self.assertEqual(
            plan.position_expires_at,
            trigger_ts + timedelta(minutes=60),
        )
        target_ts = plan.armed_at + timedelta(minutes=16)
        candle(target_ts, 101.0, plan.target_price + 1, 100.8, plan.target_price)
        resolve_plan(plan, now=target_ts + timedelta(seconds=50))
        plan.refresh_from_db()

        self.assertEqual(plan.exit_reason, 'TARGET')

    @override_settings(AUCTION_SHADOW_MAX_HOLD_MINUTES=5)
    def test_closed_plan_gets_versioned_postmortem_and_frozen_counterfactuals(self):
        plan = create_shadow_plan(analysis_record())
        trigger_ts = plan.armed_at + timedelta(minutes=1)
        candle(trigger_ts, 99.5, 101.0, 99.0, 100.5)
        resolve_plan(plan, now=trigger_ts + timedelta(seconds=50))
        plan.refresh_from_db()

        target_ts = trigger_ts + timedelta(minutes=1)
        candle(target_ts, 101.0, plan.target_price + 1, 100.4, plan.target_price)
        resolve_plan(plan, now=target_ts + timedelta(seconds=50))
        plan.refresh_from_db()
        self.assertEqual(plan.exit_reason, 'TARGET')

        # Counterfactuals wait for the entire original five-minute holding
        # window, even though the canonical 1.5R trade closed earlier.
        for minute in (2, 3, 4):
            candle(
                trigger_ts + timedelta(minutes=minute),
                plan.target_price, plan.target_price + 0.2,
                plan.target_price - 0.2, plan.target_price,
            )
        payload = build_postmortem(
            plan, now=plan.position_expires_at + timedelta(seconds=1),
        )

        self.assertEqual(payload['primary_diagnosis'], 'SUCCESS')
        self.assertFalse(payload['execution_authorized'])
        self.assertEqual(
            set(payload['counterfactuals']),
            {
                'market_target_1.0r', 'market_target_1.5r',
                'market_target_2.0r', 'post_confirmation_limit_5m',
                'intraday_p1_structural', 'intraday_p2_hybrid',
            },
        )
        self.assertTrue(
            payload['counterfactuals']['post_confirmation_limit_5m']['filled'],
        )
        self.assertEqual(
            ensure_postmortem(
                plan, now=plan.position_expires_at + timedelta(seconds=1),
            ),
            'CREATED',
        )
        plan.refresh_from_db()
        self.assertEqual(
            plan.postmortem_version,
            'auction-postmortem-v3-intraday-management',
        )
        self.assertEqual(ensure_postmortem(plan), 'EXISTS')

    def test_expired_candidate_is_learned_as_no_trigger_without_fake_pnl(self):
        plan = create_shadow_plan(analysis_record())
        last_ts = plan.expires_at - timedelta(minutes=1)
        candle(last_ts, 100.3, 100.4, 99.5, 100.2)
        resolve_plan(plan, now=plan.expires_at + timedelta(seconds=1))
        plan.refresh_from_db()

        outcome = resolve_open_plans(now=plan.expires_at + timedelta(seconds=1))
        plan.refresh_from_db()
        payload = plan.postmortem

        self.assertEqual(plan.state, 'EXPIRED')
        self.assertEqual(outcome['POSTMORTEM_CREATED'], 1)
        self.assertEqual(payload['primary_diagnosis'], 'NO_TRIGGER')
        self.assertEqual(payload['actual']['net_r'], 0.0)
        self.assertEqual(payload['counterfactuals'], {})


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
