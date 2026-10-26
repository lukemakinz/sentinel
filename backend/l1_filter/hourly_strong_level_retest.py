"""S88: hourly implementation of the single Strong Level Retest hypothesis.

S87 established that 4h zones were too sparse to evaluate.  This successor
keeps the same causal score and pre-armed first-retest entry, but forms zones
on closed 1h bars.  It is a replacement research candidate, not a second
portfolio strategy.
"""
from dataclasses import dataclass

import pandas as pd

from .scalp_strategy import ScalpConfig, resample_closed
from .strong_level_retest import (
    prepare_four_hour_bars,
    strong_level_events_from_bars,
)


@dataclass(frozen=True)
class HourlyStrongLevelRetestConfig:
    name: str = 'S88_hourly_strong_level_retest'
    swing_width: int = 2
    structure_lookback: int = 240
    cluster_atr: float = 0.45
    min_prior_touches: int = 2
    displacement_atr: float = 1.50
    volume_multiple: float = 1.25
    min_score: float = 70.0
    entry_fraction: float = 0.50
    stop_buffer_atr: float = 0.20
    validity_hours: int = 36
    target_r: float = 3.0
    min_target_r: float = 2.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.5,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=24 * 60,
            risk_fraction=0.0020,
            max_notional_equity=1.0,
            daily_loss_fraction=0.010,
            weekly_loss_fraction=0.018,
            drawdown_risk_scale_fraction=0.040,
            drawdown_halt_fraction=0.060,
            fee_bps=5.0,
            maker_fee_bps=2.0,
            slippage_bps=2.0,
            limit_penetration_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=5.0,
            max_margin_fraction=0.20,
            margin_safety_reserve=0.01,
            max_positions=1,
        )


def hourly_level_features(minutes: pd.DataFrame) -> pd.DataFrame:
    # prepare_four_hour_bars operates on any complete OHLCV bar frame; its
    # historical name is retained so the frozen S87 implementation is intact.
    return prepare_four_hour_bars(resample_closed(minutes, 60))


def hourly_strong_level_signals(
    minutes: pd.DataFrame,
    config: HourlyStrongLevelRetestConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    bars = hourly_level_features(minutes)
    events = strong_level_events_from_bars(bars, config)
    signals = []
    for event in events:
        signals.append({
            'timestamp': event['created_at'],
            'side': event['side'],
            'reference': float(bars.loc[event['created_at'], 'close']),
            'stop': event['stop'],
            'atr': event['atr4h'],
            'limit_price': event['entry'],
            'limit_ttl_minutes': config.validity_hours * 60,
            'target_price': event['target'],
            'min_target_r': config.min_target_r,
            'min_stop_atr': 0.20,
            'max_stop_atr': 1.50,
            'score': event['score'],
            'setup': 'hourly_strong_ob_sr_first_retest',
            'setup_id': event['setup_id'],
            'order_block': [event['bottom'], event['top']],
            'evidence': {
                'score_components': event['score_components'],
                'prior_sr_touches': event['prior_touches'],
                'displacement_atr': event['displacement_atr'],
                'origin_volume_ratio': event['volume_ratio'],
                'trend_aligned': event['trend_aligned'],
                'armed_before_retest': True,
                'zone_timeframe': '1h',
            },
        })
    signals.sort(key=lambda item: item['timestamp'])
    return bars, signals
