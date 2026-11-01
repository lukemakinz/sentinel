"""Prospective journal for setup search: record, resolve, summarize.

Every MSS-confirmed setup the scanner sees is stored, including ones first
seen after they already ended, so outcome statistics are not limited to
setups that happened to be alerted. Resolution uses closed 15m bars with the
same conservative rules as the scanner: limit fill, stop before target in a
bar, TP1 = nearest BSL, 72h time exit, stress-cost R.
"""
from __future__ import annotations

from datetime import timedelta
import logging

import pandas as pd
import requests
from django.db import IntegrityError
from django.utils import timezone

from .models import SetupObservation
from .ob_liquidity_reversal import OBLiquidityReversalConfig, stress_net_r
from .setup_search import _get, klines_to_bars

logger = logging.getLogger(__name__)
SETUP_STATUSES = {'WAIT_RETEST', 'RR_TOO_LOW', 'IN_POSITION', 'RECENT_RESULT'}
STRATEGY = OBLiquidityReversalConfig()
EPISODE_LIFETIME = timedelta(minutes=STRATEGY.trigger_minutes * (STRATEGY.mss_window_bars + 1))


def _ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def record_scan(report: dict) -> list[SetupObservation]:
    """Store new setups/episodes; return newly created rows for alerting."""
    created = []
    for row in report['rows']:
        if row['status'] in SETUP_STATUSES and row.get('mss_time'):
            kind, event = 'SETUP', row['mss_time']
        elif row['status'] == 'WAIT_MSS':
            kind, event = 'EPISODE', row['sweep_time']
        else:
            continue
        key = f"{kind}:{row['symbol']}:{row['side']}:{event}"
        defaults = {
            'last_status': row['status'],
            'score': row['score'],
            'payload': row,
        }
        observation = SetupObservation.objects.filter(key=key).first()
        if observation is not None:
            # Features and context belong to the moment the setup was first seen;
            # variants are owned by the resolver. Later scans only refresh status.
            kept = {k: observation.payload[k] for k in ('features', 'variants', 'variants_done')
                    if k in observation.payload}
            defaults['payload'] = {**row, **kept}
            for field, value in defaults.items():
                setattr(observation, field, value)
            observation.save(update_fields=[*defaults, 'last_seen'])
            continue
        try:
            observation = SetupObservation.objects.create(
                key=key, kind=kind, symbol=row['symbol'], side=row['side'],
                event_time=_ts(event).to_pydatetime(), first_status=row['status'],
                entry_limit=row.get('entry_limit'), stop_loss=row.get('stop_loss'),
                tp1=row.get('tp1_bsl'), rr_tp1=row.get('rr_tp1_net_stress'),
                strict_rr_ok=bool(row.get('checklist', {}).get('rr_tp1_min_1_3')),
                absorption=row.get('absorption') or '', **defaults,
            )
        except IntegrityError:  # a concurrent cycle stored it first
            continue
        created.append(observation)
        if kind == 'SETUP':
            SetupObservation.objects.filter(
                kind='EPISODE', symbol=row['symbol'], side=row['side'],
                event_time=_ts(row['sweep_time']).to_pydatetime(), outcome='OPEN',
            ).update(outcome='MSS', resolved_at=timezone.now())
    return created


def resolve_path(bars: pd.DataFrame, obs: SetupObservation) -> dict:
    """Outcome of one setup on closed 15m bars after its MSS close."""
    side = 1 if obs.side == 'LONG' else -1
    limit, stop, tp1 = obs.entry_limit, obs.stop_loss, obs.tp1
    after = bars.loc[bars.index > _ts(obs.event_time)]
    ttl = timedelta(minutes=STRATEGY.limit_ttl_minutes)
    max_hold = timedelta(hours=STRATEGY.max_hold_hours)
    filled_at = None
    for timestamp, row in after.iterrows():
        if filled_at is None:
            if timestamp - _ts(obs.event_time) > ttl:
                return {'outcome': 'EXPIRED', 'at': timestamp}
            if not ((row.low <= limit) if side == 1 else (row.high >= limit)):
                continue
            filled_at = timestamp
        if (row.low <= stop) if side == 1 else (row.high >= stop):
            return {
                'outcome': 'STOPPED', 'at': timestamp, 'filled_at': filled_at,
                'net_r': stress_net_r(side, limit, stop, stop, STRATEGY),
            }
        if (row.high >= tp1) if side == 1 else (row.low <= tp1):
            return {'outcome': 'TP1_HIT', 'at': timestamp, 'filled_at': filled_at,
                    'net_r': stress_net_r(side, limit, stop, tp1, STRATEGY)}
        if timestamp - filled_at >= max_hold:
            return {'outcome': 'TIME', 'at': timestamp, 'filled_at': filled_at,
                    'net_r': stress_net_r(side, limit, stop, float(row.close), STRATEGY)}
    if filled_at is not None:
        return {'outcome': 'FILLED', 'filled_at': filled_at}
    return {'outcome': 'OPEN'}


ENTRY_VARIANTS = ('fvg_edge', 'fvg_mid', 'mss_market')
EXIT_VARIANTS = ('tp1', 'ext3r', 'ext3r_partial2r')
TERMINAL = {'TP1_HIT', 'TARGET', 'STOPPED', 'TIME', 'EXPIRED', 'NO_TARGET', 'INVALID'}


def _net_r(side, entry, stop, exit_price, market_entry):
    """Stress net R; a market entry pays taker + slippage instead of maker."""
    r = stress_net_r(side, entry, stop, exit_price, STRATEGY)
    if market_entry:
        extra = (STRATEGY.stress_taker_bps - STRATEGY.stress_maker_bps
                 + STRATEGY.stress_slippage_bps) / 10000 * entry
        risk = side * (entry - stop)
        r -= extra / risk if risk > 0 else 0.0
    return r


def resolve_variant(bars: pd.DataFrame, obs: SetupObservation, entry_kind: str,
                    exit_kind: str) -> dict:
    """One counterfactual entry/exit combination on the same closed 15m bars."""
    side = 1 if obs.side == 'LONG' else -1
    row, features = obs.payload, obs.payload.get('features') or {}
    stop = obs.stop_loss
    entry = {'fvg_edge': obs.entry_limit, 'fvg_mid': features.get('fvg_mid'),
             'mss_market': None}[entry_kind]
    target = obs.tp1 if exit_kind == 'tp1' else row.get('first_bsl_min_3r')
    after = bars.loc[bars.index > _ts(obs.event_time)]
    if target is None or stop is None or (entry_kind != 'mss_market' and entry is None):
        return {'outcome': 'NO_TARGET'}
    if entry_kind == 'mss_market':
        if after.empty:
            return {'outcome': 'OPEN'}
        entry = float(after.iloc[0].open)  # next bar open after the MSS close
    if side * (entry - stop) <= 0 or side * (target - entry) <= 0:
        return {'outcome': 'INVALID'}
    partial = (entry + side * 2 * abs(entry - stop)) if exit_kind == 'ext3r_partial2r' else None
    ttl = timedelta(minutes=STRATEGY.limit_ttl_minutes)
    max_hold = timedelta(hours=STRATEGY.max_hold_hours)
    market = entry_kind == 'mss_market'
    filled_at, banked, partial_taken = (after.index[0] if market else None), 0.0, False
    for timestamp, bar in after.iterrows():
        if filled_at is None:
            if timestamp - _ts(obs.event_time) > ttl:
                return {'outcome': 'EXPIRED'}
            if not ((bar.low <= entry) if side == 1 else (bar.high >= entry)):
                continue
            filled_at = timestamp
        weight = 0.5 if partial_taken else 1.0
        if (bar.low <= stop) if side == 1 else (bar.high >= stop):
            return {'outcome': 'STOPPED', 'net_r': round(
                banked + weight * _net_r(side, entry, stop, stop, market), 4,
            )}
        if partial is not None and not partial_taken and (
                (bar.high >= partial) if side == 1 else (bar.low <= partial)):
            banked = 0.5 * _net_r(side, entry, stop, partial, market)
            partial_taken, weight = True, 0.5
        if (bar.high >= target) if side == 1 else (bar.low <= target):
            return {'outcome': 'TARGET', 'net_r': round(
                banked + weight * _net_r(side, entry, stop, target, market), 4)}
        if timestamp - filled_at >= max_hold:
            return {'outcome': 'TIME', 'net_r': round(
                banked + weight * _net_r(side, entry, stop, float(bar.close), market), 4)}
    return {'outcome': 'FILLED' if filled_at is not None else 'OPEN'}


def resolve_variants(bars: pd.DataFrame, obs: SetupObservation) -> dict:
    return {f'{e}+{x}': resolve_variant(bars, obs, e, x)
            for e in ENTRY_VARIANTS for x in EXIT_VARIANTS}


def resolve_open(session=None, now=None) -> list[SetupObservation]:
    """Advance open rows; return rows that reached a final outcome."""
    session = session or requests.Session()
    now = now or pd.Timestamp.now(tz='UTC')
    finished = []
    stale_episodes = SetupObservation.objects.filter(
        kind='EPISODE', outcome='OPEN', event_time__lt=now - EPISODE_LIFETIME)
    stale_episodes.update(outcome='NO_MSS', resolved_at=timezone.now())
    horizon = now - timedelta(minutes=STRATEGY.limit_ttl_minutes) - timedelta(
        hours=STRATEGY.max_hold_hours + 1)
    for obs in SetupObservation.objects.filter(kind='SETUP', event_time__gte=horizon):
        variants_done = obs.payload.get('variants_done', False)
        if obs.outcome not in {'OPEN', 'FILLED'} and variants_done:
            continue
        if None in (obs.entry_limit, obs.stop_loss, obs.tp1):
            continue
        start_ms = int(_ts(obs.event_time).value // 10**6)
        try:
            rows = _get(session, '/fapi/v1/klines', {
                'symbol': obs.symbol, 'interval': '15m', 'startTime': start_ms, 'limit': 500})
        except requests.RequestException as exc:
            # Leave it open; the next cycle retries. One outage must not stall the rest.
            logger.warning('Setup resolve skipped for %s: %s', obs.key, exc)
            continue
        bars = klines_to_bars(rows, 15, now)
        variants = resolve_variants(bars, obs)
        obs.payload = {**obs.payload, 'variants': variants,
                       'variants_done': all(v['outcome'] in TERMINAL for v in variants.values())}
        if obs.outcome not in {'OPEN', 'FILLED'}:
            obs.save(update_fields=['payload'])
            continue
        result = resolve_path(bars, obs)
        fields = ['outcome', 'payload']
        obs.outcome = result['outcome']
        if result.get('filled_at') is not None and obs.filled_at is None:
            obs.filled_at = result['filled_at'].to_pydatetime()
            fields.append('filled_at')
        if result['outcome'] not in {'OPEN', 'FILLED'}:
            obs.resolved_at = result['at'].to_pydatetime()
            obs.net_r = result.get('net_r')
            fields += ['resolved_at', 'net_r']
            finished.append(obs)
        obs.save(update_fields=fields)
    return finished


def journal_summary(since=None) -> dict:
    """Prospective outcome statistics; strict-rule trades reported separately."""
    rows = SetupObservation.objects.filter(kind='SETUP')
    if since is not None:
        rows = rows.filter(event_time__gte=since)
    episodes = SetupObservation.objects.filter(kind='EPISODE')
    if since is not None:
        episodes = episodes.filter(event_time__gte=since)

    def stats(queryset):
        closed = [o.net_r for o in queryset if o.net_r is not None]
        wins = [r for r in closed if r > 0]
        losses = [r for r in closed if r <= 0]
        return {
            'setups': queryset.count(),
            'filled_closed': len(closed),
            'expired': queryset.filter(outcome='EXPIRED').count(),
            'open': queryset.filter(outcome__in=['OPEN', 'FILLED']).count(),
            'win_rate': round(len(wins) / len(closed), 3) if closed else None,
            'mean_net_r': round(sum(closed) / len(closed), 3) if closed else None,
            'total_net_r': round(sum(closed), 3),
            'profit_factor': round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) else None,
        }

    variant_r = {}
    for obs in rows:
        for name, v in (obs.payload.get('variants') or {}).items():
            if v.get('net_r') is not None:
                variant_r.setdefault(name, []).append(v['net_r'])
    variants = {
        name: {'closed': len(r), 'mean_net_r': round(sum(r) / len(r), 3),
               'win_rate': round(sum(x > 0 for x in r) / len(r), 3)}
        for name, r in sorted(variant_r.items())
    }
    return {
        'variants': variants,
        'strict_rr_1_3': stats(rows.filter(strict_rr_ok=True)),
        'all_setups_to_tp1': stats(rows),
        'episodes': {
            'total': episodes.count(),
            'reached_mss': episodes.filter(outcome='MSS').count(),
            'no_mss': episodes.filter(outcome='NO_MSS').count(),
        },
    }
