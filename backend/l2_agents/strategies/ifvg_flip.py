"""SAI1 inverse-FVG flip plugin."""
from l2_agents.strategy_engine import StrategyPlugin, StrategySpec


class IfvgFlipStrategy(StrategyPlugin):
    spec = StrategySpec(
        strategy_id='SAI1_IFVG_FLIP',
        version='sai1-ifvg-flip-v1',
        display_name='IFVG flip',
        family='IMBALANCE_FLIP',
        status='SHADOW_ONLY',
        required_timeframes=('15m', '1m'),
        compatible_management_policies=(
            'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID',
        ),
        long_zone_kinds=('FVG',),
        short_zone_kinds=('FVG',),
        detector_mode='AI_ADJUDICATED',
        description='FVG invalidation and directional reclaim on a closed 1m candle.',
    )

    def triggered(self, plan, candle) -> bool:
        low, high = float(candle['low']), float(candle['high'])
        opened, close = float(candle['open']), float(candle['close'])
        touched = low <= plan.zone_high and high >= plan.zone_low
        return touched and (
            close > plan.zone_high and close > opened
            if plan.direction == 'LONG'
            else close < plan.zone_low and close < opened
        )


STRATEGY_PLUGIN = IfvgFlipStrategy()
