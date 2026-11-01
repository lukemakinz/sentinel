"""Live setup search for the OB Liquidity Reversal checklist (S112/S113 rules).

Scans liquid Binance USD-M altcoin perpetuals and reports, per symbol and
side, how far the 7-point checklist has progressed and what must happen next.
It reuses the backtested state machine (``scan_long_bars``) on closed bars, so
a live status means exactly what the replay meant.

This is an observation tool, not a trade signal: S112 and S113 showed no edge
after costs. It never places orders.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pandas as pd
import requests

from .ob_liquidity_reversal import (
    OBLiquidityReversalConfig,
    mirror,
    scan_long_bars,
    stress_net_r,
)
from .strong_level_retest import prepare_four_hour_bars

BINANCE_FAPI = 'https://fapi.binance.com'
# Majors are context; stablecoins and gold tokens are not altcoins.
EXCLUDED_BASES = {'BTC', 'ETH', 'USDC', 'FDUSD', 'TUSD', 'BUSD', 'USDP', 'DAI',
                  'PAXG', 'XAUT'}
CHECKLIST = (
    'trend_przed_setupem_1h',
    'cena_w_strefie_ob',
    'sweep_ssl',
    'mss',
    'displacement_fvg',
    'retest_wejscie',
    'rr_tp1_min_1_3',
)
# Lower number = more actionable; used to sort the report.
STATUS_PRIORITY = {
    'IN_POSITION': 0, 'WAIT_RETEST': 1, 'RR_TOO_LOW': 2, 'WAIT_MSS': 3,
    'WAIT_SWEEP': 4, 'APPROACHING_ZONE': 5, 'RECENT_RESULT': 6, 'NO_SETUP': 9,
}


@dataclass(frozen=True)
class SetupSearchConfig:
    min_quote_volume_usd: float = 20_000_000
    max_symbols: int = 60
    approach_atr: float = 4.0
    bars_15m: int = 500
    bars_1h: int = 500
    bars_4h: int = 200
    recent_result_hours: int = 24
    strategy: OBLiquidityReversalConfig = OBLiquidityReversalConfig()


def _get(session, path, params=None):
    response = session.get(f'{BINANCE_FAPI}{path}', params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def fetch_universe(session, config: SetupSearchConfig) -> list[str]:
    """Trading USDT perpetual altcoins above the 24h quote-volume floor."""
    info = _get(session, '/fapi/v1/exchangeInfo')
    eligible = {
        s['symbol'] for s in info['symbols']
        if s.get('contractType') == 'PERPETUAL' and s.get('quoteAsset') == 'USDT'
        and s.get('status') == 'TRADING' and s.get('baseAsset') not in EXCLUDED_BASES
    }
    tickers = [
        t for t in _get(session, '/fapi/v1/ticker/24hr')
        if t['symbol'] in eligible and float(t['quoteVolume']) >= config.min_quote_volume_usd
    ]
    tickers.sort(key=lambda t: -float(t['quoteVolume']))
    return [t['symbol'] for t in tickers[:config.max_symbols]]


def klines_to_bars(rows, interval_minutes: int, now: pd.Timestamp) -> pd.DataFrame:
    """REST klines -> closed bars indexed by close time (right label)."""
    frame = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 5, 9]]
    frame.columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
    frame = frame.astype(float)
    opened = pd.to_datetime(frame.open_time.astype('int64').to_numpy(), unit='ms', utc=True)
    frame.index = (opened + pd.Timedelta(minutes=interval_minutes)).as_unit('ns')
    frame = frame.drop(columns='open_time')
    return frame.loc[frame.index <= now]


def fetch_bars(session, symbol: str, config: SetupSearchConfig, now: pd.Timestamp) -> dict:
    out = {}
    for interval, minutes, limit in (('15m', 15, config.bars_15m),
                                     ('1h', 60, config.bars_1h),
                                     ('4h', 240, config.bars_4h)):
        rows = _get(session, '/fapi/v1/klines',
                    {'symbol': symbol, 'interval': interval, 'limit': limit})
        out[interval] = klines_to_bars(rows, minutes, now)
    return out


def fetch_open_interest(session, symbol: str) -> pd.Series:
    rows = _get(session, '/futures/data/openInterestHist',
                {'symbol': symbol, 'period': '5m', 'limit': 500})
    index = pd.to_datetime([int(r['timestamp']) for r in rows], unit='ms', utc=True)
    return pd.Series([float(r['sumOpenInterest']) for r in rows], index=index).sort_index()


def market_context(session, now: pd.Timestamp, long_rows: list[dict]) -> dict:
    """BTC 1h trend and alt breadth at scan time, attached to every setup."""
    context = {'btc_above_ema50_1h': None, 'btc_return_24h_pct': None,
               'alt_breadth_above_ema50_1h': None}
    try:
        btc = klines_to_bars(_get(session, '/fapi/v1/klines', {
            'symbol': 'BTCUSDT', 'interval': '1h', 'limit': 200}), 60, now)
        ema = btc.close.ewm(span=50, adjust=False).mean()
        context['btc_above_ema50_1h'] = bool(btc.close.iloc[-1] > ema.iloc[-1])
        context['btc_return_24h_pct'] = round((btc.close.iloc[-1] / btc.close.iloc[-25] - 1) * 100, 3)
    except Exception:  # context is optional; never fail the scan for it
        pass
    flags = [row['above_ema50_1h'] for row in long_rows if row.get('above_ema50_1h') is not None]
    if flags:
        context['alt_breadth_above_ema50_1h'] = round(sum(flags) / len(flags), 3)
    return context


def _fmt(value):
    return None if value is None else float(f'{value:.6g}')


def _post_mss_path(m15: pd.DataFrame, side: int, setup: dict, config) -> dict:
    """What happened after the MSS close, on closed 15m bars (real prices)."""
    after = m15.loc[m15.index > setup['time']]
    limit, stop, tp1 = setup['limit'], setup['stop'], setup['tp1']
    filled_at = None
    for timestamp, row in after.iterrows():
        if filled_at is None:
            if timestamp - setup['time'] > pd.Timedelta(minutes=config.limit_ttl_minutes):
                return {'state': 'EXPIRED', 'at': timestamp}
            if not ((row.low <= limit) if side == 1 else (row.high >= limit)):
                continue
            filled_at = timestamp
        # Conservative: the stop wins on the fill bar and before the target.
        if (row.low <= stop) if side == 1 else (row.high >= stop):
            return {'state': 'STOPPED', 'at': timestamp, 'filled_at': filled_at}
        if (row.high >= tp1) if side == 1 else (row.low <= tp1):
            return {'state': 'TP1_HIT', 'at': timestamp, 'filled_at': filled_at}
    if filled_at is not None:
        return {'state': 'FILLED', 'filled_at': filled_at}
    return {'state': 'PENDING'}


def _evaluate_side(bars: dict, side: int, config: SetupSearchConfig,
                   now: pd.Timestamp, open_interest: pd.Series | None) -> dict:
    strategy = config.strategy
    frames = {k: (v if side == 1 else mirror(v)) for k, v in bars.items()}
    scan = scan_long_bars(
        prepare_four_hour_bars(frames['15m']), prepare_four_hour_bars(frames['1h']),
        frames['4h'], strategy, Counter(), open_interest)
    ctx = scan['context']
    real = lambda v: None if v is None else side * v  # noqa: E731
    checks = dict.fromkeys(CHECKLIST, False)
    result = {'side': 'LONG' if side == 1 else 'SHORT', 'price': _fmt(real(ctx['close']))}
    if side == 1:
        hourly = bars['1h'].close
        result['above_ema50_1h'] = bool(hourly.iloc[-1] > hourly.ewm(span=50, adjust=False).mean().iloc[-1])
    atr = ctx['atr']

    setups = scan['setups']
    latest = setups[-1] if setups else None
    episode = scan['open_episode']
    path = None
    if latest is not None:
        age = now - pd.Timestamp(latest['time'], tz='UTC')
        if age <= pd.Timedelta(hours=config.recent_result_hours):
            levels = [side * v for v in latest['bsl_levels']]
            setup = {
                'time': pd.Timestamp(latest['time'], tz='UTC'),
                'limit': side * latest['limit'],
                'stop': side * latest['stop'],
                'tp1': levels[0],
            }
            rr1 = stress_net_r(side, setup['limit'], setup['stop'], levels[0], strategy)
            tp_ext = next((
                (lv, r) for lv in levels
                for r in [stress_net_r(side, setup['limit'], setup['stop'], lv, strategy)]
                if strategy.min_net_r <= r <= strategy.max_net_r
            ), None)
            path = _post_mss_path(bars['15m'], side, setup, strategy)
            if path['state'] in {'EXPIRED', 'STOPPED', 'TP1_HIT'} and episode is not None:
                latest = None  # a newer live sweep is more actionable
    if latest is not None and path is not None:
        checks.update({k: True for k in CHECKLIST[:5]})
        checks['retest_wejscie'] = path['state'] in {'FILLED', 'STOPPED', 'TP1_HIT'}
        checks['rr_tp1_min_1_3'] = rr1 >= strategy.min_net_r
        evidence = latest['evidence']
        atr = latest['atr']
        mss_close = evidence['mss_close']
        fvg = evidence['fvg']
        zone_age = pd.Timestamp(latest['time'], tz='UTC') - pd.Timestamp(evidence['zone_ob_time'])
        # Mirror-space geometry is side-symmetric, so distances need no sign.
        result['features'] = {
            'atr_15m': round(atr, 10),
            'sweep_depth_atr': round((evidence['ssl'] - evidence['sweep_extreme']) / atr, 3),
            'displacement_atr': round((mss_close - evidence['sweep_extreme']) / atr, 3),
            'fvg_size_atr': round((fvg[1] - fvg[0]) / atr, 3),
            'stop_atr': round((latest['limit'] - latest['stop']) / atr, 3),
            'zone_age_hours': round(zone_age.total_seconds() / 3600, 1),
            'mss_hour_utc': int(pd.Timestamp(latest['time'], tz='UTC').hour),
            'fvg_mid': _fmt(side * (fvg[0] + fvg[1]) / 2),
            'mss_close': _fmt(side * mss_close),
            'discount_4h': (ctx['range_4h'] is not None and evidence['sweep_extreme'] <= (
                ctx['range_4h'][0] + (ctx['range_4h'][1] - ctx['range_4h'][0]) / 3)),
        }
        result.update({
            'mss_time': str(setup['time']),
            'entry_limit': _fmt(setup['limit']),
            'stop_loss': _fmt(setup['stop']),
            'tp1_bsl': _fmt(levels[0]),
            'rr_tp1_net_stress': round(rr1, 2),
            'tp2_bsl': _fmt(levels[1]) if len(levels) > 1 else None,
            'first_bsl_min_3r': _fmt(tp_ext[0]) if tp_ext else None,
            'rr_first_bsl_min_3r': round(tp_ext[1], 2) if tp_ext else None,
            'absorption': evidence.get('absorption'),
            'sweep_time': evidence['sweep_time'],
            'post_mss': path['state'],
        })
        ttl_left = pd.Timedelta(minutes=strategy.limit_ttl_minutes) - age
        if path['state'] == 'FILLED':
            result['status'] = 'IN_POSITION'
            result['next'] = (f"Wejście wypełnione {path['filled_at']}; SL {result['stop_loss']}, "
                              f"TP1 {result['tp1_bsl']}.")
        elif path['state'] == 'PENDING' and checks['rr_tp1_min_1_3']:
            result['status'] = 'WAIT_RETEST'
            result['next'] = (f"Czekaj na retest FVG: limit {result['entry_limit']}, "
                              f"SL {result['stop_loss']}, TP1 {result['tp1_bsl']} "
                              f"(RR 1:{rr1:.1f}); zlecenie ważne jeszcze "
                              f"{max(int(ttl_left.total_seconds() // 60), 0)} min.")
        elif path['state'] == 'PENDING':
            result['status'] = 'RR_TOO_LOW'
            alt = (f" Kolejne BSL {result['first_bsl_min_3r']} daje RR 1:"
                   f"{result['rr_first_bsl_min_3r']}." if tp_ext else '')
            result['next'] = (f"Struktura gotowa, ale RR do TP1 to tylko 1:{rr1:.1f} — "
                              f"wg ścisłych zasad brak wejścia.{alt}")
        else:
            result['status'] = 'RECENT_RESULT'
            result['next'] = {
                'EXPIRED': 'Limit nie został wypełniony w 240 min — setup wygasł.',
                'STOPPED': f"Setup wypełniony i zatrzymany na SL ({path['at']}).",
                'TP1_HIT': f"Setup wypełniony, TP1 osiągnięty ({path['at']}).",
            }[path['state']] + f' RR do TP1 był 1:{rr1:.1f}.'
        result['checklist'] = checks
        result['score'] = sum(checks.values())
        return result

    if episode is not None:
        checks.update({k: True for k in CHECKLIST[:3]})
        lh = real(episode['lh_to_break'])
        result.update({
            'status': 'WAIT_MSS',
            'sweep_time': episode['sweep_time'],
            'swept_ssl': _fmt(real(episode['ssl'])),
            'sweep_extreme': _fmt(real(episode['sweep_extreme'])),
            'mss_level': _fmt(lh),
            'zone': sorted(_fmt(real(v)) for v in episode['zone']),
            'absorption': episode['absorption'],
            'next': (f"Sweep zrobiony ({episode['sweep_time']}). Czekaj na zamknięcie 15m "
                     f"{'powyżej' if side == 1 else 'poniżej'} {_fmt(lh)} (MSS) z FVG — "
                     f"zostało {episode['bars_left']} świec 15m. Unieważnienie: zamknięcie "
                     f"{'poniżej' if side == 1 else 'powyżej'} {_fmt(real(episode['zone_floor']))}."),
        })
        result['checklist'] = checks
        result['score'] = sum(checks.values())
        return result

    checks['trend_przed_setupem_1h'] = ctx['trend_ok']
    close = ctx['close']
    zones = [z for z in ctx['active_zones'] if z[0] - strategy.zone_tolerance_atr * atr <= close]
    nearest = min(zones, key=lambda z: max(0.0, close - z[1]), default=None)
    distance = None if nearest is None else max(0.0, close - nearest[1]) / atr
    in_zone = nearest is not None and distance == 0.0
    checks['cena_w_strefie_ob'] = in_zone
    zone_txt = None if nearest is None else sorted(_fmt(real(v)) for v in nearest)
    result.update({'zone': zone_txt, 'zone_distance_atr': None if distance is None else round(distance, 2),
                   'ssl': _fmt(real(ctx['ssl'])), 'lh': _fmt(real(ctx['lh']))})
    trend_word = 'spadkowy' if side == 1 else 'wzrostowy'
    if ctx['trend_ok'] and in_zone:
        result['status'] = 'WAIT_SWEEP'
        result['next'] = (f"Cena w strefie OB {zone_txt}. Czekaj na sweep "
                          f"{'SSL poniżej' if side == 1 else 'BSL powyżej'} {result['ssl']}, "
                          f"potem MSS.")
    elif ctx['trend_ok'] and distance is not None and distance <= config.approach_atr:
        result['status'] = 'APPROACHING_ZONE'
        result['next'] = (f"Trend {trend_word} na 1H. Strefa OB {zone_txt} "
                          f"{distance:.1f} ATR {'niżej' if side == 1 else 'wyżej'} — obserwuj.")
    else:
        result['status'] = 'NO_SETUP'
        missing = [k for k, ok in checks.items() if not ok][:2]
        result['next'] = f"Brak setupu (brakuje: {', '.join(missing)})."
    result['checklist'] = checks
    result['score'] = sum(checks.values())
    return result


def evaluate_symbol(bars: dict, config: SetupSearchConfig, now: pd.Timestamp,
                    open_interest: pd.Series | None = None) -> list[dict]:
    return [_evaluate_side(bars, side, config, now, open_interest) for side in (1, -1)]


def run_setup_search(config: SetupSearchConfig = SetupSearchConfig(),
                     symbols: list[str] | None = None,
                     now: pd.Timestamp | None = None) -> dict:
    """Scan the universe; returns rows sorted by how actionable they are."""
    now = now or pd.Timestamp.now(tz='UTC')
    session = requests.Session()
    universe = symbols or fetch_universe(session, config)

    def scan(symbol):
        try:
            bars = fetch_bars(session, symbol, config, now)
            rows = evaluate_symbol(bars, config, now)
            # Open interest only matters once a sweep exists; fetch it lazily.
            if any(r['status'] not in {'NO_SETUP', 'APPROACHING_ZONE', 'WAIT_SWEEP'} for r in rows):
                rows = evaluate_symbol(bars, config, now, fetch_open_interest(session, symbol))
            return [{'symbol': symbol, **row} for row in rows], None
        except Exception as exc:  # one bad symbol must not stop the scan
            return [], f'{symbol}: {type(exc).__name__}: {exc}'

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(scan, universe))
    rows = [row for found, _ in outcomes for row in found]
    context = market_context(session, now, [row for row in rows if row['side'] == 'LONG'])
    for row in rows:
        if 'features' in row:
            row['features'].update(context)
    rows.sort(key=lambda r: (STATUS_PRIORITY[r['status']], -r['score'], r['symbol']))
    return {
        'as_of': str(now),
        'universe': len(universe),
        'rows': rows,
        'errors': [error for _, error in outcomes if error],
        'warning': ('Narzędzie obserwacyjne. Backtesty S112/S113 tej strategii nie '
                    'wykazały przewagi po kosztach — to nie jest sygnał do wejścia.'),
    }
