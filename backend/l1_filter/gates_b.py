"""Gate B: Setup Structure — min 3 of 5 must pass."""
import numpy as np

from analysts.structure import detect_swing_points, detect_order_blocks, detect_fvg
from .utils import compute_atr


def check_liquidity_sweep(candles: list, direction: str) -> tuple[bool, dict]:
    if len(candles) < 10:
        return False, {}

    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    closes = np.array([c['close'] for c in candles])

    lookback = min(5, len(candles) // 4)
    swings = detect_swing_points(highs, lows, lookback=lookback)
    if not swings:
        return False, {}

    last_close = closes[-1]

    if direction == 'LONG':
        # Look for a recent low that was swept then price recovered
        lows_only = [(i, p) for i, p, t in swings if 'L' in t]
        if len(lows_only) >= 2:
            _, prev_low = lows_only[-2]
            _, last_low_price = lows_only[-1]
            # Sweep: last candle went below prev low but closed above it
            recent_low  = min(c['low']  for c in candles[-3:])
            recent_close = candles[-1]['close']
            if recent_low < prev_low and recent_close > prev_low:
                return True, {'swept_level': prev_low, 'nearest_liquidity': prev_low}
    else:
        # SHORT: swept above swing high then reversed
        highs_only = [(i, p) for i, p, t in swings if 'H' in t]
        if len(highs_only) >= 2:
            _, prev_high = highs_only[-2]
            recent_high  = max(c['high'] for c in candles[-3:])
            recent_close = candles[-1]['close']
            if recent_high > prev_high and recent_close < prev_high:
                return True, {'swept_level': prev_high, 'nearest_liquidity': prev_high}

    return False, {}


def check_fvg_ob(candles: list, direction: str) -> tuple[bool, dict]:
    if len(candles) < 5:
        return False, {}

    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    closes = np.array([c['close'] for c in candles])
    opens  = np.array([c['open']  for c in candles])
    vols   = np.array([c['volume'] for c in candles])

    fvgs = detect_fvg(highs, lows, closes)
    obs  = detect_order_blocks(opens, closes, highs, lows, vols)

    current = closes[-1]

    if direction == 'LONG':
        # FVG below or at current price acts as support — price may have already moved above it
        bullish_fvgs = [g for g in fvgs if g['type'] == 'bullish_fvg' and g['bottom'] <= current]
        if bullish_fvgs:
            gap = bullish_fvgs[0]
            return True, {'fvg_zone': (gap['bottom'], gap['top'])}
        bullish_obs = [ob for ob in obs if ob['type'] == 'bullish_ob' and ob['bottom'] <= current]
        if bullish_obs:
            ob = bullish_obs[0]
            return True, {'fvg_zone': (ob['bottom'], ob['top'])}
    else:
        bearish_fvgs = [g for g in fvgs if g['type'] == 'bearish_fvg' and g['top'] >= current]
        if bearish_fvgs:
            gap = bearish_fvgs[0]
            return True, {'fvg_zone': (gap['bottom'], gap['top'])}
        bearish_obs = [ob for ob in obs if ob['type'] == 'bearish_ob' and ob['top'] >= current]
        if bearish_obs:
            ob = bearish_obs[0]
            return True, {'fvg_zone': (ob['bottom'], ob['top'])}

    return False, {}


def check_premium_discount(candles: list, direction: str) -> tuple[bool, dict]:
    if len(candles) < 10:
        return False, {}

    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    current = candles[-1]['close']

    range_high = max(highs)
    range_low  = min(lows)
    midpoint   = (range_high + range_low) / 2

    discount_zone_top    = midpoint - (range_high - range_low) * 0.1  # below 40% of range
    premium_zone_bottom  = midpoint + (range_high - range_low) * 0.1  # above 60% of range

    if direction == 'LONG'  and current < discount_zone_top:
        return True, {'zone': 'discount', 'midpoint': midpoint}
    if direction == 'SHORT' and current > premium_zone_bottom:
        return True, {'zone': 'premium', 'midpoint': midpoint}

    return False, {'zone': 'neutral', 'midpoint': midpoint}


def check_classical_pattern(candles: list, direction: str) -> tuple[bool, dict]:
    if len(candles) < 7:
        return False, {}

    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])

    lookback = min(5, len(candles) // 4)
    swings = detect_swing_points(highs, lows, lookback=lookback)

    if direction == 'LONG':
        # Double bottom: two swing lows within 1% of each other
        swing_lows = [(i, p) for i, p, t in swings if 'L' in t]
        for j in range(len(swing_lows) - 1):
            p1, p2 = swing_lows[j][1], swing_lows[j + 1][1]
            if p1 > 0 and abs(p1 - p2) / p1 < 0.03:  # 3% tolerance
                return True, {'pattern': 'double_bottom', 'level': (p1 + p2) / 2}
    else:
        # Double top: two swing highs within 3% of each other
        swing_highs = [(i, p) for i, p, t in swings if 'H' in t]
        for j in range(len(swing_highs) - 1):
            p1, p2 = swing_highs[j][1], swing_highs[j + 1][1]
            if p1 > 0 and abs(p1 - p2) / p1 < 0.03:
                return True, {'pattern': 'double_top', 'level': (p1 + p2) / 2}

    return False, {}


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
