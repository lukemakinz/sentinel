"""
Liquidity level tracker.
Computes real structural levels: PDH/PDL, PWH/PWL, Asian Range, Equal Highs/Lows.
These are used by:
  - B1 gate: sweep must hit a REAL level, not just 5-candle lookback
  - L3 Calculator: TP targets nearest unswept liquidity pool
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional


# ── Computation helpers ───────────────────────────────────────────────────────

def compute_pdh_pdl(symbol: str, now: datetime) -> tuple[Optional[float], Optional[float]]:
    """Previous Day High / Previous Day Low from 1h candles."""
    from ingester.models import Candle

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    candles = list(Candle.objects.filter(
        symbol=symbol, interval='1h', is_closed=True,
        timestamp__gte=yesterday_start,
        timestamp__lt=today_start,
    ).values_list('high', 'low'))

    if not candles:
        return None, None

    pdh = float(max(h for h, _ in candles))
    pdl = float(min(l for _, l in candles))
    return pdh, pdl


def compute_pwh_pwl(symbol: str, now: datetime) -> tuple[Optional[float], Optional[float]]:
    """Previous Week High / Low from 4h candles."""
    from ingester.models import Candle

    days_since_monday = now.weekday()
    this_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    last_monday = this_monday - timedelta(weeks=1)

    candles = list(Candle.objects.filter(
        symbol=symbol, interval='4h', is_closed=True,
        timestamp__gte=last_monday,
        timestamp__lt=this_monday,
    ).values_list('high', 'low'))

    if not candles:
        return None, None

    return float(max(h for h, _ in candles)), float(min(l for _, l in candles))


def compute_asian_range(symbol: str, now: datetime) -> tuple[Optional[float], Optional[float]]:
    """
    Asian Range High/Low — 02:00 to 06:00 UTC same day.
    This is the "tight consolidation" window before London opens.
    London sweeps this range (Judas Swing) before the real move.
    """
    from ingester.models import Candle

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    asian_start = today + timedelta(hours=2)   # 02:00 UTC today
    asian_end   = today + timedelta(hours=6)   # 06:00 UTC today (before London at 07:00)

    candles = list(Candle.objects.filter(
        symbol=symbol, interval='1h', is_closed=True,
        timestamp__gte=asian_start,
        timestamp__lt=asian_end,
    ).values_list('high', 'low'))

    if not candles:
        return None, None

    return float(max(h for h, _ in candles)), float(min(l for _, l in candles))


def check_london_judas_swing(symbol: str, direction: str, now: datetime,
                              candles_recent: list) -> tuple[bool, dict]:
    """
    London Judas Swing filter (07-10 UTC):
    London trade is ONLY valid if the sweep specifically hit Asian High (SHORT)
    or Asian Low (LONG). This prevents entering on the fake move (Judas Swing)
    that hasn't yet collected Asian Range liquidity.

    If outside London session → always passes (no restriction).
    If Asian Range not available → passes (no data to filter on).
    """
    if not (7 <= now.hour < 10):
        return True, {'london_filter': 'not_london_session'}

    asian_high, asian_low = compute_asian_range(symbol, now)
    if asian_high is None or asian_low is None:
        return True, {'london_filter': 'no_asian_range_data'}

    if not candles_recent:
        return True, {'london_filter': 'no_candle_data'}

    # Check last 3 candles for Asian Range interaction
    recent_low  = min(float(c.get('low',  candles_recent[-1]['close'])) for c in candles_recent[-3:])
    recent_high = max(float(c.get('high', candles_recent[-1]['close'])) for c in candles_recent[-3:])
    last_close  = float(candles_recent[-1]['close'])

    TOLERANCE = 0.002   # 0.2% — allow slight overshoot

    if direction == 'LONG':
        # LONG: price must have swept Asian LOW and recovered above it
        swept_asian_low = recent_low <= asian_low * (1 + TOLERANCE)
        recovered       = last_close > asian_low
        passed = swept_asian_low and recovered
        return passed, {
            'london_filter': 'asian_low_swept' if passed else 'asian_low_NOT_swept',
            'asian_low': round(asian_low, 4),
            'recent_low': round(recent_low, 4),
        }
    else:
        # SHORT: price must have swept Asian HIGH and rejected below it
        swept_asian_high = recent_high >= asian_high * (1 - TOLERANCE)
        rejected         = last_close < asian_high
        passed = swept_asian_high and rejected
        return passed, {
            'london_filter': 'asian_high_swept' if passed else 'asian_high_NOT_swept',
            'asian_high': round(asian_high, 4),
            'recent_high': round(recent_high, 4),
        }


def detect_equal_levels(prices: list[float], tolerance_pct: float = 0.2,
                         min_touches: int = 2) -> list[float]:
    """
    Find price levels with multiple touches (equal highs / equal lows).
    Returns list of level prices where >= min_touches touches exist.
    """
    if not prices or len(prices) < min_touches:
        return []

    levels = []
    used = set()

    for i, p in enumerate(prices):
        if i in used:
            continue
        touches = [i]
        for j in range(i + 1, len(prices)):
            if j not in used and abs(prices[j] - p) / p * 100 <= tolerance_pct:
                touches.append(j)

        if len(touches) >= min_touches:
            cluster_price = sum(prices[k] for k in touches) / len(touches)
            levels.append(round(cluster_price, 4))
            used.update(touches)

    return levels


def get_nearest_liquidity(current_price: float, levels: list[float],
                           direction: str, min_r: float = 0.5,
                           r_size: float = None) -> Optional[float]:
    """
    Find nearest unswept liquidity level for TP targeting.
    LONG: nearest level ABOVE current price
    SHORT: nearest level BELOW current price
    min_r: minimum R distance to avoid setting TP too close
    """
    if not levels:
        return None

    if direction == 'LONG':
        candidates = [l for l in levels if l > current_price]
        return min(candidates) if candidates else None
    else:
        candidates = [l for l in levels if l < current_price]
        return max(candidates) if candidates else None


# ── Snapshot — all levels for a symbol at a given time ───────────────────────

@dataclass
class LiquiditySnapshot:
    symbol:       str
    timestamp:    datetime
    pdh:          Optional[float] = None
    pdl:          Optional[float] = None
    pwh:          Optional[float] = None
    pwl:          Optional[float] = None
    asian_high:   Optional[float] = None
    asian_low:    Optional[float] = None
    equal_highs:  list[float]     = field(default_factory=list)
    equal_lows:   list[float]     = field(default_factory=list)

    @classmethod
    def build(cls, symbol: str, now: datetime = None) -> 'LiquiditySnapshot':
        if now is None:
            now = datetime.now(timezone.utc)

        pdh, pdl     = compute_pdh_pdl(symbol, now)
        pwh, pwl     = compute_pwh_pwl(symbol, now)
        a_hi, a_lo   = compute_asian_range(symbol, now)

        # Equal levels from last 24h of 1h candles
        from ingester.models import Candle
        from datetime import timedelta
        recent = list(Candle.objects.filter(
            symbol=symbol, interval='1h', is_closed=True,
            timestamp__gte=now - timedelta(hours=24),
        ).order_by('timestamp').values_list('high', 'low'))

        highs  = [float(h) for h, _ in recent]
        lows   = [float(l) for _, l in recent]
        eq_hi  = detect_equal_levels(highs, tolerance_pct=0.15)
        eq_lo  = detect_equal_levels(lows,  tolerance_pct=0.15)

        return cls(
            symbol=symbol, timestamp=now,
            pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl,
            asian_high=a_hi, asian_low=a_lo,
            equal_highs=eq_hi, equal_lows=eq_lo,
        )

    def all_levels(self) -> list[float]:
        """All known liquidity levels as a flat sorted list."""
        levels = []
        for attr in ('pdh', 'pdl', 'pwh', 'pwl', 'asian_high', 'asian_low'):
            v = getattr(self, attr)
            if v is not None:
                levels.append(v)
        levels.extend(self.equal_highs)
        levels.extend(self.equal_lows)
        return sorted(set(round(l, 4) for l in levels))

    def nearest_above(self, price: float) -> Optional[float]:
        return get_nearest_liquidity(price, self.all_levels(), 'LONG')

    def nearest_below(self, price: float) -> Optional[float]:
        return get_nearest_liquidity(price, self.all_levels(), 'SHORT')

    def is_near_level(self, price: float, tolerance_pct: float = 0.3) -> bool:
        """True if price is within tolerance% of any known level."""
        return any(abs(price - l) / l * 100 <= tolerance_pct for l in self.all_levels())
