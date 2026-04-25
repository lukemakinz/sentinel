"""
Position sizing using ATR (Average True Range).
"""
import logging

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


def compute_atr(highs, lows, closes, period=14):
    """Calculate Average True Range."""
    if len(highs) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return np.mean(true_ranges) if true_ranges else None

    # Smoothed ATR
    atr = np.mean(true_ranges[:period])
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period

    return atr


def calculate_stop_loss(entry_price, atr, side, multiplier=1.5):
    """Calculate ATR-based stop loss."""
    distance = atr * multiplier
    if side == 'LONG':
        return entry_price - distance
    else:
        return entry_price + distance


def calculate_take_profits(entry_price, stop_loss, side):
    """
    Multi-level take profit:
    TP1 = 1:1 RR → 40%
    TP2 = 2:1 RR → 30%
    TP3 = 3:1 RR → 20%
    Rest 10% → trailing stop
    """
    risk = abs(entry_price - stop_loss)

    if side == 'LONG':
        tp1 = entry_price + risk * 1
        tp2 = entry_price + risk * 2
        tp3 = entry_price + risk * 3
    else:
        tp1 = entry_price - risk * 1
        tp2 = entry_price - risk * 2
        tp3 = entry_price - risk * 3

    return [
        {'level': tp1, 'close_pct': 0.40, 'label': 'TP1 (1:1)'},
        {'level': tp2, 'close_pct': 0.30, 'label': 'TP2 (2:1)'},
        {'level': tp3, 'close_pct': 0.20, 'label': 'TP3 (3:1)'},
    ]


def calculate_position_size(balance, risk_percent, entry_price, stop_loss, leverage=1):
    """
    Calculate position size based on risk.
    position_size = (balance * risk_percent) / |entry - stop_loss|
    """
    risk_amount = balance * risk_percent
    price_risk = abs(entry_price - stop_loss)

    if price_risk == 0:
        return 0

    size_in_usd = risk_amount / price_risk * entry_price
    max_size = balance * leverage

    return min(size_in_usd, max_size)


def get_atr_for_symbol(symbol, interval='1h', period=14):
    """Fetch candles and compute current ATR."""
    from ingester.models import Candle

    candles = list(Candle.objects.filter(
        symbol=symbol, interval=interval, is_closed=True,
    ).order_by('-timestamp').values('high', 'low', 'close')[:period + 10])

    if len(candles) < period + 1:
        return None

    candles.reverse()
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    closes = [float(c['close']) for c in candles]

    return compute_atr(highs, lows, closes, period)
