"""S121 forward paper tracker: short new listings with a funding guard.

Protocol: docs/research/s121_listing_short_forward/protocol.json (frozen 2026-11-02).
Stateless: every run rebuilds all paper trades from Binance public REST data.
The listing registry is append-only so delisted symbols stay tracked.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from django.conf import settings

from .broad_universe import INDEX_SYMBOLS, NON_ALT_BASES
from .oos_data import rest_funding

FAPI = 'https://fapi.binance.com'
FORWARD_START = pd.Timestamp('2026-11-02', tz='UTC')
NOTIONAL = 25.0
FEE_BPS, SLIP_BPS = 5.0, 30.0
STOP_PCT, HOLD_DAYS = 0.35, 14
ENTRY_GUARD_MIN_DAY1_FUNDING = -0.0010
FUNDING_EXIT_FLOOR = -0.03
MAX_OPEN = 5
DAY = pd.Timedelta(days=1)


def paper_dir() -> Path:
    path = Path(settings.BASE_DIR).parent / 'data' / 'paper_forward' / 's121'
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------- simulation
def simulate_guarded(bars: pd.DataFrame, funding: pd.Series, now: pd.Timestamp) -> dict:
    """One paper trade on closed daily bars (index = UTC day open).

    Returns a dict with status SKIPPED / PENDING / OPEN / CLOSED.
    """
    if len(bars) < 2:
        return {'status': 'PENDING', 'reason': 'waiting_for_second_bar'}
    def settled(start, end):
        if funding.empty:
            return funding
        return funding[(funding.index >= start) & (funding.index < end)]

    day1 = settled(bars.index[0], bars.index[0] + DAY)
    if float(day1.sum()) < ENTRY_GUARD_MIN_DAY1_FUNDING:
        return {'status': 'SKIPPED', 'reason': 'entry_guard_day1_funding', 'day1_funding': float(day1.sum())}

    slip = SLIP_BPS / 10_000
    raw_entry = float(bars.open.iloc[1])
    entry_time = bars.index[1]
    stop_price = raw_entry * (1 + STOP_PCT)
    last_planned = 1 + HOLD_DAYS - 1
    result = {'entry_time': entry_time, 'raw_entry': raw_entry}
    for i in range(1, len(bars)):
        day_end = bars.index[i] + DAY
        if float(bars.high.iloc[i]) >= stop_price:
            raw_exit, reason = max(stop_price, float(bars.open.iloc[i])), 'STOP'
        elif float(settled(entry_time, day_end).sum()) <= FUNDING_EXIT_FLOOR:
            raw_exit, reason = float(bars.close.iloc[i]), 'FUNDING_EXIT'
        elif i == last_planned:
            raw_exit, reason = float(bars.close.iloc[i]), 'TIME'
        else:
            continue
        return {**result, **_close(raw_entry, raw_exit, reason, entry_time, day_end,
                                   float(settled(entry_time, day_end).sum()), slip)}
    mark = float(bars.close.iloc[-1])
    open_funding = float(settled(entry_time, bars.index[-1] + DAY).sum())
    unrealized = (raw_entry * (1 - slip) - mark) / raw_entry + open_funding - FEE_BPS / 10_000
    return {**result, 'status': 'OPEN', 'mark': mark, 'unrealized_net': unrealized,
            'funding': open_funding, 'days_held': len(bars) - 1}


def _close(raw_entry, raw_exit, reason, entry_time, exit_time, funding_sum, slip) -> dict:
    gross = (raw_entry * (1 - slip) - raw_exit * (1 + slip)) / raw_entry
    net = gross - 2 * FEE_BPS / 10_000 + funding_sum
    return {'status': 'CLOSED', 'reason': reason, 'raw_exit': raw_exit,
            'exit_time': exit_time, 'gross': gross, 'funding': funding_sum, 'net': net}


def apply_concurrency(trades: list[dict]) -> list[dict]:
    """Skip a new entry while MAX_OPEN earlier paper positions are still open."""
    taken, open_exits = [], []
    for t in sorted(trades, key=lambda x: x.get('entry_time') or pd.Timestamp.max.tz_localize('UTC')):
        if t['status'] not in ('OPEN', 'CLOSED'):
            taken.append(t)
            continue
        open_exits = [e for e in open_exits if e is None or e > t['entry_time']]
        if len(open_exits) >= MAX_OPEN:
            taken.append({**t, 'status': 'SKIPPED', 'reason': 'concurrency_cap'})
            continue
        open_exits.append(t.get('exit_time'))
        taken.append(t)
    return taken


# ------------------------------------------------------------------- data
def _eligible(symbol: str, base: str) -> bool:
    return symbol not in {'BTCUSDT', 'ETHUSDT'} and symbol not in INDEX_SYMBOLS and base not in NON_ALT_BASES


def discover(session: requests.Session) -> list[dict]:
    """Append-only registry of eligible listings with onboardDate >= FORWARD_START."""
    registry_path = paper_dir() / 'listings.json'
    registry = {r['symbol']: r for r in json.loads(registry_path.read_text())} if registry_path.exists() else {}
    info = session.get(f'{FAPI}/fapi/v1/exchangeInfo', timeout=30).json()
    for s in info.get('symbols', []):
        onboard = pd.Timestamp(int(s.get('onboardDate', 0)), unit='ms', tz='UTC')
        if (s.get('contractType') == 'PERPETUAL' and s.get('quoteAsset') == 'USDT'
                and onboard >= FORWARD_START and _eligible(s['symbol'], s.get('baseAsset', ''))
                and s['symbol'] not in registry):
            registry[s['symbol']] = {'symbol': s['symbol'], 'onboard': onboard.isoformat()}
    registry_path.write_text(json.dumps(sorted(registry.values(), key=lambda r: r['onboard']), indent=2))
    return sorted(registry.values(), key=lambda r: r['onboard'])


def daily_bars(session, symbol: str, start: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
    rows = session.get(f'{FAPI}/fapi/v1/klines', params={
        'symbol': symbol, 'interval': '1d', 'startTime': int(start.floor('D').value // 10**6), 'limit': 60,
    }, timeout=30).json()
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=['open', 'high', 'low', 'close'])
    df = pd.DataFrame([r[:7] for r in rows], columns=['t', 'open', 'high', 'low', 'close', 'volume', 'ct'])
    df = df[df.ct.astype('int64') < int(now.value // 10**6)]  # closed bars only
    df.index = pd.to_datetime(df.t.astype('int64'), unit='ms', utc=True)
    return df[['open', 'high', 'low', 'close']].astype(float)


def run(now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz='UTC')
    session = requests.Session()
    listings = discover(session)
    btc = daily_bars(session, 'BTCUSDT', FORWARD_START - DAY, now)
    trades = []
    for item in listings:
        onboard = pd.Timestamp(item['onboard'])
        bars = daily_bars(session, item['symbol'], onboard, now)
        funding = (rest_funding(item['symbol'], onboard.floor('D'), now, session)
                   if len(bars) else pd.Series(dtype=float))
        trade = {'symbol': item['symbol'], 'onboard': item['onboard'],
                 **simulate_guarded(bars, funding, now)}
        if trade['status'] == 'CLOSED':
            try:
                exit_day = trade['exit_time'] - DAY
                btc_ret = float(btc.close.loc[exit_day] / btc.open.loc[trade['entry_time']] - 1)
                trade['hedged_net'] = trade['net'] + btc_ret
            except KeyError:
                trade['hedged_net'] = None
        trades.append(trade)
    trades = apply_concurrency(trades)
    closed = [t for t in trades if t['status'] == 'CLOSED']
    nets = np.array([t['net'] for t in closed]) if closed else np.array([])
    summary = {
        'protocol': 'S121 v1.0.0', 'as_of': now.isoformat(), 'listings_tracked': len(listings),
        'open': sum(t['status'] == 'OPEN' for t in trades),
        'closed': len(closed), 'skipped': sum(t['status'] == 'SKIPPED' for t in trades),
        'pending': sum(t['status'] == 'PENDING' for t in trades),
        'mean_net_pct': round(float(nets.mean()) * 100, 3) if len(nets) else None,
        'win_rate': round(float((nets > 0).mean()), 3) if len(nets) else None,
        'paper_pnl_usd': round(float(nets.sum()) * NOTIONAL, 2) if len(nets) else 0.0,
        'review_stage': ('gate_ready' if len(closed) >= 50 else 'first_look' if len(closed) >= 30
                         else 'collecting'),
    }
    state = {'summary': summary, 'trades': trades}
    (paper_dir() / 'state.json').write_text(json.dumps(state, indent=2, default=str))
    return summary
