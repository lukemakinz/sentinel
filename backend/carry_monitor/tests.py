from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import TestCase
from django.utils import timezone as dj_timezone

from .live_prices import (
    funding_score_bps,
    get_completed_daily_spot_closes,
    get_funding_settlements,
    get_last_closed_mark_high,
    get_perp_price,
    get_spot_price,
)
from .models import CarryDecisionLog, CarryEpisode
from .tasks import (
    PROTOCOL_SHA256,
    STRATEGY,
    _live_features,
    accrue_funding,
    evaluate_monthly_decision,
    monitor_safety,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _feature(funding=60.0, return_pct=10.0, close=110.0, ema=100.0):
    return {
        'feature_cutoff': '2026-01-31 00:00:00+00:00',
        'close': close,
        'ema50': ema,
        'return_30d_pct': return_pct,
        'prior_month_funding_bps': funding,
        'qualified': funding >= 50 and return_pct > 0 and close > ema,
    }


def _features(eth=60.0, sol=40.0, bnb=30.0):
    return {
        'ETHUSDT': _feature(eth),
        'SOLUSDT': _feature(sol),
        'BNBUSDT': _feature(bnb),
    }


class LivePricesTests(TestCase):
    @patch('carry_monitor.live_prices.requests.get')
    def test_spot_and_perpetual_prices_are_read_only_tickers(self, mock_get):
        mock_get.side_effect = [
            _FakeResponse({'price': '2500.5'}),
            _FakeResponse({'price': '2499.5'}),
        ]
        self.assertEqual(get_spot_price('ETHUSDT'), 2500.5)
        self.assertEqual(get_perp_price('ETHUSDT'), 2499.5)

    @patch('carry_monitor.live_prices.requests.get')
    def test_daily_closes_end_before_decision(self, mock_get):
        rows = [
            [1735689600000, '0', '0', '0', '100', '0', 0],
            [1735776000000, '0', '0', '0', '101', '0', 0],
        ]
        mock_get.return_value = _FakeResponse(rows)
        end = datetime(2025, 2, 1, tzinfo=timezone.utc)
        frame = get_completed_daily_spot_closes('ETHUSDT', end)
        self.assertEqual(list(frame.close), [100.0, 101.0])
        self.assertEqual(mock_get.call_args.kwargs['params']['endTime'],
                         int(end.timestamp() * 1000) - 1)

    @patch('carry_monitor.live_prices.requests.get')
    def test_last_closed_mark_high_ignores_open_bar(self, mock_get):
        now = datetime(2025, 1, 1, 0, 2, 30, tzinfo=timezone.utc)
        mock_get.return_value = _FakeResponse([
            [1735689660000, '100', '105', '99', '102', '0', 1735689719999],
            [1735689720000, '102', '999', '101', '103', '0', 1735689779999],
        ])
        bar_time, high = get_last_closed_mark_high('ETHUSDT', now)
        self.assertEqual(bar_time, datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(high, 105.0)

    @patch('carry_monitor.live_prices.requests.get')
    def test_funding_score_sums_and_scales(self, mock_get):
        mock_get.return_value = _FakeResponse([
            {'fundingTime': 1735689600000, 'fundingRate': '0.0001', 'markPrice': '100'},
            {'fundingTime': 1735718400000, 'fundingRate': '0.0002', 'markPrice': '101'},
        ])
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 2, 1, tzinfo=timezone.utc)
        self.assertAlmostEqual(funding_score_bps('ETHUSDT', start, end), 3.0)
        rows = get_funding_settlements('ETHUSDT', start, end)
        self.assertEqual(rows[0]['mark_price'], 100.0)


class Safe25MonthlyDecisionTests(TestCase):
    def setUp(self):
        self.feb = datetime(2026, 2, 1, 1, tzinfo=timezone.utc)
        self.mar = datetime(2026, 3, 1, 1, tzinfo=timezone.utc)

    @patch('carry_monitor.tasks.get_perp_price', return_value=2500.0)
    @patch('carry_monitor.tasks.get_spot_price', return_value=2500.0)
    @patch('carry_monitor.tasks._live_features')
    @patch('carry_monitor.tasks.timezone.now')
    def test_enters_filtered_leader_with_rounded_equal_quantity(
            self, mock_now, mock_live, _spot, _perp):
        mock_now.return_value = self.feb
        mock_live.side_effect = lambda symbol, *_: _features()[symbol]
        result = evaluate_monthly_decision()
        self.assertEqual(result['target'], 'ETHUSDT')
        episode = CarryEpisode.objects.get(status='OPEN')
        self.assertEqual(episode.strategy, STRATEGY)
        self.assertEqual(episode.protocol_sha256, PROTOCOL_SHA256)
        self.assertAlmostEqual(episode.quantity, .009)
        self.assertGreater(episode.reserve_usd, 27)

    @patch('carry_monitor.tasks.get_funding_settlements', return_value=[])
    @patch('carry_monitor.tasks.get_perp_price', return_value=2500.0)
    @patch('carry_monitor.tasks.get_spot_price', return_value=2500.0)
    @patch('carry_monitor.tasks._live_features')
    @patch('carry_monitor.tasks.timezone.now')
    def test_same_leader_is_force_reset_next_month(
            self, mock_now, mock_live, _spot, _perp, _funding):
        mock_now.return_value = self.feb
        mock_live.side_effect = lambda symbol, *_: _features()[symbol]
        evaluate_monthly_decision()
        first = CarryEpisode.objects.get(status='OPEN')
        mock_now.return_value = self.mar
        result = evaluate_monthly_decision()
        first.refresh_from_db()
        second = CarryEpisode.objects.get(status='OPEN')
        self.assertEqual(result['action'], 'monthly_reset_same_asset')
        self.assertEqual(first.status, 'CLOSED')
        self.assertNotEqual(first.id, second.id)

    @patch('carry_monitor.tasks.get_perp_price', return_value=2500.0)
    @patch('carry_monitor.tasks.get_spot_price', return_value=2500.0)
    @patch('carry_monitor.tasks._live_features')
    @patch('carry_monitor.tasks.timezone.now')
    def test_monthly_decision_is_idempotent(
            self, mock_now, mock_live, _spot, _perp):
        mock_now.return_value = self.feb
        mock_live.side_effect = lambda symbol, *_: _features()[symbol]
        evaluate_monthly_decision()
        result = evaluate_monthly_decision()
        self.assertEqual(result['action'], 'already_evaluated')
        self.assertEqual(CarryEpisode.objects.count(), 1)
        self.assertEqual(CarryDecisionLog.objects.count(), 1)

    @patch('carry_monitor.tasks.funding_score_bps', return_value=60.0)
    @patch('carry_monitor.tasks.get_completed_daily_spot_closes')
    def test_live_feature_uses_completed_return_and_ema(self, mock_daily, _funding):
        index = pd.date_range('2025-09-01', periods=150, freq='1D', tz='UTC')
        mock_daily.return_value = pd.DataFrame(
            {'close': np.linspace(80, 120, len(index))}, index=index)
        row = _live_features(
            'ETHUSDT',
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(row['qualified'])
        self.assertGreater(row['return_30d_pct'], 0)
        self.assertGreater(row['close'], row['ema50'])


class FundingAndSafetyTests(TestCase):
    def _episode(self, **overrides):
        now = dj_timezone.now() - dj_timezone.timedelta(hours=2)
        values = {
            'strategy': STRATEGY,
            'protocol_sha256': PROTOCOL_SHA256,
            'symbol': 'ETHUSDT',
            'status': 'OPEN',
            'opened_at': now,
            'spot_entry_price': 2500.0,
            'perp_entry_price': 2500.0,
            'notional_usd': 22.5,
            'quantity': .009,
            'futures_margin_usd': 200.0,
            'reserve_usd': 27.4,
            'qualifying_funding_bps': 60.0,
            'entry_reason': 'enter_highest_funding',
            'last_funding_accrued_at': now,
            'min_futures_equity_usd': 199.98,
            'max_mark_leverage': .113,
        }
        values.update(overrides)
        return CarryEpisode.objects.create(**values)

    @patch('carry_monitor.tasks.get_funding_settlements')
    def test_positive_funding_is_not_added_to_safety_buffer(self, mock_rows):
        episode = self._episode()
        settlement_time = episode.opened_at + dj_timezone.timedelta(hours=1)
        mock_rows.return_value = [
            {'time': settlement_time, 'rate': .01, 'mark_price': 2500.0},
            {'time': settlement_time, 'rate': -.001, 'mark_price': 2500.0},
        ]
        result = accrue_funding()
        episode.refresh_from_db()
        self.assertAlmostEqual(result['accrued_usd'], .2025)
        self.assertAlmostEqual(episode.adverse_funding_usd, -.0225)

    @patch('carry_monitor.tasks.get_funding_settlements', return_value=[])
    @patch('carry_monitor.tasks.get_perp_price', return_value=2500.0)
    @patch('carry_monitor.tasks.get_spot_price', return_value=2500.0)
    @patch('carry_monitor.tasks.get_last_closed_mark_high')
    def test_squeeze_closes_at_next_monitor_run(
            self, mock_high, _spot, _perp, _funding):
        episode = self._episode()
        bar_time = dj_timezone.now() - dj_timezone.timedelta(minutes=1)
        mock_high.return_value = (bar_time, 12_000.0)
        result = monitor_safety()
        episode.refresh_from_db()
        self.assertTrue(result['action'].startswith('emergency_'))
        self.assertEqual(episode.status, 'CLOSED')
        self.assertLess(episode.min_futures_equity_usd, 125)

    def test_tasks_are_noops_while_flat(self):
        self.assertEqual(accrue_funding(), {'accrued_usd': 0.0, 'settlements': 0})
        self.assertEqual(monitor_safety(), {'action': 'flat'})
