"""Test data factories for l1_filter gate tests."""
import math


def make_candles(closes, highs=None, lows=None, volumes=None, opens=None):
    result = []
    for i, c in enumerate(closes):
        c = float(c)
        result.append({
            'open':   float(opens[i])   if opens   else c * 0.999,
            'high':   float(highs[i])   if highs   else c * 1.002,
            'low':    float(lows[i])    if lows    else c * 0.998,
            'close':  c,
            'volume': float(volumes[i]) if volumes else 1000.0,
        })
    return result


def uptrend(n=250, start=1000.0, step=5.0):
    closes = [start + i * step for i in range(n)]
    return make_candles(closes)


def downtrend(n=250, start=2500.0, step=5.0):
    closes = [start - i * step for i in range(n)]
    return make_candles(closes)


def ranging(n=100, mean=1000.0, amplitude=3.0):
    closes = [mean + amplitude * math.sin(i * 0.4) for i in range(n)]
    highs  = [c + 5 for c in closes]
    lows   = [c - 5 for c in closes]
    return make_candles(closes, highs=highs, lows=lows)


def trending_with_spike_volume(n=30, spike_at=-1):
    """Last candle has 3× volume — triggers C4."""
    closes  = [1000 + i * 5 for i in range(n)]
    volumes = [1000.0] * n
    volumes[spike_at] = 3000.0
    return make_candles(closes, volumes=volumes)
