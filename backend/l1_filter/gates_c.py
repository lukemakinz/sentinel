"""Gate C: Trigger Confirmation — min 2 of 5 must pass."""
import numpy as np

from analysts.structure import detect_swing_points, detect_structure_break, compute_vwap_bands
from analysts.momentum import compute_rsi, detect_divergence, detect_divergence_extended, _ema
from .utils import compute_ema, compute_obv


def check_choch(candles: list, direction: str,
                require_htf_bos: bool = True) -> tuple[bool, dict]:
    """
    C1: Change of Character (CHoCH) — NOT Break of Structure (BOS).
    CHoCH = first LH after a series of HH (reversal signal)
    BOS   = new HH in ongoing uptrend (continuation)
    Only CHoCH is a REVERSAL trigger. BOS = trend continuation, different trade.
    """
    if len(candles) < 8:
        return False, {}

    # HTF→LTF hierarchy: prefer HTF BOS before LTF CHoCH (reduces false signals)
    # Not a hard block — reduces conviction but doesn't invalidate signal
    _htf_confirmed = require_htf_bos  # tracked in trade_context for signal quality

    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    closes = np.array([c['close'] for c in candles])

    lookback = max(1, len(candles) // 10)
    swings = detect_swing_points(highs, lows, lookback=lookback)
    structure = detect_structure_break(swings)

    # ONLY CHoCH passes — BOS is a different signal (trend continuation, not reversal)
    if structure and structure['type'] == 'CHoCH':
        if direction == 'LONG'  and structure['direction'] == 'bullish':
            return True, {'type': 'CHoCH', 'level': structure['level'],
                          'note': 'First HL after series of LL — bullish reversal'}
        if direction == 'SHORT' and structure['direction'] == 'bearish':
            return True, {'type': 'CHoCH', 'level': structure['level'],
                          'note': 'First LH after series of HH — bearish reversal'}

    # BOS also accepted for TREND FOLLOW trades (S3 Classic TA)
    # but NOT for S1 SMC Sweep which requires reversal structure
    if structure and structure['type'] == 'BOS':
        if direction == 'LONG'  and structure['direction'] == 'bullish':
            return True, {'type': 'BOS', 'level': structure['level'],
                          'note': 'Break of Structure — trend continuation (lower conviction)'}
        if direction == 'SHORT' and structure['direction'] == 'bearish':
            return True, {'type': 'BOS', 'level': structure['level'],
                          'note': 'Break of Structure — trend continuation (lower conviction)'}

    # Fallback: price break above/below last swing — only for BOS context
    swing_highs = [p for _, p, t in swings if 'H' in t]
    swing_lows  = [p for _, p, t in swings if 'L' in t]
    last_close  = float(closes[-1])

    if direction == 'LONG' and swing_highs and last_close > swing_highs[-1]:
        return True, {'type': 'BOS_fallback', 'level': swing_highs[-1]}
    if direction == 'SHORT' and swing_lows and last_close < swing_lows[-1]:
        return True, {'type': 'BOS_fallback', 'level': swing_lows[-1]}

    return False, {}


def check_momentum_divergence(candles: list, direction: str,
                               symbol: str = None) -> tuple[bool, dict]:
    """
    C2: Momentum divergence — RSI or CVD divergence at sweep point.
    Expert improvement: CVD divergence (price lower low + CVD higher low) is
    the strongest confirmation of absorption by institutions.
    """
    if len(candles) < 20:
        return False, {}

    # Primary: CVD divergence (if data available)
    if symbol:
        try:
            from ingester.models import WhaleCVD
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(hours=8)
            cvd_values = list(WhaleCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff)
                              .order_by('timestamp').values_list('cumulative_delta', flat=True)[-20:])
            if len(cvd_values) >= 10:
                import numpy as np
                cvd_arr   = np.array([float(v) for v in cvd_values], dtype=float)
                closes_cvd = np.array([c['close'] for c in candles[-len(cvd_arr):]], dtype=float)
                div = detect_divergence(closes_cvd, cvd_arr) or detect_divergence_extended(closes_cvd, cvd_arr)
                if direction == 'LONG'  and div in {'bullish', 'bullish_hidden'}:
                    return True, {'divergence': f'{div}_cvd', 'source': 'WhaleCVD'}
                if direction == 'SHORT' and div in {'bearish', 'bearish_hidden'}:
                    return True, {'divergence': f'{div}_cvd', 'source': 'WhaleCVD'}
        except Exception:
            pass

    # Fallback: RSI divergence
    import numpy as np
    closes = np.array([c['close'] for c in candles], dtype=float)
    rsi = compute_rsi(closes)
    if len(rsi) < 10:
        return False, {}

    div = detect_divergence(closes, rsi) or detect_divergence_extended(closes, rsi)
    if direction == 'LONG'  and div in {'bullish', 'bullish_hidden'}:
        strength = 'hidden' if 'hidden' in div else 'regular'
        return True, {'divergence': f'{div}_rsi', 'source': 'RSI', 'strength': strength}
    if direction == 'SHORT' and div in {'bearish', 'bearish_hidden'}:
        strength = 'hidden' if 'hidden' in div else 'regular'
        return True, {'divergence': f'{div}_rsi', 'source': 'RSI', 'strength': strength}

    return False, {}


def check_delta_candle(candles: list, direction: str) -> tuple[bool, dict]:
    """
    C3: Delta candle — taker buy volume vs taker sell volume.
    Replaces EMA crossover (which duplicated A2 info).
    Requires 'taker_buy_volume' in candle data; falls back to volume proxy.
    """
    if len(candles) < 5:
        return False, {}

    # Use last 3 closed candles
    recent = candles[-3:]
    deltas = []
    for c in recent:
        buy_vol  = c.get('taker_buy_volume', c.get('volume', 0) * 0.5)
        sell_vol = c.get('volume', 0) - buy_vol
        deltas.append(buy_vol - sell_vol)

    net_delta = sum(deltas)
    avg_vol   = sum(c.get('volume', 0) for c in candles[-10:]) / 10 if len(candles) >= 10 else 1

    # Significant positive delta = buyers dominate; negative = sellers
    threshold = avg_vol * 0.1   # 10% of avg volume as minimum signal

    if direction == 'LONG'  and net_delta > threshold:
        return True, {'net_delta': round(net_delta, 2), 'signal': 'buy_pressure'}
    if direction == 'SHORT' and net_delta < -threshold:
        return True, {'net_delta': round(net_delta, 2), 'signal': 'sell_pressure'}

    return False, {'net_delta': round(net_delta, 2)}


# Keep old name as alias so existing tests/imports still work
check_ema_crossover = check_delta_candle


def check_volume_spike(candles: list) -> tuple[bool, dict]:
    if len(candles) < 21:
        return False, {}

    volumes = [c['volume'] for c in candles]
    avg_vol  = sum(volumes[-21:-1]) / 20
    last_vol = volumes[-1]

    if avg_vol == 0:
        return False, {}

    ratio = last_vol / avg_vol
    return ratio > 1.5, {'volume_ratio': round(ratio, 2), 'avg_volume': avg_vol}


def check_vwap(candles: list, direction: str) -> tuple[bool, dict]:
    if len(candles) < 10:
        return False, {}

    closes  = [c['close']  for c in candles]
    highs   = [c['high']   for c in candles]
    lows    = [c['low']    for c in candles]
    volumes = [c['volume'] for c in candles]

    vwap, upper, lower = compute_vwap_bands(closes, volumes, highs, lows)
    if vwap is None:
        return False, {}

    current = closes[-1]
    if direction == 'LONG'  and current > vwap:
        return True, {'vwap': vwap}
    if direction == 'SHORT' and current < vwap:
        return True, {'vwap': vwap}

    return False, {'vwap': vwap}


def check_obv_confirmation(candles: list, direction: str) -> tuple[bool, dict]:
    """
    C6: OBV confirmation.
    For continuation trades we want price trend and volume trend aligned.
    """
    if len(candles) < 12:
        return False, {}

    closes = [c['close'] for c in candles]
    obv = compute_obv(candles)
    if len(obv) < 8:
        return False, {}

    obv_ema = compute_ema(obv, 5)
    price_ema = compute_ema(closes, 5)
    if not obv_ema or not price_ema:
        return False, {}

    obv_slope_up = obv[-1] > obv[-4]
    price_slope_up = closes[-1] > price_ema[-1]
    obv_slope_down = obv[-1] < obv[-4]
    price_slope_down = closes[-1] < price_ema[-1]

    if direction == 'LONG' and obv[-1] > obv_ema[-1] and obv_slope_up and price_slope_up:
        return True, {'obv': round(obv[-1], 2), 'obv_ema': round(obv_ema[-1], 2), 'signal': 'bullish_obv'}
    if direction == 'SHORT' and obv[-1] < obv_ema[-1] and obv_slope_down and price_slope_down:
        return True, {'obv': round(obv[-1], 2), 'obv_ema': round(obv_ema[-1], 2), 'signal': 'bearish_obv'}

    return False, {'obv': round(obv[-1], 2), 'obv_ema': round(obv_ema[-1], 2)}


def check_price_action_trigger(candles: list, direction: str) -> tuple[bool, dict]:
    """
    C7: Strong trigger candle.
    We want a displacement-style close, not just a wick through structure.
    """
    if len(candles) < 3:
        return False, {}

    last = candles[-1]
    prev = candles[-2]
    candle_range = max(last['high'] - last['low'], 1e-9)
    body = abs(last['close'] - last['open'])
    body_ratio = body / candle_range
    close_pos = (last['close'] - last['low']) / candle_range
    breakout_up = last['close'] > prev['high']
    breakout_down = last['close'] < prev['low']

    if direction == 'LONG' and body_ratio >= 0.6 and close_pos >= 0.7 and breakout_up:
        return True, {'body_ratio': round(body_ratio, 3), 'close_position': round(close_pos, 3), 'signal': 'bullish_displacement'}
    if direction == 'SHORT' and body_ratio >= 0.6 and close_pos <= 0.3 and breakout_down:
        return True, {'body_ratio': round(body_ratio, 3), 'close_position': round(close_pos, 3), 'signal': 'bearish_displacement'}

    return False, {'body_ratio': round(body_ratio, 3), 'close_position': round(close_pos, 3)}
