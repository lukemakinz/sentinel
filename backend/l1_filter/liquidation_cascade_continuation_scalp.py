"""S39: Liquidation-cascade CONTINUATION -- the directional complement to
S38, which faded the same cascade signature (ATR-outlier range + volume
spike + outlier open-interest drop in one 15m bar) and lost clearly on base
costs alone (PF 0.45 and 0.55 across both entry-timing routes, not a
marginal miss). A clean loss on the fade side is itself information: it
means, in this data, forced-deleveraging candles tend to continue rather
than mean-revert. This protocol tests that directional complement once,
under the exact same detection formula and gates -- not a parameter
adjustment of S38, a flip of which side of the trade the same signal takes.

Entry is WITH the cascade direction. Stop sits at the cascade bar's own
midpoint (its close-time 50% level, the same "half-range" convention S37
already used for premium/discount) rather than beyond the far extreme,
since a retrace back through the middle of the forcing candle invalidates
the continuation thesis. Exit reuses S20's patient breakeven+chandelier
runner unmodified (target_r=8, trail_atr=2.5, partial_r=1.5) -- the one
execution style anywhere in this project's 38 prior routes that has shown
genuine, if stress-fragile, edge -- a principled reuse, not cherry-picking:
if a forced-flow continuation candle behaves like an order-block
continuation, the same patient runner that worked for one should be tried
on the other before any new execution parameters are invented.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class CascadeContinuationConfig:
    name: str
    route: str  # 'immediate' or 'confirmed'
    displacement_atr_mult: float = 2.5
    volume_mult: float = 2.5
    volume_avg_lookback: int = 20
    oi_lookback_bars: int = 2
    oi_zscore_window: int = 96
    oi_extreme_z: float = 2.0
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0

    def __post_init__(self):
        if self.route not in ('immediate', 'confirmed'):
            raise ValueError('Unknown cascade continuation route')
        if (self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.oi_lookback_bars < 1
                or self.oi_zscore_window < 20 or self.oi_extreme_z <= 0
                or self.partial_r <= 0 or self.partial_r >= self.target_r
                or self.trail_atr <= 0):
            raise ValueError('Invalid cascade continuation parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S20 H1 on purpose -- see module docstring.
        return ScalpConfig(
            name=self.name, minutes=15, target_r=self.target_r, partial_r=self.partial_r,
            partial_fraction=0.0, trailing=True, trail_atr=self.trail_atr,
            max_hold_minutes=240, risk_fraction=0.0020, max_notional_equity=0.50,
            daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
            min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
            margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
            fixed_margin_usd=25.0, fixed_risk_usd=0.50,
        )


def central_variants() -> list[CascadeContinuationConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        CascadeContinuationConfig('S39_cascade_continuation_immediate', 'immediate'),
        CascadeContinuationConfig('S39_cascade_continuation_confirmed', 'confirmed'),
    ]


def cascade_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                      config: CascadeContinuationConfig) -> pd.DataFrame:
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


def generate_cascade_signals(bars: pd.DataFrame, config: CascadeContinuationConfig,
                              symbol: str) -> list[dict]:
    """Identical cascade detection to S38. Trade WITH the cascade direction
    instead of against it. Stop sits at the cascade bar's own midpoint
    (a retrace through the middle of the forcing candle invalidates the
    continuation thesis)."""
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
            continue
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue

        cascade_down = close[i] < open_[i]
        side = -1 if cascade_down else 1  # trade WITH the cascade direction
        midpoint = (high[i] + low[i]) / 2.0

        if config.route == 'immediate':
            entry_i, reference = i, float(close[i])
        else:
            entry_i = i + 1
            if entry_i >= n:
                continue
            confirm_ok = (close[entry_i] < open_[entry_i] if side == -1
                          else close[entry_i] > open_[entry_i])
            if not confirm_ok:
                continue
            reference = float(close[entry_i])

        stop = midpoint
        risk = side * (reference - stop)
        if risk <= 0:
            continue

        direction = 'long' if side == 1 else 'short'
        timestamp = bars.index[entry_i]
        records.append({
            'timestamp': timestamp, 'side': side, 'reference': reference,
            'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 4.0,
            'atr': float(atr[i]), 'score': 6,
            'setup': f'liquidation_cascade_continuation_{config.route}',
            'setup_id': f'LCC:v1:{config.route}:{symbol}:{direction}:{timestamp.isoformat()}',
        })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
