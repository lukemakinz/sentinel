"""Gate B: Setup Structure — min 3 of 5 must pass."""
import numpy as np

from analysts.structure import detect_swing_points, detect_order_blocks, detect_fvg
from .utils import compute_atr


def check_liquidity_sweep(candles: list, direction: str,
                          symbol: str = None) -> tuple[bool, dict]:
    """
    B1: Liquidity sweep against REAL structural levels (PDH/PDL/Asian Range/Equal levels).
    Falls back to swing-based detection if no real levels available.
    """
    if len(candles) < 10:
        return False, {}

    last_close = candles[-1]['close']
    recent_high = max(c['high'] for c in candles[-3:])
    recent_low  = min(c['low']  for c in candles[-3:])

    # Primary: check against real liquidity levels
    if symbol:
        try:
            from datetime import timezone as tz
            from datetime import datetime
            from l1_filter.liquidity import LiquiditySnapshot

            snap    = LiquiditySnapshot.build(symbol)
            levels  = snap.all_levels()

            if levels:
                if direction == 'LONG':
                    # Sweep = wick broke below a known level then recovered above it
                    swept = [l for l in levels if recent_low < l < last_close]
                    if swept:
                        target = min(swept, key=lambda l: abs(last_close - l))
                        return True, {
                            'swept_level': target,
                            'nearest_liquidity': snap.nearest_above(last_close),
                            'sweep_type': 'PDH/PDL/Asian/Equal',
                        }
                else:
                    swept = [l for l in levels if last_close < l < recent_high]
                    if swept:
                        target = min(swept, key=lambda l: abs(last_close - l))
                        return True, {
                            'swept_level': target,
                            'nearest_liquidity': snap.nearest_below(last_close),
                            'sweep_type': 'PDH/PDL/Asian/Equal',
                        }
        except Exception:
            pass   # fall through to swing-based

    # Fallback: swing-based detection (less precise)
    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    lookback = min(5, len(candles) // 4)
    swings = detect_swing_points(highs, lows, lookback=lookback)

    if direction == 'LONG':
        lows_only = [(i, p) for i, p, t in swings if 'L' in t]
        if len(lows_only) >= 2:
            _, prev_low = lows_only[-2]
            if recent_low < prev_low and last_close > prev_low:
                return True, {'swept_level': prev_low, 'nearest_liquidity': prev_low,
                               'sweep_type': 'swing_fallback'}
    else:
        highs_only = [(i, p) for i, p, t in swings if 'H' in t]
        if len(highs_only) >= 2:
            _, prev_high = highs_only[-2]
            if recent_high > prev_high and last_close < prev_high:
                return True, {'swept_level': prev_high, 'nearest_liquidity': prev_high,
                               'sweep_type': 'swing_fallback'}

    return False, {}


def check_fvg_ob(candles: list, direction: str) -> tuple[bool, dict]:
    """
    B2: Proper FVG detection with displacement candle + mitigation tracking.
    Falls back to Order Block detection if no qualifying FVG found.
    Entry at 50% (mid-FVG / OTE) — not arbitrary 25%.
    """
    if len(candles) < 5:
        return False, {}

    current = candles[-1]['close']

    # Primary: proper FVG with displacement candle
    atr = compute_atr(candles)[-1] if len(candles) >= 2 else 1.0
    avg_vol = sum(c.get('volume', 0) for c in candles[-20:]) / min(20, len(candles))

    from l1_filter.fvg import get_active_fvgs
    fvg_dir = 'bullish' if direction == 'LONG' else 'bearish'
    active_fvgs = get_active_fvgs(candles, atr, fvg_dir)

    if direction == 'LONG':
        # Active bullish FVGs below current price (support)
        nearby = [f for f in active_fvgs if f.bottom <= current]
        if nearby:
            fvg = max(nearby, key=lambda f: f.bottom)  # most recent below
            return True, {
                'fvg_zone': (fvg.bottom, fvg.top),
                'entry_ote': fvg.ote_entry,   # OTE = 50% mid
                'fvg_type': 'displacement_fvg',
            }
    else:
        nearby = [f for f in active_fvgs if f.top >= current]
        if nearby:
            fvg = min(nearby, key=lambda f: f.top)
            return True, {
                'fvg_zone': (fvg.bottom, fvg.top),
                'entry_ote': fvg.ote_entry,
                'fvg_type': 'displacement_fvg',
            }

    # Fallback: Order Block (last opposing candle before strong move)
    opens  = np.array([c['open']  for c in candles])
    closes = np.array([c['close'] for c in candles])
    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    vols   = np.array([c.get('volume', 0) for c in candles])
    obs    = detect_order_blocks(opens, closes, highs, lows, vols)

    if direction == 'LONG':
        bullish_obs = [ob for ob in obs if ob['type'] == 'bullish_ob' and ob['bottom'] <= current]
        if bullish_obs:
            ob = bullish_obs[0]
            return True, {'fvg_zone': (ob['bottom'], ob['top']), 'fvg_type': 'order_block'}
    else:
        bearish_obs = [ob for ob in obs if ob['type'] == 'bearish_ob' and ob['top'] >= current]
        if bearish_obs:
            ob = bearish_obs[0]
            return True, {'fvg_zone': (ob['bottom'], ob['top']), 'fvg_type': 'order_block'}

    return False, {}


def check_premium_discount(candles: list, direction: str,
                            htf_candles: list = None) -> tuple[bool, dict]:
    """
    B3: Premium/Discount zone based on HTF swing (50% retracement).
    Uses 4H candles if provided (htf_candles), falls back to provided candles.
    SMC definition: Discount = below 50% of HTF range → buy.
                    Premium  = above 50% of HTF range → sell.
    OTE zone: 62-79% retracement for highest probability entries.
    """
    ref_candles = htf_candles if htf_candles and len(htf_candles) >= 20 else candles
    if len(ref_candles) < 10:
        return False, {}

    highs   = [c['high'] for c in ref_candles]
    lows    = [c['low']  for c in ref_candles]
    current = candles[-1]['close']

    range_high = max(highs)
    range_low  = min(lows)
    total_range = range_high - range_low

    if total_range == 0:
        return False, {}

    midpoint = (range_high + range_low) / 2
    # 50% = midpoint. Discount = below 50%. Premium = above 50%.
    # OTE zone: 62-79% retracement from swing high (for longs going into discount)
    ote_low  = range_high - 0.79 * total_range   # 79% retracement level
    ote_high = range_high - 0.62 * total_range   # 62% retracement level

    if direction == 'LONG':
        if current < midpoint:
            in_ote = ote_low <= current <= ote_high
            return True, {
                'zone': 'discount',
                'midpoint': round(midpoint, 4),
                'in_ote': in_ote,
                'ote_range': (round(ote_low, 4), round(ote_high, 4)),
            }
    elif direction == 'SHORT':
        if current > midpoint:
            # OTE for shorts: 62-79% retracement from swing low
            ote_low_s  = range_low + 0.62 * total_range
            ote_high_s = range_low + 0.79 * total_range
            in_ote = ote_low_s <= current <= ote_high_s
            return True, {
                'zone': 'premium',
                'midpoint': round(midpoint, 4),
                'in_ote': in_ote,
                'ote_range': (round(ote_low_s, 4), round(ote_high_s, 4)),
            }

    return False, {'zone': 'neutral', 'midpoint': round(midpoint, 4)}



# B4 (classical patterns) REMOVED — redundant with B1+B2, adds noise.
# Double bottom/top in SMC vocabulary = equal highs/lows sweep (handled by B1+LiquidityTracker).


def check_atr_squeeze(candles: list) -> tuple[bool, dict]:
    if len(candles) < 21:
        return False, {}

    # Use raw True Range (not Wilder-smoothed) for fast squeeze detection
    ranges = [c['high'] - c['low'] for c in candles]
    avg_range    = sum(ranges[-21:-1]) / 20
    current_range = ranges[-1]

    if avg_range == 0:
        return False, {}

    passed = current_range < 0.5 * avg_range
    return passed, {'current_atr': current_range, 'avg_atr': avg_range}
