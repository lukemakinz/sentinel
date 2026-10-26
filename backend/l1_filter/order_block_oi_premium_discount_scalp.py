"""S37: S20 H1's exact entry+exit (order block + OI confirmation, patient
exit) plus ICT premium/discount — the one classic ICT confluence concept
from the original team brief (analyst + order-block trader + ICT trader +
price-action trader) never tested standalone in this project's S16-S30
lineage, though its formula already exists in gates_b.check_premium_discount
for the live scanner. "Buy cheap relative to the recent range, sell
expensive relative to it": a long retest must occur in the lower half (H1)
or the tighter 62-79% OTE band (H2) of the trailing swing range; mirrored
for shorts.

Swing range is a rolling 320-bar (80h / ~3.3 day) high/low on the same 15m
series S20 already uses — not a separate HTF fetch, kept simple and causal.

Execution (stop management, target cap, breakeven+chandelier trailing) is
identical to S20 H1, isolating premium/discount as the only new variable.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class OrderBlockPremiumDiscountConfig:
    name: str
    route: str  # 'half_range' or 'ote_zone'
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20
    zone_ttl_bars: int = 32
    stop_buffer_atr_mult: float = 0.15
    obv_ema_period: int = 9
    oi_lookback_bars: int = 8
    swing_lookback_bars: int = 320
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0

    def __post_init__(self):
        if self.route not in ('half_range', 'ote_zone'):
            raise ValueError('Unknown premium/discount route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.oi_lookback_bars < 1 or self.swing_lookback_bars < 10
                or self.partial_r <= 0 or self.partial_r >= self.target_r
                or self.trail_atr <= 0):
            raise ValueError('Invalid premium/discount parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S20 H1 on purpose — isolates premium/discount as the
        # only new variable.
        return ScalpConfig(
            name=self.name, minutes=15, target_r=self.target_r, partial_r=self.partial_r,
            partial_fraction=0.0, trailing=True, trail_atr=self.trail_atr,
            max_hold_minutes=240, risk_fraction=0.0020, max_notional_equity=0.50,
            daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
            min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
            margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
            fixed_margin_usd=25.0, fixed_risk_usd=0.50,
        )


def central_variants() -> list[OrderBlockPremiumDiscountConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        OrderBlockPremiumDiscountConfig('S37_premium_discount_half', 'half_range'),
        OrderBlockPremiumDiscountConfig('S37_premium_discount_ote', 'ote_zone'),
    ]


def premium_discount_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                              config: OrderBlockPremiumDiscountConfig) -> pd.DataFrame:
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)

    n = config.swing_lookback_bars
    bars['swing_high'] = bars.high.rolling(n, min_periods=n).max()
    bars['swing_low'] = bars.low.rolling(n, min_periods=n).min()
    return bars


def generate_premium_discount_signals(bars: pd.DataFrame, config: OrderBlockPremiumDiscountConfig,
                                       symbol: str) -> list[dict]:
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
    swing_high, swing_low = bars.swing_high.to_numpy(), bars.swing_low.to_numpy()
    ob_bull_confirmed = bars.ob_bull_confirmed.to_numpy()
    ob_bull_top, ob_bull_bottom = bars.ob_bull_top.to_numpy(), bars.ob_bull_bottom.to_numpy()
    ob_bear_confirmed = bars.ob_bear_confirmed.to_numpy()
    ob_bear_top, ob_bear_bottom = bars.ob_bear_top.to_numpy(), bars.ob_bear_bottom.to_numpy()

    active = {1: [], -1: []}
    records = []
    for i in range(n):
        active[1] = [z for z in active[1] if z['expires'] > i]
        active[-1] = [z for z in active[-1] if z['expires'] > i]

        if ob_bull_confirmed[i] and np.isfinite(ob_bull_top[i]) and np.isfinite(ob_bull_bottom[i]):
            active[1].append({'top': float(ob_bull_top[i]), 'bottom': float(ob_bull_bottom[i]),
                              'expires': i + config.zone_ttl_bars})
        if ob_bear_confirmed[i] and np.isfinite(ob_bear_top[i]) and np.isfinite(ob_bear_bottom[i]):
            active[-1].append({'top': float(ob_bear_top[i]), 'bottom': float(ob_bear_bottom[i]),
                               'expires': i + config.zone_ttl_bars})

        if not np.isfinite(atr[i]) or not np.isfinite(swing_high[i]) or not np.isfinite(swing_low[i]):
            continue
        rng = swing_high[i] - swing_low[i]
        if rng <= 0:
            continue

        for side in (1, -1):
            if side == 1:
                touched = [z for z in active[1] if low[i] <= z['top'] and close[i] >= z['bottom']]
            else:
                touched = [z for z in active[-1] if high[i] >= z['bottom'] and close[i] <= z['top']]
            if not touched:
                continue
            for z in touched:
                active[side].remove(z)

            regime_ok = htf_trend_up[i] if side == 1 else htf_trend_down[i]
            if not (regime_ok and htf_adx[i] >= config.adx_threshold):
                continue
            flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue
            if not np.isfinite(oi_change[i]):
                continue
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue

            if config.route == 'half_range':
                midpoint = (swing_high[i] + swing_low[i]) / 2
                zone_ok = close[i] < midpoint if side == 1 else close[i] > midpoint
            else:
                if side == 1:
                    ote_low = swing_high[i] - 0.79 * rng
                    ote_high = swing_high[i] - 0.62 * rng
                else:
                    ote_low = swing_low[i] + 0.62 * rng
                    ote_high = swing_low[i] + 0.79 * rng
                zone_ok = ote_low <= close[i] <= ote_high
            if not zone_ok:
                continue

            zone = touched[0]
            stop = (zone['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                    else zone['top'] + config.stop_buffer_atr_mult * atr[i])
            risk = side * (close[i] - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': bars.index[i], 'side': side, 'reference': float(close[i]),
                'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 3.0,
                'atr': float(atr[i]), 'score': 6,
                'setup': f'order_block_premium_discount_{config.route}',
                'setup_id': (
                    f'OBPD:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
