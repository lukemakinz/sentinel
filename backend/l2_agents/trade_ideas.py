"""Assessment and journaling of the user's own trade ideas (decision support).

Sentinel never places these trades.  It scores economics and context with the
same frozen rules as the research stack (cost in R, M1 trend alignment, M3
global context), stores the idea, and later resolves it on Binance 1m candles,
so the user can measure whether their decisions and the verdicts carry edge.

Verdict rules v1 (frozen; risk hygiene, not a profit promise):
  RED    cost > 0.25 R, or M1 aligned < -0.25, or M3 aligned < -0.45
  YELLOW cost > 0.15 R, or M3 OPPOSED, or target < 1.5 R, or no trend data
  GREEN  otherwise
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import requests
from django.utils import timezone

FAPI = 'https://fapi.binance.com'
VERDICT_VERSION = 'trade-idea-verdict-v1'
TAKER_BPS, MAKER_BPS, SLIP_BPS = 5.0, 2.0, 5.0
MARKET_TOLERANCE = 0.002     # entry within 0.2% of price at creation = market order
TRIGGER_WINDOW = timedelta(hours=24)
MAX_HOLD = timedelta(hours=72)


def normalize_symbol(raw: str) -> str:
    symbol = raw.upper().replace('/', '').replace('-', '')
    return symbol if symbol.endswith('USDT') else f'{symbol}USDT'


def current_price(symbol: str, session=None) -> float:
    session = session or requests.Session()
    data = session.get(f'{FAPI}/fapi/v1/ticker/price', params={'symbol': symbol}, timeout=10).json()
    if 'price' not in data:
        raise ValueError(f'Unknown Binance USD-M symbol: {symbol}')
    return float(data['price'])


def order_type(direction: str, entry: float, price: float | None) -> str:
    """MARKET near the price; LIMIT = better price (pullback); STOP_ENTRY = breakout."""
    if price is None or abs(entry - price) / price <= MARKET_TOLERANCE:
        return 'MARKET'
    below = entry < price
    return 'LIMIT' if (direction.upper() == 'LONG') == below else 'STOP_ENTRY'


def assess(symbol: str, direction: str, entry: float, stop: float, target: float | None = None,
           risk_usd: float = 1.25, price: float | None = None, snapshot: dict | None = None) -> dict:
    """Pure assessment given a market snapshot (built live when not supplied)."""
    from .global_context import candidate_alignment
    from .mechanical_baseline import trend_alignment_score

    direction = direction.upper()
    if direction not in {'LONG', 'SHORT'}:
        raise ValueError('Kierunek musi być long albo short.')
    if (direction == 'LONG' and not stop < entry) or (direction == 'SHORT' and not stop > entry):
        raise ValueError('Stop musi być po stronie ryzyka (long: poniżej wejścia, short: powyżej).')
    if target is not None and ((direction == 'LONG' and target <= entry)
                               or (direction == 'SHORT' and target >= entry)):
        raise ValueError('Target musi być po stronie zysku.')
    if snapshot is None:
        from .market_intelligence import MarketSnapshotBuilder
        snapshot = MarketSnapshotBuilder().build(symbol)

    risk = abs(entry - stop)
    risk_pct = risk / entry * 100
    cost_r = (2 * (TAKER_BPS + SLIP_BPS) / 10_000) / (risk / entry)
    rr = abs(target - entry) / risk if target is not None else None
    m1, m1_tfs = trend_alignment_score(snapshot, direction)
    m3 = candidate_alignment(snapshot.get('global_context') or {}, direction)
    m3_score = m3.get('aligned_score_minus1_1')

    red, yellow = [], []
    if cost_r > 0.25:
        red.append(f'koszt {cost_r:.2f}R > 0.25R (stop za ciasny: {risk_pct:.2f}%)')
    elif cost_r > 0.15:
        yellow.append(f'koszt {cost_r:.2f}R > 0.15R')
    if m1 is None:
        yellow.append('brak danych trendu (M1) dla tego symbolu')
    elif m1 < -0.25:
        red.append(f'trend 1h/4h/1d przeciw (M1 {m1:+.2f})')
    if m3_score is not None and m3_score < -0.45:
        red.append(f'kontekst globalny mocno przeciw (M3 {m3_score:+.2f})')
    elif m3.get('status') == 'OPPOSED':
        yellow.append(f'kontekst globalny przeciw (M3 {m3_score:+.2f})')
    if rr is not None and rr < 1.5:
        yellow.append(f'target tylko {rr:.2f}R')
    verdict = 'RED' if red else 'YELLOW' if yellow else 'GREEN'
    quantity = risk_usd / risk
    return {
        'version': VERDICT_VERSION, 'verdict': verdict, 'red': red, 'yellow': yellow,
        'risk_pct': round(risk_pct, 3), 'cost_r': round(cost_r, 3),
        'rr': round(rr, 2) if rr is not None else None,
        'm1_aligned': round(m1, 3) if m1 is not None else None, 'm1_timeframes': m1_tfs,
        'm3_status': m3.get('status'), 'm3_aligned': m3_score,
        'global_state': (snapshot.get('global_context') or {}).get('state'),
        'trend_regime': (snapshot.get('trend_state') or {}).get('regime'),
        'quantity': quantity, 'notional_usd': round(quantity * entry, 2), 'risk_usd': risk_usd,
        'price_at_creation': price,
        'order_type': order_type(direction, entry, price),
        'snapshot_hash': snapshot.get('snapshot_hash'),
    }


def create_idea(symbol: str, direction: str, entry: float, stop: float,
                target: float | None = None, risk_usd: float = 1.25, source: str = 'telegram'):
    from .models import TradeIdea

    symbol = normalize_symbol(symbol)
    price = current_price(symbol)
    result = assess(symbol, direction, entry, stop, target, risk_usd, price=price)
    return TradeIdea.objects.create(
        source=source, symbol=symbol, direction=direction.upper(), entry=entry, stop=stop,
        target=target, risk_usd=risk_usd, verdict=result['verdict'], assessment=result,
    )


# ------------------------------------------------------------------ outcomes
def _minutes(session, symbol: str, start, end) -> pd.DataFrame:
    rows, cursor, end_ms = [], int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    while cursor < end_ms:
        batch = session.get(f'{FAPI}/fapi/v1/klines', params={
            'symbol': symbol, 'interval': '1m', 'startTime': cursor, 'endTime': end_ms - 1,
            'limit': 1500}, timeout=20).json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 60_000
    if not rows:
        return pd.DataFrame(columns=['open', 'high', 'low', 'close'])
    df = pd.DataFrame([r[:7] for r in rows], columns=['t', 'open', 'high', 'low', 'close', 'v', 'ct'])
    df = df[df.ct.astype('int64') < int(timezone.now().timestamp() * 1000)]  # closed bars only
    df.index = pd.to_datetime(df.t.astype('int64'), unit='ms', utc=True)
    return df[['open', 'high', 'low', 'close']].astype(float)


def simulate_idea(idea, bars: pd.DataFrame, now) -> dict:
    """Stateless outcome on closed 1m bars after creation (same-bar stop first)."""
    d = 1 if idea.direction == 'LONG' else -1
    kind = (idea.assessment or {}).get('order_type') or 'MARKET'
    after = bars[bars.index >= pd.Timestamp(idea.created_at)]
    trigger_i = None
    for i, (ts, row) in enumerate(after.iterrows()):
        if ts > pd.Timestamp(idea.created_at) + TRIGGER_WINDOW:
            break
        if kind == 'MARKET':
            hit = True
        elif kind == 'LIMIT':  # resting order: requires a trade-through
            hit = row.low < idea.entry if d > 0 else row.high > idea.entry
        else:  # STOP_ENTRY breakout
            hit = row.high >= idea.entry if d > 0 else row.low <= idea.entry
        if hit:
            trigger_i = i
            break
    if trigger_i is None:
        expired = now >= idea.created_at + TRIGGER_WINDOW
        return {'state': 'EXPIRED' if expired else 'PENDING'}
    trig_ts = after.index[trigger_i]
    row = after.iloc[trigger_i]
    if kind == 'MARKET':
        entry, entry_fee = float(row.close) * (1 + d * SLIP_BPS / 10_000), TAKER_BPS
    elif kind == 'LIMIT':
        entry, entry_fee = idea.entry, MAKER_BPS
    else:  # gap through the trigger fills at the worse open
        raw = max(idea.entry, float(row.open)) if d > 0 else min(idea.entry, float(row.open))
        entry, entry_fee = raw * (1 + d * SLIP_BPS / 10_000), TAKER_BPS
    risk = abs(entry - idea.stop)
    if risk <= 0 or (d > 0 and entry <= idea.stop) or (d < 0 and entry >= idea.stop):
        return {'state': 'CLOSED', 'triggered_at': trig_ts, 'closed_at': trig_ts,
                'exit_price': entry, 'exit_reason': 'INVALID', 'net_r': 0.0}
    deadline = trig_ts + MAX_HOLD
    for ts, row in after.iloc[trigger_i + 1:].iterrows():
        if ts >= deadline:
            break
        stop_hit = row.low <= idea.stop if d > 0 else row.high >= idea.stop
        tgt_hit = idea.target is not None and (row.high >= idea.target if d > 0 else row.low <= idea.target)
        if stop_hit:
            exit_price, fee, reason = idea.stop * (1 - d * SLIP_BPS / 10_000), TAKER_BPS, 'STOP'
        elif tgt_hit:
            exit_price, fee, reason = idea.target, MAKER_BPS, 'TARGET'
        else:
            continue
        return _closed(d, entry, exit_price, risk, entry_fee, fee, reason, trig_ts, ts)
    if now >= deadline and len(after.iloc[trigger_i + 1:]):
        tail = after[(after.index > trig_ts) & (after.index < deadline)]
        if len(tail) and tail.index[-1] >= deadline - timedelta(minutes=2):
            exit_price = float(tail.close.iloc[-1]) * (1 - d * SLIP_BPS / 10_000)
            return _closed(d, entry, exit_price, risk, entry_fee, TAKER_BPS, 'TIME', trig_ts, tail.index[-1])
    return {'state': 'TRIGGERED', 'triggered_at': trig_ts}


def _closed(d, entry, exit_price, risk, entry_fee, exit_fee, reason, trig_ts, ts) -> dict:
    gross = d * (exit_price - entry) / risk
    fees = (entry * entry_fee + exit_price * exit_fee) / 10_000 / risk
    return {'state': 'CLOSED', 'triggered_at': trig_ts, 'closed_at': ts, 'exit_price': exit_price,
            'exit_reason': reason, 'net_r': round(gross - fees, 4)}


def resolve_open_ideas(now=None) -> dict:
    from .models import TradeIdea

    now = now or timezone.now()
    session = requests.Session()
    counts: dict[str, int] = {}
    for idea in TradeIdea.objects.filter(state__in=('PENDING', 'TRIGGERED')):
        end = min(now, idea.created_at + TRIGGER_WINDOW + MAX_HOLD + timedelta(hours=1))
        bars = _minutes(session, idea.symbol, idea.created_at - timedelta(minutes=1), end)
        result = simulate_idea(idea, bars, now)
        for key, value in result.items():
            setattr(idea, key, value.to_pydatetime() if hasattr(value, 'to_pydatetime') else value)
        idea.save()
        counts[idea.state] = counts.get(idea.state, 0) + 1
    return counts


def journal_stats() -> dict:
    from .models import TradeIdea

    ideas = list(TradeIdea.objects.all())
    closed = [i for i in ideas if i.state == 'CLOSED' and i.net_r is not None and i.exit_reason != 'INVALID']

    def block(items):
        r = [i.net_r for i in items]
        return {'n': len(r), 'mean_r': round(sum(r) / len(r), 3) if r else None,
                'win_rate': round(sum(x > 0 for x in r) / len(r), 3) if r else None,
                'total_r': round(sum(r), 2)}
    return {
        'ideas': len(ideas), 'pending': sum(i.state == 'PENDING' for i in ideas),
        'open': sum(i.state == 'TRIGGERED' for i in ideas),
        'expired': sum(i.state == 'EXPIRED' for i in ideas),
        'closed': block(closed),
        'by_verdict': {v: block([i for i in closed if i.verdict == v]) for v in ('GREEN', 'YELLOW', 'RED')},
    }
