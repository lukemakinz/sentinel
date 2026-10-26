"""S17b: same order-block regime/structure/flow evidence as S17, but fixes
the mechanism that made S17 lose — 84% of S17's trades hit a full stop
because "first touch of the zone" fired on weak, noisy dips, not genuine
reactions. This is the identical fix that turned S8 into the (still losing,
but meaningfully better) S8v2 in this project's history: don't enter on the
touch alone, require a rejection candle first (wick into the zone, close
back on the correct side, directional body, close in the outer part of the
bar's own range).

A zone now persists through weak touches instead of being consumed by them:
it is only removed when price closes clean through it (invalidated, no
trade) or when a genuine rejection candle occurs (one attempt, taken or
not, per zone — same "first mitigation" discipline as S17).
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig, divergence_events


@dataclass(frozen=True)
class OrderBlockRejectionConfig:
    name: str
    route: str  # 'base' or 'divergence'
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20
    zone_ttl_bars: int = 32
    stop_buffer_atr_mult: float = 0.15
    obv_ema_period: int = 9
    target_r: float = 5.0
    rejection_close_position: float = 0.6

    def __post_init__(self):
        if self.route not in ('base', 'divergence'):
            raise ValueError('Unknown order block rejection route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.target_r <= 1 or not 0.5 <= self.rejection_close_position <= 1.0):
            raise ValueError('Invalid order block rejection parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S16/S17 on purpose — isolates entry-quality effects.
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=True,
            trail_atr=1.5,
            max_hold_minutes=240,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=5.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
        )


def central_variants() -> list[OrderBlockRejectionConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        OrderBlockRejectionConfig('S17b_ob_rejection_base', 'base'),
        OrderBlockRejectionConfig('S17b_ob_rejection_divergence', 'divergence'),
    ]


def _recent(event: np.ndarray, window: int = 3) -> np.ndarray:
    return pd.Series(event).rolling(window, min_periods=1).max().astype(bool).to_numpy()


def generate_order_block_rejection_signals(bars: pd.DataFrame, config: OrderBlockRejectionConfig,
                                            symbol: str) -> list[dict]:
    """Same zone bookkeeping as S17, except a zone survives a weak touch and
    is only consumed by invalidation (clean close through it) or a genuine
    rejection candle (one attempt, taken or not, per zone)."""
    recent_div = {}
    if config.route == 'divergence':
        for side in (1, -1):
            events, _ = divergence_events(bars, side)
            recent_div[side] = _recent(events)

    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close, open_ = (bars.low.to_numpy(), bars.high.to_numpy(),
                               bars.close.to_numpy(), bars.open.to_numpy())
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
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

        if not np.isfinite(atr[i]):
            continue

        candle_range = high[i] - low[i]
        for side in (1, -1):
            surviving = []
            fired = False
            for z in active[side]:
                if side == 1:
                    entered = low[i] <= z['top']
                    invalidated = close[i] < z['bottom']
                else:
                    entered = high[i] >= z['bottom']
                    invalidated = close[i] > z['top']
                if not entered:
                    surviving.append(z)
                    continue
                if invalidated:
                    continue  # consumed: mitigated without holding

                if candle_range <= 0:
                    surviving.append(z)  # doji at the zone: not a rejection, try again later
                    continue
                if side == 1:
                    close_pos = (close[i] - low[i]) / candle_range
                    rejection = close[i] > open_[i] and close_pos >= config.rejection_close_position
                else:
                    close_pos = (high[i] - close[i]) / candle_range
                    rejection = close[i] < open_[i] and close_pos >= config.rejection_close_position
                if not rejection:
                    surviving.append(z)  # weak touch: zone stays active
                    continue

                # Consumed by a genuine rejection candle: one attempt, whether
                # or not it clears the other filters below.
                if not fired:
                    regime_ok = htf_trend_up[i] if side == 1 else htf_trend_down[i]
                    flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
                    div_ok = True if config.route == 'base' else recent_div[side][i]
                    if regime_ok and htf_adx[i] >= config.adx_threshold and flow_ok and div_ok:
                        stop = (z['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                                else z['top'] + config.stop_buffer_atr_mult * atr[i])
                        risk = side * (close[i] - stop)
                        if risk > 0:
                            direction = 'long' if side == 1 else 'short'
                            records.append({
                                'timestamp': bars.index[i],
                                'side': side,
                                'reference': float(close[i]),
                                'stop': float(stop),
                                'min_stop_atr': 0.5,
                                'max_stop_atr': 3.0,
                                'atr': float(atr[i]),
                                'score': 6,
                                'setup': f'order_block_rejection_{config.route}',
                                'setup_id': (
                                    f'OBR:v1:{config.route}:{symbol}:{direction}:'
                                    f'{bars.index[i].isoformat()}'
                                ),
                            })
                            fired = True
                # zone consumed either way (rejection attempted); drop it
            active[side] = surviving

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
