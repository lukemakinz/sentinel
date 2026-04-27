"""
Proper FVG (Fair Value Gap) detection with:
- Displacement candle requirement (body > 1.5 × ATR)
- Volume spike confirmation
- Mitigation tracking (price returned to 50%+)
- OTE entry at 50% (mid-FVG), not arbitrary 25%
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FVGZone:
    bottom:    float
    top:       float
    direction: str          # 'bullish' | 'bearish'
    mitigated: bool = False
    created_idx: int = 0    # candle index when FVG formed
    fill_ratio: float = 0.0
    status: str = 'fresh'   # fresh | partial | stale

    @property
    def depth(self) -> float:
        return self.top - self.bottom

    @property
    def mid(self) -> float:
        """50% level — OTE entry zone."""
        return self.bottom + self.depth * 0.5

    @property
    def ote_entry(self) -> float:
        """Optimal Trade Entry — 50% of FVG depth."""
        return self.mid


def find_fvgs_with_displacement(
    candles: list[dict],
    atr: float,
    avg_volume: float = None,
    displacement_atr_mult: float = 1.5,
    vol_multiplier: float = 1.2,
) -> list[FVGZone]:
    """
    Find FVGs where:
    1. Price gap exists between candle[i] and candle[i+2]
    2. Displacement candle (i+1) has body >= displacement_atr_mult × ATR
    3. Volume on displacement candle >= vol_multiplier × avg_volume (if provided)

    Returns list of FVGZone objects.
    """
    if len(candles) < 3 or atr <= 0:
        return []

    if avg_volume is None and len(candles) >= 20:
        avg_volume = sum(c.get('volume', 0) for c in candles[-20:]) / 20

    fvgs = []
    for i in range(len(candles) - 2):
        c0, c1, c2 = candles[i], candles[i + 1], candles[i + 2]

        # Displacement candle: body size
        body = abs(c1['close'] - c1['open'])
        if body < displacement_atr_mult * atr:
            continue

        # Volume check (optional)
        if avg_volume and avg_volume > 0:
            if c1.get('volume', avg_volume) < vol_multiplier * avg_volume:
                continue

        # Bullish FVG: gap between c0.high and c2.low
        if c0['high'] < c2['low']:
            fvgs.append(FVGZone(
                bottom=float(c0['high']),
                top=float(c2['low']),
                direction='bullish',
                created_idx=i,
            ))

        # Bearish FVG: gap between c2.high and c0.low
        if c2['high'] < c0['low']:
            fvgs.append(FVGZone(
                bottom=float(c2['high']),
                top=float(c0['low']),
                direction='bearish',
                created_idx=i,
            ))

    return fvgs


def is_fvg_mitigated(fvg: FVGZone, low: float = None, high: float = None) -> bool:
    """
    FVG is mitigated when price retraces to 50%+ of the gap.
    Bullish FVG: price drops to mid or below
    Bearish FVG: price rises to mid or above
    """
    if fvg.direction == 'bullish' and low is not None:
        return low <= fvg.mid
    if fvg.direction == 'bearish' and high is not None:
        return high >= fvg.mid
    return False


def get_active_fvgs(candles: list[dict], atr: float, direction: str) -> list[FVGZone]:
    """Return non-mitigated FVGs in the given direction from recent candles."""
    all_fvgs = find_fvgs_with_displacement(candles, atr)
    relevant = [f for f in all_fvgs if f.direction == direction]

    # Mark as mitigated if price has returned to mid after formation
    closes = [c['close'] for c in candles]
    lows   = [c['low']   for c in candles]
    highs  = [c['high']  for c in candles]

    active = []
    for fvg in relevant:
        max_fill_ratio = 0.0
        for j in range(fvg.created_idx + 3, len(candles)):
            if direction == 'bullish':
                intrusion = max(0.0, fvg.top - lows[j])
            else:
                intrusion = max(0.0, highs[j] - fvg.bottom)
            fill_ratio = min(max(intrusion / max(fvg.depth, 1e-9), 0.0), 1.0)
            max_fill_ratio = max(max_fill_ratio, fill_ratio)

        fvg.fill_ratio = round(max_fill_ratio, 4)
        if max_fill_ratio < 0.25:
            fvg.status = 'fresh'
        elif max_fill_ratio < 0.5:
            fvg.status = 'partial'
        else:
            fvg.status = 'stale'

        if fvg.status != 'stale':
            active.append(fvg)

    return active
