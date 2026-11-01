"""SAI1 trend-retest plugin."""
from l2_agents.strategy_engine import StrategyPlugin, StrategySpec


class TrendRetestStrategy(StrategyPlugin):
    spec = StrategySpec(
        strategy_id='SAI1_TREND_RETEST',
        version='sai1-trend-retest-v1',
        display_name='Trend retest',
        family='TREND_CONTINUATION',
        status='SHADOW_ONLY',
        required_timeframes=('4h', '1h', '15m', '1m'),
        compatible_management_policies=(
            'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID',
        ),
        long_zone_kinds=('RECENT_SUPPORT', 'FVG'),
        short_zone_kinds=('RECENT_RESISTANCE', 'FVG'),
        detector_mode='AI_ADJUDICATED',
        description='Higher-timeframe trend continuation after a retest and reclaim.',
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


STRATEGY_PLUGIN = TrendRetestStrategy()
