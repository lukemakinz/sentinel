from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from l2_agents.trade_ideas import assess, order_type, simulate_idea


def snapshot(direction='UP', strength=80.0, global_score=40.0):
    state = {'available': True, 'direction': direction, 'strength_0_100': strength}
    return {
        'trend_state': {'timeframes': {'1h': state, '4h': state, '1d': state}, 'regime': 'X'},
        'global_context': {'state': 'TRANSITION', 'target_bias_score_minus100_100': global_score,
                           'target_data_coverage_0_1': 1.0},
        'snapshot_hash': 'h',
    }


class AssessTest(SimpleTestCase):
    def test_green_when_cheap_aligned_and_good_rr(self):
        a = assess('SOLUSDT', 'long', 100, 97, 106, price=100.05, snapshot=snapshot())
        self.assertEqual(a['verdict'], 'GREEN')
        self.assertEqual(a['order_type'], 'MARKET')
        self.assertAlmostEqual(a['quantity'], 1.25 / 3)

    def test_red_when_stop_too_tight(self):
        a = assess('SOLUSDT', 'long', 100, 99.95, 101, snapshot=snapshot())
        self.assertEqual(a['verdict'], 'RED')
        self.assertTrue(any('koszt' in r for r in a['red']))

    def test_red_when_trend_opposes(self):
        a = assess('SOLUSDT', 'short', 100, 103, 94, snapshot=snapshot('UP'))
        self.assertEqual(a['verdict'], 'RED')

    def test_yellow_without_trend_data(self):
        a = assess('NEWUSDT', 'long', 100, 97, 106, snapshot={'global_context': {}})
        self.assertEqual(a['verdict'], 'YELLOW')

    def test_rejects_stop_on_wrong_side(self):
        with self.assertRaises(ValueError):
            assess('SOLUSDT', 'long', 100, 101, snapshot=snapshot())

    def test_order_types(self):
        self.assertEqual(order_type('LONG', 95, 100), 'LIMIT')
        self.assertEqual(order_type('LONG', 105, 100), 'STOP_ENTRY')
        self.assertEqual(order_type('SHORT', 105, 100), 'LIMIT')


class SimulateIdeaTest(SimpleTestCase):
    def idea(self, kind='MARKET', direction='LONG', entry=100.0, stop=98.0, target=104.0):
        return SimpleNamespace(direction=direction, entry=entry, stop=stop, target=target,
                               created_at=pd.Timestamp('2026-11-02 10:00', tz='UTC').to_pydatetime(),
                               assessment={'order_type': kind})

    def bars(self, rows):
        idx = pd.date_range('2026-11-02 10:00', periods=len(rows), freq='1min', tz='UTC')
        return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=idx)

    def test_market_entry_hits_target(self):
        r = simulate_idea(self.idea(), self.bars([(100, 100.2, 99.9, 100), (100, 104.5, 99.5, 104)]),
                          timezone.now())
        self.assertEqual((r['state'], r['exit_reason']), ('CLOSED', 'TARGET'))
        self.assertGreater(r['net_r'], 1.8)

    def test_limit_needs_trade_through_and_expires(self):
        idea = self.idea(kind='LIMIT', entry=97.0, stop=95.0, target=101.0)
        r = simulate_idea(idea, self.bars([(100, 100.5, 97.0, 99)]), idea.created_at + timedelta(hours=30))
        self.assertEqual(r['state'], 'EXPIRED')

    def test_same_bar_stop_first(self):
        r = simulate_idea(self.idea(), self.bars([(100, 100, 100, 100), (100, 105, 97, 101)]), timezone.now())
        self.assertEqual(r['exit_reason'], 'STOP')
        self.assertLess(r['net_r'], -1.0)


class JournalTest(TestCase):
    def test_stats_split_by_verdict(self):
        from l2_agents.models import TradeIdea
        from l2_agents.trade_ideas import journal_stats

        for verdict, r in (('GREEN', 1.5), ('GREEN', -1.0), ('RED', -1.1)):
            TradeIdea.objects.create(symbol='SOLUSDT', direction='LONG', entry=1, stop=0.9,
                                     verdict=verdict, state='CLOSED', net_r=r, exit_reason='X')
        s = journal_stats()
        self.assertEqual(s['closed']['n'], 3)
        self.assertEqual(s['by_verdict']['GREEN']['n'], 2)
        self.assertEqual(s['by_verdict']['RED']['mean_r'], -1.1)
