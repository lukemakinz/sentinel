"""S112: OB Liquidity Reversal (ICT/SMC sweep -> MSS -> FVG retest -> BSL).

Long sequence, all from closed bars only:

1. 1h context is bearish: the last two confirmed 1h swing highs and lows are
   both descending (LH + LL).
2. Price trades into an active 1h bullish order block (last bearish 1h candle
   before a bullish 1h displacement), published before the sweep.
3. A closed 15m bar sweeps the latest confirmed 15m swing low (SSL) inside the
   order block.
4. Within the confirmation window a 15m close breaks the latest confirmed 15m
   swing high (MSS), and the sweep->MSS leg left a bullish FVG.
5. A limit order rests at the FVG's proximal edge; the stop sits beyond the
   sweep extreme; the single target is a confirmed 1h swing high above the
   MSS close (buy-side liquidity):
   - ``nearest``: the nearest BSL, skipped unless its stress net R >= 3;
   - ``first_at_min_r``: the nearest BSL whose stress net R is in [3, 10].

Shorts are the exact mirror. The detector is written for longs and applied to
a price-negated copy for shorts, so both directions share one code path.

S113 adds optional, frozen filters on top of the same sequence:

- absorption: at the sweep extreme the 15m CVD (from 1m taker volume) is above
  its value at the swept pivot (sellers failed to extend), or open interest
  fell by ``oi_flush_pct`` from one hour before the sweep (positions flushed);
- discount: the sweep low lies in the lower ``discount_fraction`` of the last
  ``discount_lookback_4h`` closed 4h bars' range;
- a single scale-out of ``partial_fraction`` at ``partial_r`` gross R.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import ScalpConfig, resample_closed
from .strong_level_retest import confirmed_swings, prepare_four_hour_bars


@dataclass(frozen=True)
class OBLiquidityReversalConfig:
    name: str = 'S112_ob_liquidity_reversal'
    trigger_minutes: int = 15
    context_minutes: int = 60
    swing_width: int = 2
    ssl_lookback_bars: int = 96
    zone_displacement_atr: float = 1.0
    zone_close_location: float = 0.70
    zone_search_bars: int = 3
    zone_max_age_hours: int = 240
    zone_tolerance_atr: float = 0.50
    min_sweep_atr: float = 0.05
    mss_window_bars: int = 16
    mss_break_atr: float = 0.05
    min_fvg_atr: float = 0.10
    stop_buffer_atr: float = 0.10
    min_stop_atr: float = 0.35
    max_stop_atr: float = 3.0
    min_net_r: float = 3.0
    max_net_r: float = 10.0
    target_mode: str = 'nearest'  # or 'first_at_min_r'
    require_absorption: bool = False
    oi_flush_pct: float = 0.5
    discount_fraction: float | None = None
    discount_lookback_4h: int = 30
    partial_r: float | None = None
    partial_fraction: float = 0.5
    max_positions: int = 1
    limit_ttl_minutes: int = 240
    max_hold_hours: int = 72
    stress_taker_bps: float = 8.0
    stress_maker_bps: float = 5.0
    stress_slippage_bps: float = 5.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=3.0,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_hours * 60,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.010,
            weekly_loss_fraction=0.018,
            drawdown_risk_scale_fraction=0.040,
            drawdown_halt_fraction=0.060,
            fee_bps=5.0,
            maker_fee_bps=2.0,
            slippage_bps=2.0,
            limit_penetration_bps=2.0,
            min_reward_cost_ratio=0.0,
            leverage=5.0,
            max_margin_fraction=0.20,
            margin_safety_reserve=0.01,
            max_positions=self.max_positions,
        )


def mirror(minutes: pd.DataFrame) -> pd.DataFrame:
    """Negate prices so a short setup becomes a long setup."""
    out = minutes.copy()
    out['open'] = -minutes.open
    out['close'] = -minutes.close
    out['high'] = -minutes.low
    out['low'] = -minutes.high
    # Aggressive buying in the mirror is aggressive selling in reality.
    out['taker_buy_volume'] = minutes.volume - minutes.taker_buy_volume
    return out


def _known_at(bars: pd.DataFrame, swings) -> tuple[np.ndarray, np.ndarray]:
    """Swing confirmation times (sorted) and prices."""
    times = np.array([bars.index[c].value for _, c, _ in swings], dtype=np.int64)
    prices = np.array([p for _, _, p in swings], dtype=float)
    order = np.argsort(times, kind='stable')
    return times[order], prices[order]


def _bullish_zones(h1: pd.DataFrame, config: OBLiquidityReversalConfig) -> list[dict]:
    """1h bullish OBs with publication time and causal invalidation time."""
    rows = list(h1.itertuples())
    closes = h1.close.to_numpy()
    index = h1.index
    zones = []
    for k in range(config.zone_search_bars + 1, len(rows)):
        bar = rows[k]
        if not np.isfinite(bar.atr) or bar.atr <= 0:
            continue
        if (bar.close - bar.open) < config.zone_displacement_atr * bar.atr:
            continue
        candle_range = max(bar.high - bar.low, 1e-12)
        if (bar.close - bar.low) / candle_range < config.zone_close_location:
            continue
        ob_i = next((
            i for i in range(k - 1, k - 1 - config.zone_search_bars, -1)
            if rows[i].close < rows[i].open
        ), None)
        if ob_i is None:
            continue
        bottom, top = float(rows[ob_i].low), float(rows[ob_i].open)
        if top <= bottom:
            continue
        last = min(len(rows) - 1, k + config.zone_max_age_hours)
        broken = np.nonzero(closes[k + 1:last + 1] < bottom)[0]
        # An unbroken zone lives for its full age even past the data's end,
        # so a live scan still sees it at the last closed bar.
        expires = (
            index[k + 1 + int(broken[0])].value if len(broken)
            else index[k].value + config.zone_max_age_hours * 3600 * 10**9
        )
        zones.append({
            'published': index[k].value,
            'expires': expires,
            'bottom': bottom,
            'top': top,
            'ob_time': str(index[ob_i]),
        })
    return zones


def _long_setups(minutes: pd.DataFrame, config: OBLiquidityReversalConfig,
                 audit: Counter, open_interest: pd.Series | None = None) -> list[dict]:
    """Raw long geometry; prices are in the frame's own (maybe mirrored) space."""
    return scan_long_bars(
        prepare_four_hour_bars(resample_closed(minutes, config.trigger_minutes)),
        prepare_four_hour_bars(resample_closed(minutes, config.context_minutes)),
        resample_closed(minutes, 240), config, audit, open_interest)['setups']


def scan_long_bars(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame,
                   config: OBLiquidityReversalConfig, audit: Counter,
                   open_interest: pd.Series | None = None) -> dict:
    """Long state machine on closed, prepared bars (right-labelled close times).

    Returns completed MSS setups, the still-open sweep episode (if the data
    ends inside an MSS window) and the context at the last closed bar, so the
    live setup search and the backtest share one implementation.
    """
    cvd = np.cumsum((2 * m15.taker_buy_volume - m15.volume).to_numpy())
    h4_t = h4.index.asi8
    h4_low = h4.low.rolling(config.discount_lookback_4h).min().to_numpy()
    h4_high = h4.high.rolling(config.discount_lookback_4h).max().to_numpy()
    if open_interest is not None:
        # A 5m metrics sample is only treated as known once its period ends.
        oi_t = (open_interest.index + pd.Timedelta(minutes=5)).asi8
        oi_v = open_interest.to_numpy(dtype=float)
    bar_ns = config.trigger_minutes * 60 * 10**9
    sh15, sl15 = confirmed_swings(m15, config.swing_width)
    sh1, sl1 = confirmed_swings(h1, config.swing_width)
    sh15_t, sh15_p = _known_at(m15, sh15)
    sl15_t, sl15_p = _known_at(m15, sl15)
    sh1_t, sh1_p = _known_at(h1, sh1)
    sl1_t, sl1_p = _known_at(h1, sl1)
    sl15_pivot_t = {m15.index[c].value: m15.index[p].value for p, c, _ in sl15}
    sl15_pivot_i = {m15.index[c].value: p for p, c, _ in sl15}
    zones = _bullish_zones(h1, config)
    lookback_ns = config.ssl_lookback_bars * config.trigger_minutes * 60 * 10**9

    times = m15.index.asi8
    opens, highs = m15.open.to_numpy(), m15.high.to_numpy()
    lows, closes = m15.low.to_numpy(), m15.close.to_numpy()
    atrs = m15.atr.to_numpy()
    used_zones: set[int] = set()
    setups = []

    def last_two(t_arr, p_arr, t):
        n = np.searchsorted(t_arr, t, side='right')
        return (p_arr[n - 2], p_arr[n - 1]) if n >= 2 else None

    def latest(t_arr, p_arr, t):
        n = np.searchsorted(t_arr, t, side='right')
        return (t_arr[n - 1], p_arr[n - 1]) if n >= 1 else None

    def oi_at(t):
        n = np.searchsorted(oi_t, t, side='right')
        return oi_v[n - 1] if n >= 1 else None

    def in_discount(j):
        n = np.searchsorted(h4_t, times[j - 1], side='right')
        if n < 1 or not np.isfinite(h4_low[n - 1]):
            return False
        lo, hi = h4_low[n - 1], h4_high[n - 1]
        return lows[j] <= lo + config.discount_fraction * (hi - lo)

    def absorbed(j, e, pivot_i):
        if cvd[e] > cvd[pivot_i]:
            return 'cvd_divergence'
        if open_interest is not None:
            before = oi_at(times[j] - bar_ns - 3600 * 10**9)
            after = oi_at(times[e])
            if before and after and (after / before - 1) * 100 <= -config.oi_flush_pct:
                return 'oi_flush'
        return None

    open_episode = None
    j = 1
    while j < len(m15):
        prior_t, atr = times[j - 1], atrs[j]
        if not np.isfinite(atr) or atr <= 0:
            j += 1
            continue
        # Swings must be confirmed by the previous closed bar.
        ssl = latest(sl15_t, sl15_p, prior_t)
        if ssl is None or prior_t - sl15_pivot_t[ssl[0]] > lookback_ns:
            j += 1
            continue
        if lows[j] > ssl[1] - config.min_sweep_atr * atr:
            j += 1
            continue
        audit['ssl_sweeps'] += 1
        highs_ctx = last_two(sh1_t, sh1_p, prior_t)
        lows_ctx = last_two(sl1_t, sl1_p, prior_t)
        if not (highs_ctx and lows_ctx and highs_ctx[1] < highs_ctx[0]
                and lows_ctx[1] < lows_ctx[0]):
            audit['reject_context_not_bearish'] += 1
            j += 1
            continue
        zone_i = next((
            i for i, z in enumerate(zones)
            if i not in used_zones and z['published'] <= prior_t < z['expires']
            and z['bottom'] - config.zone_tolerance_atr * atr <= lows[j] <= z['top']
        ), None)
        if zone_i is None:
            audit['reject_no_active_zone'] += 1
            j += 1
            continue
        zone = zones[zone_i]
        if config.discount_fraction is not None and not in_discount(j):
            audit['reject_not_in_4h_discount'] += 1
            j += 1
            continue
        lh = latest(sh15_t, sh15_p, prior_t)
        if lh is None or lh[1] <= closes[j]:
            audit['reject_no_lh_above'] += 1
            j += 1
            continue
        audit['armed'] += 1

        extreme, extreme_i = lows[j], j
        floor = zone['bottom'] - config.zone_tolerance_atr * atr
        outcome = None
        for m in range(j + 1, min(len(m15), j + 1 + config.mss_window_bars)):
            if closes[m] < floor:
                outcome = ('reject_zone_failed', m)
                break
            if lows[m] < extreme:
                extreme, extreme_i = lows[m], m
            if closes[m] < lh[1] + config.mss_break_atr * atrs[m]:
                continue
            fvg = None
            for i in range(m, j + 1, -1):
                gap = lows[i] - highs[i - 2]
                if gap >= config.min_fvg_atr * atrs[m]:
                    fvg = (float(highs[i - 2]), float(lows[i]))
                    break
            if fvg is None:
                outcome = ('reject_mss_without_fvg', m)
                break
            absorption = absorbed(j, extreme_i, sl15_pivot_i[ssl[0]])
            if config.require_absorption and absorption is None:
                outcome = ('reject_no_absorption', m)
                break
            n = np.searchsorted(sh1_t, times[m], side='right')
            above = np.unique(sh1_p[:n][sh1_p[:n] > closes[m]])
            if not len(above):
                outcome = ('reject_no_bsl_target', m)
                break
            used_zones.add(zone_i)
            setups.append({
                'time': times[m],
                'limit': fvg[1],
                'stop': float(extreme - config.stop_buffer_atr * atrs[m]),
                'bsl_levels': [float(v) for v in above],
                'atr': float(atrs[m]),
                'evidence': {
                    'sweep_time': str(m15.index[j]),
                    'ssl': float(ssl[1]),
                    'sweep_extreme': float(extreme),
                    'lh_broken': float(lh[1]),
                    'mss_close': float(closes[m]),
                    'fvg': list(fvg),
                    'zone': [zone['bottom'], zone['top']],
                    'zone_ob_time': zone['ob_time'],
                    'absorption': absorption,
                },
            })
            outcome = ('mss_confirmed', m)
            break
        if outcome is None and j + config.mss_window_bars >= len(m15):
            # Data ends inside the MSS window: the episode is still live.
            open_episode = {
                'sweep_time': str(m15.index[j]),
                'ssl': float(ssl[1]),
                'sweep_extreme': float(extreme),
                'lh_to_break': float(lh[1] + config.mss_break_atr * atrs[-1]),
                'zone': [zone['bottom'], zone['top']],
                'zone_floor': float(floor),
                'bars_elapsed': len(m15) - 1 - j,
                'bars_left': j + config.mss_window_bars - (len(m15) - 1),
                'absorption': absorbed(j, extreme_i, sl15_pivot_i[ssl[0]]),
            }
            audit['open_episode'] += 1
            j = len(m15)
        elif outcome is None:
            audit['reject_mss_timeout'] += 1
            j += config.mss_window_bars
        else:
            audit[outcome[0]] += 1
            j = outcome[1] + 1

    now = times[-1]
    highs_ctx = last_two(sh1_t, sh1_p, now)
    lows_ctx = last_two(sl1_t, sl1_p, now)
    ssl_now = latest(sl15_t, sl15_p, now)
    lh_now = latest(sh15_t, sh15_p, now)
    n4 = np.searchsorted(h4_t, now, side='right')
    context = {
        'close': float(closes[-1]),
        'atr': float(atrs[-1]),
        'swing_highs_1h': [float(v) for v in highs_ctx] if highs_ctx else None,
        'swing_lows_1h': [float(v) for v in lows_ctx] if lows_ctx else None,
        'trend_ok': bool(highs_ctx and lows_ctx and highs_ctx[1] < highs_ctx[0]
                         and lows_ctx[1] < lows_ctx[0]),
        'ssl': float(ssl_now[1]) if ssl_now else None,
        'lh': float(lh_now[1]) if lh_now else None,
        'active_zones': [
            [z['bottom'], z['top']] for i, z in enumerate(zones)
            if i not in used_zones and z['published'] <= now < z['expires']
        ],
        'range_4h': (
            [float(h4_low[n4 - 1]), float(h4_high[n4 - 1])]
            if n4 >= 1 and np.isfinite(h4_low[n4 - 1]) else None
        ),
    }
    return {'setups': setups, 'open_episode': open_episode, 'context': context}


def stress_net_r(side: int, limit: float, stop: float, target: float,
                 config: OBLiquidityReversalConfig) -> float:
    """Net R of a limit entry under stress costs (maker in, taker+slip out)."""
    maker = config.stress_maker_bps / 10000
    taker = config.stress_taker_bps / 10000
    slip = config.stress_slippage_bps / 10000
    stop_fill = stop * (1 - side * slip)
    target_fill = target * (1 - side * slip)
    loss = side * (limit - stop_fill) + maker * limit + taker * stop_fill
    gain = side * (target_fill - limit) - maker * limit - taker * target_fill
    return gain / loss if loss > 0 else float('-inf')


def ob_liquidity_reversal_signals(
    minutes: pd.DataFrame,
    config: OBLiquidityReversalConfig = OBLiquidityReversalConfig(),
    open_interest: pd.Series | None = None,
) -> tuple[list[dict], dict]:
    """Executable limit signals for ``execute_cluster`` plus a state audit."""
    # Integer time arithmetic below assumes nanosecond indexes.
    minutes = minutes.set_axis(minutes.index.as_unit('ns'))
    if open_interest is not None:
        open_interest = open_interest.set_axis(open_interest.index.as_unit('ns'))
    signals, audit = [], {}
    for side, frame in ((1, minutes), (-1, mirror(minutes))):
        counter = Counter()
        for raw in _long_setups(frame, config, counter, open_interest):
            # Map mirrored geometry back to real prices; levels are nearest first.
            limit, stop = side * raw['limit'], side * raw['stop']
            levels = [side * v for v in raw['bsl_levels']]
            if config.target_mode == 'nearest':
                levels = levels[:1]
            target = net_r = None
            for level in levels:
                level_r = stress_net_r(side, limit, stop, level, config)
                if level_r > config.max_net_r:
                    break
                if level_r >= config.min_net_r:
                    target, net_r = level, level_r
                    break
            if target is None:
                counter['reject_no_bsl_in_net_r_range'] += 1
                continue
            evidence = {
                key: ([side * v for v in value] if isinstance(value, list)
                      else side * value if isinstance(value, float) else value)
                for key, value in raw['evidence'].items()
            }
            evidence['stress_net_r'] = net_r
            evidence['bsl_target'] = target
            counter['signals'] += 1
            timestamp = pd.Timestamp(raw['time'], tz='UTC')
            partial = {} if config.partial_r is None else {
                'partial_price': limit + side * config.partial_r * abs(limit - stop),
                'partial_fraction': config.partial_fraction,
            }
            signals.append({
                **partial,
                'timestamp': timestamp,
                'side': side,
                'limit_price': limit,
                'stop': stop,
                'target_price': target,
                'atr': raw['atr'],
                'score': float(net_r),
                'setup': config.name,
                'setup_id': f'{side}:{timestamp.isoformat()}',
                'limit_ttl_minutes': config.limit_ttl_minutes,
                'min_stop_atr': config.min_stop_atr,
                'max_stop_atr': config.max_stop_atr,
                'min_target_r': config.min_net_r,
                'evidence': evidence,
            })
        audit['LONG' if side == 1 else 'SHORT'] = dict(counter)
    signals.sort(key=lambda s: (s['timestamp'], -s['score'], s['setup_id']))
    return signals, audit
