"""Historical replay of the frozen shadow-auction policies M0 / M1 / M3.

The replay calls the *same* production code as the live shadow loop:
``compose_snapshot`` (snapshot assembly), ``mechanical_decision`` (M0),
``trend_filtered_decision`` (M1), ``global_context_filtered_decision`` (M3),
``plan_geometry`` (entry/stop/target/costs) and ``resolve_plan`` (1m outcome
resolver).  Only data loading differs: Binance public archives instead of the
database.  Rules are frozen for this run, but the historical period remains a
retrospective diagnostic sample.  Only data collected after preregistration or
an untouched holdout may be described as out-of-sample.

Documented deviations from live (see ``REPLAY_ASSUMPTIONS``):
* Order book / OI / whale-CVD history does not exist, so the data-quality gate
  checks candle and cross-market freshness only.  M0 never uses those values
  geometrically; they only gate data availability.
* A plan is armed ``ARM_LATENCY`` after the 15m bar close (live cycles every
  5 minutes, i.e. 0-5 minutes late).
* The L1 FVG zone is absent (M0 uses RECENT_SUPPORT / RECENT_RESISTANCE only).
* Breadth universe: point-in-time per quarter, same rule as live minus the
  'Alpha' tag, which has no history.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests

from .broad_universe import INDEX_SYMBOLS, NON_ALT_BASES, daily_klines, list_usdt_perpetuals
from .scalp_data import BASE_URL, COLUMNS

REPLAY_VERSION = 'auction-replay-v1.2-intraday-management'
ARM_LATENCY = timedelta(minutes=3)
WATCHED_PAIRS = ('SOLUSDT',)          # live M0 universe: BTC, ETH, target + watched
CANDIDATE_REUSE = timedelta(hours=4)  # mirrors auction_service.CANDIDATE_REUSE
BREADTH_SIZE = 20
BREADTH_MIN_LISTING_DAYS = 730
STALE_BREADTH_AFTER = timedelta(hours=2)
INTERVAL_MINUTES = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240}
LIMITS = {'15m': 100, '1h': 220, '4h': 220, '5m': 240}  # = live _timeframe_summary limits
RECENT_BARS = 300  # raw closed bars exposed to structure-detecting plugins
REPLAY_ASSUMPTIONS = {
    'data_quality': 'candles_only (no historical order book / OI / CVD)',
    'arm_latency_minutes': ARM_LATENCY.total_seconds() / 60,
    'watched_pairs_in_m0_regime': list(WATCHED_PAIRS),
    'fvg_zone': 'absent (M0 does not use it)',
    'breadth_universe': f'point-in-time per quarter, top {BREADTH_SIZE} by prior-month '
                        f'median daily quote volume, listed >= {BREADTH_MIN_LISTING_DAYS}d, '
                        'no Alpha-tag filter (no history)',
    'costs': 'live shadow cost model (plan_geometry)',
    'overlap': 'each candidate resolved independently; concurrent positions not netted',
    'management_counterfactuals': (
        'P1 scale 50% at 0.75R then cost-BE/closed-1m structure to 1.5R; '
        'P2 risk cut after 0.5R, scale 40% at 0.75R and 30% at 1.25R, '
        'then trail the 30% runner by 0.5R; both stop-first, costed, max 4h '
        'and flat before the UTC day changes'
    ),
}


# --------------------------------------------------------------------------- data
def interval_klines(symbol: str, interval: str, month: str, cache: str) -> pd.DataFrame | None:
    """Checksummed monthly kline archive; None if the symbol had no archive."""
    relative = f'klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip'
    path = Path(cache) / relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    if not path.exists() or not checksum_path.exists():
        response = requests.get(f'{BASE_URL}/{relative}', timeout=60)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        checksum = requests.get(f'{BASE_URL}/{relative}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        if sha256(response.content).hexdigest() != checksum.text.split()[0]:
            raise ValueError(f'Checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            raw = pd.read_csv(source, header=None)
    if not str(raw.iloc[0, 0]).isdigit():
        raw = raw.iloc[1:]
    raw = raw.iloc[:, :len(COLUMNS)]
    raw.columns = COLUMNS
    raw = raw.astype({'timestamp': 'int64', 'open': float, 'high': float, 'low': float,
                      'close': float, 'volume': float})
    return raw[['timestamp', 'open', 'high', 'low', 'close', 'volume']]


class Bars:
    """Closed bars of one symbol/interval as numpy arrays (open-time indexed)."""

    def __init__(self, symbol: str, interval: str, frame: pd.DataFrame):
        frame = frame.drop_duplicates('timestamp').sort_values('timestamp')
        self.symbol, self.interval = symbol, interval
        self.open_ms = frame.timestamp.to_numpy(dtype='int64')
        self.step_ms = INTERVAL_MINUTES[interval] * 60_000
        self.o = frame.open.to_numpy(float)
        self.h = frame.high.to_numpy(float)
        self.l = frame.low.to_numpy(float)
        self.c = frame.close.to_numpy(float)
        self.v = frame.volume.to_numpy(float)

    def __len__(self):
        return len(self.open_ms)

    def closed_count(self, t_ms: int) -> int:
        """Number of bars whose close (open + step) is <= t."""
        return int(np.searchsorted(self.open_ms + self.step_ms, t_ms, side='right'))

    def rows(self, end: int, n: int) -> list[dict]:
        start = max(0, end - n)
        return [
            {
                'timestamp': datetime.fromtimestamp(self.open_ms[i] / 1000, tz=timezone.utc),
                'open': self.o[i], 'high': self.h[i], 'low': self.l[i],
                'close': self.c[i], 'volume': self.v[i],
            }
            for i in range(start, end)
        ]

    def window(self, start_ms: int, end_ms: int) -> list[dict]:
        """Rows with start <= open_time < end (for the 1m resolver)."""
        lo = int(np.searchsorted(self.open_ms, start_ms, side='left'))
        hi = int(np.searchsorted(self.open_ms, end_ms, side='left'))
        return self.rows(hi, hi - lo)


def load_bars(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp,
              cache: str) -> Bars | None:
    months = pd.period_range(start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None),
                             freq='M')
    frames = [f for f in (interval_klines(symbol, interval, str(m), cache) for m in months)
              if f is not None]
    if not frames:
        return None
    frame = pd.concat(frames)
    start_ms, end_ms = int(start.value // 10**6), int(end.value // 10**6)
    frame = frame[(frame.timestamp >= start_ms) & (frame.timestamp < end_ms)]
    return Bars(symbol, interval, frame) if len(frame) else None


# ---------------------------------------------------------------- universe (PIT)
def _eligible(symbol: str) -> bool:
    return (symbol.endswith('USDT') and symbol not in INDEX_SYMBOLS
            and symbol[:-4] not in NON_ALT_BASES and symbol not in {'BTCUSDT', 'ETHUSDT'})


def select_breadth_universe(as_of: pd.Timestamp, cache: str, candidates: list[str],
                            size: int = BREADTH_SIZE) -> list[str]:
    """Top ``size`` alts by prior-month median daily quote volume, listed long enough.

    Uses only archives published before ``as_of``; delisted symbols stay
    candidates because the archive bucket keeps them.
    """
    rank_month = str((as_of - pd.Timedelta(days=1)).tz_localize(None).to_period('M'))
    listed_by = as_of - pd.Timedelta(days=BREADTH_MIN_LISTING_DAYS)
    eligibility_month = str(listed_by.tz_localize(None).to_period('M'))

    def score(symbol):
        early = daily_klines(symbol, eligibility_month, cache)
        if early is None or early.index[0] > listed_by:
            return symbol, None
        ranked = daily_klines(symbol, rank_month, cache)
        if ranked is None or len(ranked) < 20:
            return symbol, None
        return symbol, float(ranked.quote_volume.median())

    with ThreadPoolExecutor(max_workers=16) as pool:
        scored = [s for s in pool.map(score, candidates) if s[1] is not None]
    return [s for s, _ in sorted(scored, key=lambda s: -s[1])[:size]]


# ------------------------------------------------------------------ replay plan
@dataclass
class ReplayPlan:
    """In-memory stand-in for AuctionShadowPlan accepted by ``resolve_plan``."""
    symbol: str
    strategy_id: str
    direction: str
    zone_kind: str
    zone_low: float
    zone_high: float
    structural_stop: float
    target_r: float
    management_policy: str
    armed_at: datetime
    expires_at: datetime
    position_expires_at: datetime | None
    cost_assumptions: dict
    state: str = 'ARMED'
    triggered_at: datetime | None = None
    entry_price: float | None = None
    target_price: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    closed_at: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ''
    gross_r: float | None = None
    net_r: float | None = None
    trigger_evidence: dict = field(default_factory=dict)

    def save(self, update_fields=None):  # resolver persistence hook: no-op
        return None


# ---------------------------------------------------------------------- engine
class Replay:
    def __init__(self, *, start: pd.Timestamp, end: pd.Timestamp, cache: str,
                 breadth_by_quarter: dict[str, list[str]], warmup_days: int = 61):
        self.start, self.end, self.cache = start, end, cache
        self.data_start = start - pd.Timedelta(days=warmup_days)
        self.breadth_by_quarter = breadth_by_quarter
        self._bars: dict[tuple[str, str], Bars | None] = {}
        self._summary = lru_cache(maxsize=60_000)(self._summary_uncached)

    def bars(self, symbol: str, interval: str) -> Bars | None:
        key = (symbol, interval)
        if key not in self._bars:
            self._bars[key] = load_bars(symbol, interval, self.data_start, self.end, self.cache)
        return self._bars[key]

    def drop(self, symbol: str):
        for key in [k for k in self._bars if k[0] == symbol]:
            del self._bars[key]
        self._summary.cache_clear()

    def _summary_uncached(self, symbol: str, interval: str, end_index: int, limit: int) -> dict:
        from l2_agents.market_intelligence import _summarize_rows

        bars = self.bars(symbol, interval)
        if bars is None or end_index <= 0:
            return {'available': False, 'interval': interval}
        return _summarize_rows(interval, bars.rows(end_index, limit))

    def summary(self, symbol: str, interval: str, t_ms: int, limit: int | None = None) -> dict:
        bars = self.bars(symbol, interval)
        if bars is None:
            return {'available': False, 'interval': interval}
        return self._summary(symbol, interval, bars.closed_count(t_ms), limit or LIMITS[interval])

    def _m0_summaries(self, target: str, t_ms: int, full: bool) -> dict:
        universe = list(dict.fromkeys(['BTCUSDT', 'ETHUSDT', target, *WATCHED_PAIRS]))
        summaries = {}
        for item in universe:
            frames = {'1h': self.summary(item, '1h', t_ms), '4h': self.summary(item, '4h', t_ms)}
            if full or item == target:
                frames['15m'] = self.summary(item, '15m', t_ms)
            summaries[item] = frames
        return summaries

    def snapshot(self, target: str, t: datetime, *, full: bool,
                 include_bars: bool = False) -> dict:
        """Cheap M0-input snapshot, or the full production composition."""
        from l2_agents.market_intelligence import (
            _data_quality, _global_regime, _summarize_rows, _zones, compose_snapshot,
        )
        from l2_agents.trend_state import derive_closed_daily_rows

        t_ms = int(t.timestamp() * 1000)
        summaries = self._m0_summaries(target, t_ms, full)
        instrument = dict(summaries[target])  # never mutate cached summaries
        summaries[target] = instrument
        if not full:
            regime = _global_regime(summaries)
            return {
                'symbol': target, 'global_regime': regime,
                'instrument': {'15m': instrument['15m']},
                'zones': _zones(instrument['15m']),
                'data_quality': _data_quality(instrument, {}, {}, regime, t, candles_only=True),
                'strategy_registry': {'SAI1_FAILED_AUCTION': 'SHADOW_ONLY'},
                'allowed_management_policies': ['P0_INITIAL_STOP'],
                'execution_authorized': False,
            }
        instrument['5m'] = self.summary(target, '5m', t_ms)
        instrument['1d'] = _summarize_rows(
            '1d', derive_closed_daily_rows(instrument['4h'].get('_recent_rows') or []),
            source='derived_from_six_closed_4h_bars_utc',
        )
        quarter = str(pd.Timestamp(t).tz_convert('UTC').tz_localize(None).to_period('Q'))
        breadth = self.breadth_by_quarter.get(quarter, [])
        context = dict(summaries)
        for alt in breadth:
            if alt in context:
                continue
            frame = self.summary(alt, '1h', t_ms)
            last = frame.get('last_timestamp')
            if frame.get('available') and last and (
                t - datetime.fromisoformat(last) > STALE_BREADTH_AFTER + timedelta(hours=1)
            ):
                frame = {'available': False, 'interval': '1h', 'reason': 'stale_or_delisted'}
            context[alt] = {'1h': frame}
        snapshot = compose_snapshot(
            symbol=target, now=t, summaries=summaries, context_summaries=context,
            breadth_universe={'version': f'pit-breadth-{quarter}', 'symbols': breadth},
            depth={}, flow={}, structural={}, candles_only_quality=True,
        )
        if include_bars:
            # Closed 1h/4h bars for plugins that detect their own structure.
            snapshot['recent_bars'] = {}
            for interval in ('1h', '4h'):
                bars = self.bars(target, interval)
                snapshot['recent_bars'][interval] = (
                    bars.rows(bars.closed_count(t_ms), RECENT_BARS) if bars is not None else [])
        return snapshot

    def run_symbol(self, target: str, progress=None) -> list[dict]:
        from l2_agents.mechanical_baseline import (
            global_context_filtered_decision, mechanical_decision, trend_filtered_decision,
        )
        from l2_agents.shadow_auction import plan_geometry, resolve_plan
        from l2_agents.intraday_management import POLICY_IDS, simulate_intraday_policy

        bars15 = self.bars(target, '15m')
        minutes = self.bars(target, '1m')
        if bars15 is None or minutes is None:
            return []
        data_end = datetime.fromtimestamp(
            (minutes.open_ms[-1] + 60_000) / 1000, tz=timezone.utc)
        start_ms, end_ms = int(self.start.value // 10**6), int(self.end.value // 10**6)
        closes = bars15.open_ms + bars15.step_ms
        active: dict[str, datetime] = {}
        records = []

        def loader(start, end):
            return minutes.window(int(start.timestamp() * 1000), int(end.timestamp() * 1000))

        for index in range(len(closes)):
            close_ms = int(closes[index])
            if close_ms < start_ms or close_ms > end_ms:
                continue
            t = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
            if progress and index % 5000 == 0:
                progress(target, t, len(records))
            try:
                decision = mechanical_decision(self.snapshot(target, t, full=False))
            except ValueError:
                continue
            if decision.action != 'ARM':
                continue
            low, high = sorted(float(v) for v in decision.entry_zone)
            key = f'{target}:{decision.direction}:{decision.strategy_id}:{low:.10g}:{high:.10g}'
            if key in active and active[key] > t:
                continue  # same live candidate episode: no second plan
            active[key] = t + CANDIDATE_REUSE

            snapshot = self.snapshot(target, t, full=True)
            m0 = mechanical_decision(snapshot)
            if m0.action != 'ARM' or sorted(m0.entry_zone) != [low, high]:
                raise AssertionError(f'Cheap and full M0 disagree at {target} {t}')
            m1 = trend_filtered_decision(snapshot, m0)
            m3 = global_context_filtered_decision(snapshot, m0)

            armed_at = t + ARM_LATENCY
            plan = ReplayPlan(symbol=target, strategy_id=m0.strategy_id,
                              **plan_geometry(m0.model_dump(), snapshot, armed_at))
            outcome = resolve_plan(plan, now=data_end, rows_loader=loader)
            # A candidate at the right edge may not have its complete trigger
            # or holding window.  Counting it as 0R would reward every policy
            # for missing future data, so it is excluded from inference.
            if outcome in {'NO_DATA', 'INCOMPLETE_DATA'}:
                continue
            management = {}
            if plan.triggered_at and plan.position_expires_at and plan.entry_price is not None:
                management_rows = [
                    row for row in loader(plan.triggered_at, plan.position_expires_at)
                    if row['timestamp'] > plan.triggered_at
                ]
                management = {
                    policy_id.lower(): simulate_intraday_policy(
                        direction=plan.direction,
                        entry=float(plan.entry_price),
                        initial_stop=float(plan.structural_stop),
                        rows=management_rows,
                        costs=plan.cost_assumptions,
                        policy_id=policy_id,
                        opened_at=plan.triggered_at,
                    )
                    for policy_id in POLICY_IDS
                }
            gc = snapshot.get('global_context') or {}
            trend = snapshot.get('trend_state') or {}
            records.append({
                'symbol': target, 'bar_close': t.isoformat(), 'armed_at': armed_at.isoformat(),
                'direction': m0.direction, 'regime': snapshot['global_regime']['state'],
                'm1': m1.action, 'm3': m3.action,
                'global_state': gc.get('state'),
                'global_bias': gc.get('target_bias_score_minus100_100'),
                'global_coverage': gc.get('target_data_coverage_0_1'),
                'breadth_symbols': (gc.get('components') or {}).get('alt_breadth_1h', {}).get('symbols'),
                'trend_regime': trend.get('regime'),
                'outcome': outcome, 'state': plan.state, 'exit_reason': plan.exit_reason,
                'net_r': plan.net_r, 'gross_r': plan.gross_r,
                'mfe_r': plan.mfe_r, 'mae_r': plan.mae_r,
                'management': management,
                'risk_pct': (abs(plan.entry_price - plan.structural_stop) / plan.entry_price * 100
                             if plan.entry_price else None),
                'closed_at': plan.closed_at.isoformat() if plan.closed_at else None,
            })
        return records


def run_plugin(replay: 'Replay', target: str, strategy_id: str, progress=None) -> list[dict]:
    """Generic replay of any registered strategy plugin plus M1/M3 overlays.

    Scans on the plugin's ``scan_interval`` (default 15m), holds at most one
    position per symbol, uses plugin-owned stop/target/hold when provided and
    the production plan geometry and resolver.
    """
    from l2_agents.auction_adjudicator import AuctionDecision
    from l2_agents.mechanical_baseline import (
        global_context_filtered_decision, trend_filtered_decision,
    )
    from l2_agents.shadow_auction import plan_geometry, resolve_plan
    from l2_agents.strategies import strategy_registry

    plugin = strategy_registry.get(strategy_id)
    interval = getattr(plugin, 'scan_interval', '15m')
    scan_bars = replay.bars(target, interval)
    minutes = replay.bars(target, '1m')
    if scan_bars is None or minutes is None:
        return []
    data_end = datetime.fromtimestamp((minutes.open_ms[-1] + 60_000) / 1000, tz=timezone.utc)
    start_ms, end_ms = int(replay.start.value // 10**6), int(replay.end.value // 10**6)
    closes = scan_bars.open_ms + scan_bars.step_ms
    busy_until: datetime | None = None
    records = []

    def loader(start, end):
        return minutes.window(int(start.timestamp() * 1000), int(end.timestamp() * 1000))

    for index in range(len(closes)):
        close_ms = int(closes[index])
        if close_ms < start_ms or close_ms > end_ms:
            continue
        t = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
        if progress and index % 5000 == 0:
            progress(target, t, len(records))
        if busy_until is not None and t < busy_until:
            continue
        snapshot = replay.snapshot(target, t, full=True, include_bars=True)
        scan = plugin.scan(snapshot)
        if not scan.candidates:
            continue
        cand = scan.candidates[0]
        low, high = cand.entry_zone
        m0 = AuctionDecision(
            action='ARM', direction=cand.direction, strategy_id=cand.strategy_id,
            confidence=0.5, data_quality=float((snapshot.get('data_quality') or {}).get('score') or 0.0),
            thesis=list(cand.thesis), counter_thesis=[], entry_zone=[low, high],
            trigger_conditions=list(cand.trigger_conditions),
            invalidation_conditions=list(cand.invalidation_conditions),
            management_policy='P0_INITIAL_STOP', ttl_minutes=cand.ttl_minutes,
            recheck_condition='Next scan bar.', risk_notes=['Research plugin replay.'],
        )
        m1 = trend_filtered_decision(snapshot, m0)
        m3 = global_context_filtered_decision(snapshot, m0)
        armed_at = t + ARM_LATENCY
        overrides = {'structural_stop': cand.stop_price, 'target_r': cand.target_r,
                     'max_hold_minutes': cand.max_hold_minutes,
                     'zone_kind': (cand.metadata or {}).get('zone_kind')}
        plan = ReplayPlan(symbol=target, strategy_id=strategy_id,
                          **plan_geometry(m0.model_dump(), snapshot, armed_at, overrides=overrides))
        outcome = resolve_plan(plan, now=data_end, rows_loader=loader)
        busy_until = plan.closed_at or plan.expires_at
        gc = snapshot.get('global_context') or {}
        records.append({
            'symbol': target, 'strategy_id': strategy_id, 'bar_close': t.isoformat(),
            'armed_at': armed_at.isoformat(), 'direction': m0.direction,
            'regime': snapshot['global_regime']['state'],
            'm1': m1.action, 'm3': m3.action, 'global_state': gc.get('state'),
            'global_bias': gc.get('target_bias_score_minus100_100'),
            'trend_regime': (snapshot.get('trend_state') or {}).get('regime'),
            'outcome': outcome, 'state': plan.state, 'exit_reason': plan.exit_reason,
            'net_r': plan.net_r, 'gross_r': plan.gross_r, 'mfe_r': plan.mfe_r, 'mae_r': plan.mae_r,
            'target_r': plan.target_r,
            'risk_pct': (abs(plan.entry_price - plan.structural_stop) / plan.entry_price * 100
                         if plan.entry_price else None),
            'closed_at': plan.closed_at.isoformat() if plan.closed_at else None,
        })
    return records


def quarters(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Period]:
    return list(pd.period_range(start.tz_localize(None), (end - pd.Timedelta(days=1)).tz_localize(None),
                                freq='Q'))


def build_breadth_by_quarter(start, end, cache) -> dict[str, list[str]]:
    candidates = [s for s in list_usdt_perpetuals() if _eligible(s)]
    return {
        str(q): select_breadth_universe(pd.Timestamp(q.start_time, tz='UTC'), cache, candidates)
        for q in quarters(start, end)
    }
