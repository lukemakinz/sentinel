"""Multi-Timeframe Analysis — trend direction per timeframe."""
import numpy as np

from analysts.momentum import compute_rsi, detect_divergence_extended
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


def build_top_down_context(
    candles_1d: list,
    candles_4h: list,
    candles_1h: list,
    candles_15m: list,
) -> dict:
    """
    Build a simple top-down bias state that can be used by the scanner:
    1D = macro bias, 4H = regime, 1H = setup state, 15m = timing.
    """
    bias_1d = get_tf_trend(candles_1d)
    bias_4h = get_tf_trend(candles_4h)
    bias_1h = get_tf_trend(candles_1h)
    bias_15m = get_tf_trend(candles_15m)

    state_4h = _four_hour_state(candles_4h, bias_1d, bias_4h)
    state_1h = _one_hour_state(bias_1d, bias_4h, bias_1h)
    timing_15m = _timing_state(candles_15m, bias_15m)

    allow_reversal = state_4h['state'] in {'reversal', 'neutral'}
    allow_continuation = (
        state_4h['state'] in {'continuation', 'neutral'}
        and state_1h['state'] in {'aligned_continuation', 'aligned_pullback', 'neutral'}
    )
    if state_1h['state'] == 'counter_trend':
        allow_continuation = False

    return {
        'bias_1d': bias_1d,
        'bias_4h': bias_4h,
        'bias_1h': bias_1h,
        'bias_15m': bias_15m,
        'state_4h': state_4h,
        'state_1h': state_1h,
        'timing_15m': timing_15m,
        'allow_reversal': allow_reversal,
        'allow_continuation': allow_continuation,
    }


def _four_hour_state(candles: list, bias_1d: dict, bias_4h: dict) -> dict:
    if len(candles) < 20:
        return {'state': 'neutral', 'divergence_aligned': False, 'range_position': 0.5}

    closes = np.array([c['close'] for c in candles], dtype=float)
    highs = [c['high'] for c in candles[-20:]]
    lows = [c['low'] for c in candles[-20:]]
    last_close = float(closes[-1])
    range_high = max(highs)
    range_low = min(lows)
    total_range = max(range_high - range_low, 1e-9)
    range_position = (last_close - range_low) / total_range

    rsi = compute_rsi(closes)
    divergence = detect_divergence_extended(closes, rsi) if len(rsi) >= 10 else None
    bias_dir = bias_1d.get('direction', 'NEUTRAL')
    bias_4h_dir = bias_4h.get('direction', 'NEUTRAL')

    bullish_reversal = bias_dir == 'BULLISH' and range_position <= 0.35 and divergence in {'bullish', 'bullish_hidden'}
    bearish_reversal = bias_dir == 'BEARISH' and range_position >= 0.65 and divergence in {'bearish', 'bearish_hidden'}
    if bullish_reversal or bearish_reversal:
        return {
            'state': 'reversal',
            'divergence_aligned': True,
            'divergence': divergence,
            'range_position': round(range_position, 4),
        }

    continuation = (
        bias_dir in {'BULLISH', 'BEARISH'}
        and bias_dir == bias_4h_dir
    )
    if continuation:
        return {
            'state': 'continuation',
            'divergence_aligned': False,
            'divergence': divergence,
            'range_position': round(range_position, 4),
        }

    return {
        'state': 'neutral',
        'divergence_aligned': divergence in {'bullish', 'bearish', 'bullish_hidden', 'bearish_hidden'},
        'divergence': divergence,
        'range_position': round(range_position, 4),
    }


def _one_hour_state(bias_1d: dict, bias_4h: dict, bias_1h: dict) -> dict:
    macro = bias_1d.get('direction', 'NEUTRAL')
    h4 = bias_4h.get('direction', 'NEUTRAL')
    h1 = bias_1h.get('direction', 'NEUTRAL')

    if macro != 'NEUTRAL' and h4 != 'NEUTRAL' and macro != h4:
        return {'state': 'counter_trend'}
    if macro != 'NEUTRAL' and h1 == macro:
        return {'state': 'aligned_continuation'}
    if macro != 'NEUTRAL' and h1 not in {macro, 'NEUTRAL'}:
        return {'state': 'aligned_pullback'}
    return {'state': 'neutral'}


def _timing_state(candles: list, bias_15m: dict) -> dict:
    if len(candles) < 20:
        return {'state': 'neutral', 'divergence_aligned': False}

    closes = np.array([c['close'] for c in candles], dtype=float)
    rsi = compute_rsi(closes)
    divergence = detect_divergence_extended(closes, rsi) if len(rsi) >= 10 else None
    direction = bias_15m.get('direction', 'NEUTRAL')
    aligned = (
        (direction == 'BULLISH' and divergence in {'bullish', 'bullish_hidden'}) or
        (direction == 'BEARISH' and divergence in {'bearish', 'bearish_hidden'})
    )
    state = 'timing_ready' if aligned else 'neutral'
    return {'state': state, 'divergence_aligned': aligned, 'divergence': divergence}


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
