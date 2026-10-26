"""S38: Liquidation-cascade fade -- a mechanism deliberately different from
every S16-S37 route, all of which traded WITH established structure (an
order block, a trend regime, a divergence pivot). This one trades AGAINST a
single forced-deleveraging candle: a 15m bar whose range is an ATR outlier,
whose volume is a spike, AND whose open-interest change is an outlier drop
(positions being closed, not opened -- the signature of liquidations, not
organic trend continuation). The bet is that a cascade wick overshoots and
partially mean-reverts once the forced selling/buying is exhausted, so entry
is against the cascade direction, not with it.

No order block, no HTF trend/ADX regime filter, no OBV flow filter -- all
deliberately absent: those encode "trade with structure", which is the
opposite thesis being tested here. Every other project mechanism has failed
gates while assuming trend/structure continuation; this isolates whether a
forced-flow mean-reversion signature fares differently.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class CascadeFadeConfig:
    name: str
    route: str  # 'immediate' or 'confirmed'
    displacement_atr_mult: float = 2.5
    volume_mult: float = 2.5
    volume_avg_lookback: int = 20
    oi_lookback_bars: int = 2
    oi_zscore_window: int = 96
    oi_extreme_z: float = 2.0
    stop_buffer_atr_mult: float = 0.15
    target_r: float = 3.0
    trail_atr: float = 1.5
    partial_r: float = 1.0

    def __post_init__(self):
        if self.route not in ('immediate', 'confirmed'):
            raise ValueError('Unknown cascade fade route')
        if (self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.oi_lookback_bars < 1
                or self.oi_zscore_window < 20 or self.oi_extreme_z <= 0
                or self.stop_buffer_atr_mult < 0
                or self.target_r <= self.partial_r or self.partial_r <= 0
                or self.trail_atr <= 0):
            raise ValueError('Invalid cascade fade parameters')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name, minutes=15, target_r=self.target_r, partial_r=self.partial_r,
            partial_fraction=0.0, trailing=True, trail_atr=self.trail_atr,
            max_hold_minutes=180, risk_fraction=0.0020, max_notional_equity=0.50,
            daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
            min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
            margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
            fixed_margin_usd=25.0, fixed_risk_usd=0.50,
        )


def central_variants() -> list[CascadeFadeConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        CascadeFadeConfig('S38_cascade_fade_immediate', 'immediate'),
        CascadeFadeConfig('S38_cascade_fade_confirmed', 'confirmed'),
    ]


def cascade_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                      config: CascadeFadeConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    high, low, close = bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy()
    bars['atr'] = talib.ATR(high, low, close, timeperiod=14)

    volume_baseline = bars.volume.shift(1).rolling(config.volume_avg_lookback).mean()
    bars['volume_spike'] = bars.volume >= config.volume_mult * volume_baseline
    bar_range = bars.high - bars.low
    bars['range_spike'] = bar_range >= config.displacement_atr_mult * bars.atr

    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)
    window = config.oi_zscore_window
    mean = bars.oi_change.rolling(window, min_periods=window).mean()
    std = bars.oi_change.rolling(window, min_periods=window).std()
    bars['oi_zscore'] = (bars.oi_change - mean) / std.where(std > 0)
    return bars


def generate_cascade_signals(bars: pd.DataFrame, config: CascadeFadeConfig,
                              symbol: str) -> list[dict]:
    """A cascade bar is an ATR-outlier range on a volume spike with an
    outlier drop in open interest in the SAME bar (liquidations, not fresh
    trend positioning). Fade it: enter against the cascade direction, stop
    beyond its extreme. Route 'immediate' enters as soon as the cascade bar
    closes; 'confirmed' additionally requires the very next bar to close
    back in the fade direction before entering (costs one bar of delay, but
    filters cascades that are still actively continuing)."""
    n = len(bars)
    atr = bars.atr.to_numpy()
    high, low, close, open_ = (bars.high.to_numpy(), bars.low.to_numpy(),
                               bars.close.to_numpy(), bars.open.to_numpy())
    range_spike = bars.range_spike.to_numpy()
    volume_spike = bars.volume_spike.to_numpy()
    oi_zscore = bars.oi_zscore.to_numpy()

    records = []
    for i in range(n):
        if not (range_spike[i] and volume_spike[i]):
            continue
        if not np.isfinite(oi_zscore[i]) or oi_zscore[i] > -config.oi_extreme_z:
            continue  # no outlier OI drop -> not a liquidation signature
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue

        cascade_down = close[i] < open_[i]  # forced longs liquidated -> fade with a long
        side = 1 if cascade_down else -1
        cascade_extreme = low[i] if side == 1 else high[i]

        if config.route == 'immediate':
            entry_i, reference = i, float(close[i])
        else:
            entry_i = i + 1
            if entry_i >= n:
                continue
            confirm_ok = (close[entry_i] > open_[entry_i] if side == 1
                          else close[entry_i] < open_[entry_i])
            if not confirm_ok:
                continue
            reference = float(close[entry_i])

        stop = cascade_extreme - side * config.stop_buffer_atr_mult * atr[i]
        risk = side * (reference - stop)
        if risk <= 0:
            continue

        direction = 'long' if side == 1 else 'short'
        timestamp = bars.index[entry_i]
        records.append({
            'timestamp': timestamp, 'side': side, 'reference': reference,
            'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 4.0,
            'atr': float(atr[i]), 'score': 6,
            'setup': f'liquidation_cascade_fade_{config.route}',
            'setup_id': f'LCF:v1:{config.route}:{symbol}:{direction}:{timestamp.isoformat()}',
        })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
