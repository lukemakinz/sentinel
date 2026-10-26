from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ingester.models import OpenInterest, WhaleCVD
from l2_agents.market_intelligence import _data_quality, _flow_snapshot


class FlowWindowQualityTest(TestCase):
    def test_stale_previous_oi_is_not_used_as_a_fresh_change(self):
        now = timezone.now()
        OpenInterest.objects.create(
            symbol='SOLUSDT', timestamp=now - timedelta(days=30),
            open_interest=Decimal('100'),
        )
        OpenInterest.objects.create(
            symbol='SOLUSDT', timestamp=now,
            open_interest=Decimal('110'),
        )

        flow = _flow_snapshot('SOLUSDT', now)

        self.assertIsNone(flow['open_interest_change_pct'])
        self.assertGreater(flow['open_interest_sample_gap_seconds'], 15 * 60)

    def test_oi_and_cvd_require_real_recent_windows(self):
        now = timezone.now()
        OpenInterest.objects.create(
            symbol='SOLUSDT', timestamp=now - timedelta(minutes=5),
            open_interest=Decimal('100'),
        )
        OpenInterest.objects.create(
            symbol='SOLUSDT', timestamp=now,
            open_interest=Decimal('101'),
        )
        WhaleCVD.objects.create(
            symbol='SOLUSDT', timestamp=now - timedelta(minutes=5),
            cumulative_delta=Decimal('1000'),
        )
        WhaleCVD.objects.create(
            symbol='SOLUSDT', timestamp=now,
            cumulative_delta=Decimal('1250'),
        )

        flow = _flow_snapshot('SOLUSDT', now)

        self.assertAlmostEqual(flow['open_interest_change_pct'], 1.0)
        self.assertEqual(flow['open_interest_sample_gap_seconds'], 300)
        self.assertEqual(flow['whale_cvd_change'], 250.0)
        self.assertEqual(flow['whale_cvd_window_seconds'], 300)

    def test_stale_global_context_is_a_hard_failure(self):
        now = timezone.now()
        timeframes = {
            interval: {
                'last_timestamp': now.isoformat(),
                'bars': 220,
            }
            for interval in ('15m', '1h', '4h')
        }
        depth = {'available': True, 'age_seconds': 1}
        flow = {
            'open_interest_change_pct': 0.1,
            'open_interest_timestamp': now.isoformat(),
            'open_interest_sample_gap_seconds': 300,
            'funding_rate': 0.0001,
            'funding_timestamp': now.isoformat(),
            'whale_cvd_change': 100,
            'whale_cvd_timestamp': now.isoformat(),
            'whale_cvd_window_seconds': 300,
        }
        regime = {
            'btc_4h_last_timestamp': (now - timedelta(days=1)).isoformat(),
            'eth_4h_last_timestamp': now.isoformat(),
        }

        quality = _data_quality(timeframes, depth, flow, regime, now)

        self.assertFalse(quality['tradable'])
        self.assertIn('global_btc_4h_fresh', quality['hard_failures'])
