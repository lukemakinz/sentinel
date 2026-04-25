"""Multi-Timeframe Analysis — trend direction per timeframe."""
from l1_filter.utils import compute_ema

TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d']

# Min candles needed for meaningful EMA signals
MIN_CANDLES = {'5m': 25, '15m': 25, '1h': 25, '4h': 25, '1d': 25}


def get_tf_trend(candles: list) -> dict:
    """
    Returns trend direction for a single timeframe.
    BULLISH / BEARISH / NEUTRAL + signal strength 0-100.
    """
    if len(candles) < 22:
        return {'direction': 'NEUTRAL', 'strength': 0, 'reason': 'insufficient data'}

    closes = [c['close'] for c in candles]
    ema20 = compute_ema(closes, 20)
    ema50 = compute_ema(closes, 50) if len(closes) >= 50 else []

    last_close = closes[-1]
    last_ema20 = ema20[-1] if ema20 else last_close
    last_ema50 = ema50[-1] if ema50 else last_close

    # Slope of EMA20 (last 3 values)
    slope_up = len(ema20) >= 3 and ema20[-1] > ema20[-3]

    # BULLISH: close > EMA20 > EMA50 + upward slope
    # BEARISH: close < EMA20 < EMA50 + downward slope
    if ema50:
        if last_close > last_ema20 and last_ema20 > last_ema50 and slope_up:
            strength = min(100, int((last_close - last_ema50) / last_ema50 * 1000))
            return {'direction': 'BULLISH', 'strength': min(strength, 100),
                    'ema20': round(last_ema20, 2), 'ema50': round(last_ema50, 2),
                    'close': round(last_close, 2), 'reason': 'close > EMA20 > EMA50'}
        if last_close < last_ema20 and last_ema20 < last_ema50 and not slope_up:
            strength = min(100, int((last_ema50 - last_close) / last_ema50 * 1000))
            return {'direction': 'BEARISH', 'strength': min(strength, 100),
                    'ema20': round(last_ema20, 2), 'ema50': round(last_ema50, 2),
                    'close': round(last_close, 2), 'reason': 'close < EMA20 < EMA50'}
    else:
        # Only EMA20 available
        if last_close > last_ema20 and slope_up:
            return {'direction': 'BULLISH', 'strength': 50, 'ema20': round(last_ema20, 2),
                    'close': round(last_close, 2), 'reason': 'close > EMA20'}
        if last_close < last_ema20 and not slope_up:
            return {'direction': 'BEARISH', 'strength': 50, 'ema20': round(last_ema20, 2),
                    'close': round(last_close, 2), 'reason': 'close < EMA20'}

    return {'direction': 'NEUTRAL', 'strength': 20, 'ema20': round(last_ema20, 2),
            'close': round(last_close, 2), 'reason': 'mixed signals'}


def analyze_mtf(symbol: str) -> dict:
    """Run MTF analysis for all timeframes. Returns alignment + trade type."""
    from ingester.models import Candle

    result = {}
    for tf in TIMEFRAMES:
        candles = list(
            Candle.objects.filter(symbol=symbol, interval=tf, is_closed=True)
            .order_by('-timestamp')[:100]
            .values('open', 'high', 'low', 'close', 'volume')
        )
        candle_dicts = [{'open': float(c['open']), 'high': float(c['high']),
                         'low':  float(c['low']),  'close': float(c['close']),
                         'volume': float(c['volume'])} for c in reversed(candles)]
        result[tf] = get_tf_trend(candle_dicts)

    # Classify trade type based on HTF alignment
    d1  = result.get('1d',  {}).get('direction', 'NEUTRAL')
    d4h = result.get('4h',  {}).get('direction', 'NEUTRAL')
    d1h = result.get('1h',  {}).get('direction', 'NEUTRAL')
    d15 = result.get('15m', {}).get('direction', 'NEUTRAL')

    alignment, trade_type, risk, note = _classify(d1, d4h, d1h, d15)

    return {
        'symbol':     symbol,
        'timeframes': result,
        'alignment':  alignment,   # 'full' | 'partial' | 'conflict'
        'trade_type': trade_type,  # 'TREND_FOLLOW' | 'SWING' | 'SCALP' | 'COUNTER_TREND'
        'risk_level': risk,        # 'LOW' | 'MEDIUM' | 'HIGH'
        'note':       note,
    }


def _classify(d1, d4h, d1h, d15):
    """Classify trade type based on timeframe alignment."""
    dirs = [d1, d4h, d1h, d15]
    bulls = dirs.count('BULLISH')
    bears = dirs.count('BEARISH')

    # Full alignment — all TFs agree
    if bulls == 4:
        return ('full', 'TREND_FOLLOW', 'LOW', '4/4 TF bullish — high confidence trend trade')
    if bears == 4:
        return ('full', 'TREND_FOLLOW', 'LOW', '4/4 TF bearish — high confidence trend trade')

    # 1D + 4H agree (primary trend)
    if d1 == d4h == 'BULLISH':
        if d1h in ('BULLISH', 'NEUTRAL'):
            return ('partial', 'SWING', 'MEDIUM', '1D+4H bullish, 1H aligned — standard swing trade')
        return ('partial', 'INTRADAY', 'MEDIUM', '1D+4H bullish but 1H pullback — intraday with caution')

    if d1 == d4h == 'BEARISH':
        if d1h in ('BEARISH', 'NEUTRAL'):
            return ('partial', 'SWING', 'MEDIUM', '1D+4H bearish, 1H aligned — standard swing trade')
        return ('partial', 'INTRADAY', 'MEDIUM', '1D+4H bearish but 1H bounce — intraday with caution')

    # 4H against 1D — counter-trend
    if d1 != 'NEUTRAL' and d4h != 'NEUTRAL' and d1 != d4h:
        return ('conflict', 'COUNTER_TREND', 'HIGH',
                f'⚠️ 1D {d1} vs 4H {d4h} — counter-trend, tylko TP1, ciaśniejszy SL')

    # Only lower TFs agree
    if d15 in ('BULLISH', 'BEARISH'):
        return ('partial', 'SCALP', 'HIGH', f'15m {d15} only — scalp, szybkie wyjście')

    return ('conflict', 'AVOID', 'HIGH', 'Mixed signals across all TFs — skip')
