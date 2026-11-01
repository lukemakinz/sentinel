"""SAI1 failed-auction plugin."""
from __future__ import annotations

from types import MappingProxyType

from l2_agents.strategy_engine import (
    StrategyCandidate,
    StrategyPlugin,
    StrategyScan,
    StrategySpec,
)


MAX_ZONE_DISTANCE_ATR = 2.0


class FailedAuctionStrategy(StrategyPlugin):
    spec = StrategySpec(
        strategy_id='SAI1_FAILED_AUCTION',
        version='sai1-failed-auction-v1',
        display_name='Failed auction',
        family='LIQUIDITY_REVERSAL',
        status='SHADOW_ONLY',
        required_timeframes=('15m', '1m'),
        compatible_management_policies=(
            'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID',
        ),
        long_zone_kinds=('RECENT_SUPPORT', 'FVG'),
        short_zone_kinds=('RECENT_RESISTANCE', 'FVG'),
        default_ttl_minutes=60,
        max_ttl_minutes=120,
        detector_mode='MECHANICAL',
        description='Sweep beyond a supplied extreme followed by a closed-bar reclaim.',
    )

    def scan(self, snapshot: dict) -> StrategyScan:
        """Frozen M0 detector, moved behind the common plugin contract."""
        quality = snapshot.get('data_quality') or {}
        if not quality.get('tradable'):
            return StrategyScan(diagnostics=('Data quality not tradable.',))
        regime = (snapshot.get('global_regime') or {}).get('state')
        tf15 = (snapshot.get('instrument') or {}).get('15m') or {}
        close = tf15.get('close')
        atr = tf15.get('atr14')
        if not close or not atr or atr <= 0:
            return StrategyScan(diagnostics=('Missing 15m close or ATR.',))

        zones = {zone['kind']: zone for zone in snapshot.get('zones') or []}
        candidates: list[tuple[str, dict, float]] = []
        support = zones.get('RECENT_SUPPORT')
        resistance = zones.get('RECENT_RESISTANCE')
        if support and regime in {'TREND_UP', 'RANGE'}:
            candidates.append(('LONG', support, (close - support['high']) / atr))
        if resistance and regime in {'TREND_DOWN', 'RANGE'}:
            candidates.append(('SHORT', resistance, (resistance['low'] - close) / atr))
        candidates = [
            item for item in candidates
            if 0 <= item[2] <= MAX_ZONE_DISTANCE_ATR
        ]
        if not candidates:
            return StrategyScan(diagnostics=(
                f'No regime-aligned extreme within {MAX_ZONE_DISTANCE_ATR:g} ATR ({regime}).',
            ))

        direction, zone, distance = min(candidates, key=lambda item: item[2])
        low, high = float(zone['low']), float(zone['high'])
        if direction == 'LONG':
            trigger = f'1m close above {high} after trading below {low}'
            invalidation = 'Structural stop below the swept support'
        else:
            trigger = f'1m close below {low} after trading above {high}'
            invalidation = 'Structural stop above the swept resistance'
        return StrategyScan(candidates=(StrategyCandidate(
            strategy_id=self.spec.strategy_id,
            direction=direction,
            entry_zone=(low, high),
            trigger_conditions=(trigger,),
            invalidation_conditions=(invalidation,),
            thesis=(f'{regime} regime; 20-bar extreme {distance:.2f} ATR away.',),
            ttl_minutes=self.spec.default_ttl_minutes,
            metadata=MappingProxyType({
                'regime': regime,
                'distance_atr': float(distance),
            }),
        ),))

    def triggered(self, plan, candle) -> bool:
        low = float(candle['low'])
        high = float(candle['high'])
        close = float(candle['close'])
        return (
            low < plan.zone_low and close > plan.zone_high
            if plan.direction == 'LONG'
            else high > plan.zone_high and close < plan.zone_low
        )


STRATEGY_PLUGIN = FailedAuctionStrategy()
