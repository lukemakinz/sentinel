from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
from django.test import TestCase, override_settings

from backtest.auction_replay import Bars, ReplayPlan, Replay
from backtest.auction_replay_stats import day_block_bootstrap, frame, summarize
from ingester.models import Candle, WatchedPair
from l2_agents.market_intelligence import MICROSTRUCTURE_CHECKS, MarketSnapshotBuilder

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
COUNTS = {'5m': 260, '15m': 120, '1h': 240, '4h': 240}
STEP = {'5m': 5, '15m': 15, '1h': 60, '4h': 240}
ALTS = [f'ALT{i}USDT' for i in range(6)]


def series(seed, drift, count):
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, count)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.003, count))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.003, count))
    volume = rng.uniform(10, 50, count)
    # Binance prices carry <= 8 decimals, exactly what the DecimalField stores.
    return tuple(np.round(a, 8) for a in (opens, highs, lows, closes, volume))


class ReplayParityTest(TestCase):
    """Live builder (DB) and replay (memory) must compose the same snapshot."""

    def setUp(self):
        WatchedPair.objects.create(symbol='SOLUSDT', active=True)
        drifts = {'BTCUSDT': 0.001, 'ETHUSDT': 0.0008, 'SOLUSDT': 0.0012,
                  **{alt: (0.001 if i % 2 else -0.001) for i, alt in enumerate(ALTS)}}
        self.frames = {}
        rows = []
        for seed, (symbol, drift) in enumerate(drifts.items()):
            for interval, count in COUNTS.items():
                if symbol in ALTS and interval != '1h':
                    continue
                if symbol != 'SOLUSDT' and interval == '5m':
                    continue
                o, h, l, c, v = series(seed * 10 + len(interval), drift, count)
                step = timedelta(minutes=STEP[interval])
                first = NOW - step * count
                stamps = [first + step * i for i in range(count)]
                self.frames[(symbol, interval)] = pd.DataFrame({
                    'timestamp': [int(s.timestamp() * 1000) for s in stamps],
                    'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
                })
                rows += [Candle(
                    symbol=symbol, interval=interval, timestamp=stamps[i],
                    # NumPy 2 may repr scalars as ``np.float64('...')``;
                    # Decimal expects a plain numeric string.
                    open=Decimal(str(float(o[i]))), high=Decimal(str(float(h[i]))),
                    low=Decimal(str(float(l[i]))), close=Decimal(str(float(c[i]))),
                    volume=Decimal(str(float(v[i]))), is_closed=True,
                ) for i in range(count)]
        Candle.objects.bulk_create(rows)

    def _replay(self):
        replay = Replay(start=pd.Timestamp(NOW), end=pd.Timestamp(NOW), cache='/unused',
                        breadth_by_quarter={'2026Q1': ALTS})
        for symbol, interval in [(s, i) for s in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', *ALTS]
                                 for i in COUNTS]:
            data = self.frames.get((symbol, interval))
            replay._bars[(symbol, interval)] = Bars(symbol, interval, data) if data is not None else None
        return replay

    @override_settings(BREADTH_PAIRS=ALTS, BREADTH_UNIVERSE_VERSION='parity')
    def test_live_and_replay_snapshots_match(self):
        live = MarketSnapshotBuilder().build('SOLUSDT', now=NOW)
        replay = self._replay().snapshot('SOLUSDT', NOW, full=True)

        self.assertEqual(live['global_regime'], replay['global_regime'])
        self.assertEqual(live['trend_state'], replay['trend_state'])
        self.assertEqual(live['zones'], replay['zones'])
        for interval in ('5m', '15m', '1h', '4h', '1d'):
            for key, value in live['instrument'][interval].items():
                other = replay['instrument'][interval][key]
                if isinstance(value, float):
                    self.assertAlmostEqual(value, other, places=9, msg=f'{interval}.{key}')
                else:
                    self.assertEqual(value, other, msg=f'{interval}.{key}')
        strip = lambda ctx: {k: v for k, v in ctx.items() if k != 'breadth_universe'}  # noqa: E731
        self.assertEqual(strip(live['global_context']), strip(replay['global_context']))
        self.assertEqual(replay['global_context']['components']['alt_breadth_1h']['symbols'], 6)
        live_candle_checks = {k: v for k, v in live['data_quality']['checks'].items()
                              if k not in MICROSTRUCTURE_CHECKS}
        self.assertEqual(live_candle_checks, replay['data_quality']['checks'])
        self.assertEqual(replay['data_quality']['mode'], 'candles_only_replay')

    @override_settings(BREADTH_PAIRS=ALTS)
    def test_cheap_snapshot_carries_the_same_m0_inputs(self):
        replay = self._replay()
        full = replay.snapshot('SOLUSDT', NOW, full=True)
        cheap = replay.snapshot('SOLUSDT', NOW, full=False)
        self.assertEqual(cheap['global_regime'], full['global_regime'])
        self.assertEqual(cheap['zones'], full['zones'])
        self.assertEqual(cheap['data_quality'], full['data_quality'])
        self.assertEqual(
            {k: v for k, v in cheap['instrument']['15m'].items() if k != '_recent_rows'},
            full['instrument']['15m'])

    def test_bars_never_expose_an_unclosed_bar(self):
        bars = Bars('X', '1h', self.frames[('BTCUSDT', '1h')])
        t_ms = int(NOW.timestamp() * 1000)
        self.assertEqual(bars.closed_count(t_ms), len(bars))
        self.assertEqual(bars.closed_count(t_ms - 1), len(bars) - 1)


class ReplayResolverTest(TestCase):
    def test_production_resolver_runs_on_in_memory_plan(self):
        from l2_agents.shadow_auction import resolve_plan

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        prices = [(100, 100.2, 99.0, 100.6)] + [(100.6, 105.5, 100.5, 105.0)] * 5
        frame_1m = pd.DataFrame({
            'timestamp': [int((start + timedelta(minutes=i)).timestamp() * 1000)
                          for i in range(len(prices))],
            'open': [p[0] for p in prices], 'high': [p[1] for p in prices],
            'low': [p[2] for p in prices], 'close': [p[3] for p in prices],
            'volume': [1.0] * len(prices),
        })
        minutes = Bars('SOLUSDT', '1m', frame_1m)
        plan = ReplayPlan(
            symbol='SOLUSDT', strategy_id='SAI1_FAILED_AUCTION', direction='LONG',
            zone_kind='RECENT_SUPPORT', zone_low=99.5, zone_high=100.5,
            structural_stop=98.0, target_r=1.5, management_policy='P0_INITIAL_STOP',
            armed_at=start, expires_at=start + timedelta(minutes=60),
            position_expires_at=None,
            cost_assumptions={'entry_taker_fee_bps': 5, 'target_maker_fee_bps': 2,
                              'stop_taker_fee_bps': 5, 'market_slippage_bps': 5,
                              'max_hold_minutes': 240},
        )
        loader = lambda s, e: minutes.window(int(s.timestamp() * 1000), int(e.timestamp() * 1000))  # noqa: E731
        state = resolve_plan(plan, now=start + timedelta(days=1), rows_loader=loader)
        self.assertEqual(state, 'CLOSED')
        self.assertEqual(plan.exit_reason, 'TARGET')
        self.assertGreater(plan.net_r, 1.3)
        self.assertLess(plan.net_r, plan.gross_r)


class ReplayStatsTest(TestCase):
    def _records(self):
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        out = []
        for i in range(40):
            win = i % 2 == 0
            out.append({
                'symbol': 'SOLUSDT', 'bar_close': (base + timedelta(hours=6 * i)).isoformat(),
                'direction': 'LONG', 'regime': 'TREND_UP', 'global_state': 'TRANSITION',
                'm1': 'ARM' if win else 'PASS', 'm3': 'ARM',
                'state': 'CLOSED', 'exit_reason': 'TARGET' if win else 'STOP',
                'net_r': 1.4 if win else -1.1, 'gross_r': 1.5 if win else -1.0,
                'management': {
                    'p1_structural': {
                        'complete': True, 'net_r': 0.8 if win else -0.5,
                        'tp1_hit': win,
                    },
                    'p2_hybrid': {
                        'complete': True, 'net_r': 0.7 if win else -0.4,
                        'tp1_hit': win,
                    },
                },
            })
        out.append({**out[0], 'state': 'EXPIRED', 'exit_reason': 'NO_TRIGGER',
                    'net_r': None, 'gross_r': None, 'management': {}})
        return out

    def test_vetoes_score_zero_and_uplift_is_paired(self):
        summary = summarize(self._records(), start='2025-01-01', end='2025-01-11', usd_per_r=1.25)
        self.assertEqual(summary['candidates'], 41)
        m1 = summary['policies']['m1']
        self.assertEqual(m1['filled_trades'], 20)
        self.assertEqual(summary['policies']['m3'], {**summary['policies']['m0'],
                                                     'candidates_kept': 41})
        # M1 removed exactly the 20 losers: +1.1 R each over 41 candidates.
        self.assertAlmostEqual(summary['paired_uplift_vs_m0']['m1']['mean'], 22.0 / 41, places=3)
        self.assertEqual(summary['paired_uplift_vs_m0']['m3']['mean'], 0.0)
        self.assertGreater(summary['paired_uplift_vs_m0']['m1']['ci95'][0], 0)

    def test_unfilled_plan_counts_as_zero_r(self):
        df = frame(self._records())
        self.assertEqual(df.iloc[-1].r_m0, 0.0)
        self.assertFalse(df.iloc[-1].filled)

    def test_management_policies_share_candidate_denominator(self):
        summary = summarize(
            self._records(), start='2025-01-01', end='2025-01-11',
            usd_per_r=1.25,
        )

        p1 = summary['management_policies']['p1']
        self.assertEqual(p1['comparison_candidates'], 41)
        self.assertEqual(p1['filled_trades'], 40)
        self.assertEqual(p1['tp1_hit_rate'], 0.5)
        self.assertAlmostEqual(p1['total_r'], 6.0)
        self.assertIn('p2', summary['management_uplift_vs_p0'])

    def test_incomplete_right_edge_window_is_excluded_not_scored_zero(self):
        records = self._records()
        records.append({
            **records[0], 'outcome': 'INCOMPLETE_DATA',
            'state': 'ARMED', 'net_r': None, 'gross_r': None,
        })

        df = frame(records)

        self.assertEqual(len(df), len(self._records()))

    def test_bootstrap_is_deterministic(self):
        df = frame(self._records())
        self.assertEqual(day_block_bootstrap(df, 'r_m0'), day_block_bootstrap(df, 'r_m0'))
