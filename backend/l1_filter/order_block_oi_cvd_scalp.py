"""S26: S20's entry (order block + OI confirmation, patient exit) with
cumulative volume delta (CVD — actual taker buy/sell volume, already
computed by order_block_continuation_scalp.order_block_features for S17's
divergence route but never used by S18/S20) tested as a flow confirmation
in two different roles:

  - H1 (route 'oi_cvd_flow'): CVD REPLACES OBV as the flow confirmation.
    OBV only looks at whether each candle's CLOSE moved up or down (a crude
    proxy); CVD is built from the actual taker buy/sell volume split, a
    more precise read of aggressor flow. Otherwise identical to S20 H1.
  - H2 (route 'oi_cvd_divergence'): S20 H1 UNCHANGED (OBV kept) PLUS a
    recent CVD-price divergence pivot required (reusing
    scalp_strategy.divergence_events, the same causal, already-tested pivot
    detector S17's divergence route used for RSI) — price and aggressor
    flow disagreeing at the touch bar as an extra confirmation that this
    reaction is real, not just a coincidental OI/OBV alignment.

Execution (stop management, target cap, breakeven+chandelier trailing) is
identical to S20 H1, isolating the CVD role as the only variable.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig, divergence_events


@dataclass(frozen=True)
class OrderBlockCVDConfig:
    name: str
    route: str  # 'oi_cvd_flow' or 'oi_cvd_divergence'
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20
    zone_ttl_bars: int = 32
    stop_buffer_atr_mult: float = 0.15
    obv_ema_period: int = 9
    cvd_ema_period: int = 9
    oi_lookback_bars: int = 8
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0

    def __post_init__(self):
        if self.route not in ('oi_cvd_flow', 'oi_cvd_divergence'):
            raise ValueError('Unknown order block CVD route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.cvd_ema_period < 1 or self.oi_lookback_bars < 1
                or self.partial_r <= 0 or self.partial_r >= self.target_r
                or self.trail_atr <= 0):
            raise ValueError('Invalid order block CVD parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S20 H1 on purpose — isolates the CVD role as the only
        # variable.
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=self.partial_r,
            partial_fraction=0.0,
            trailing=True,
            trail_atr=self.trail_atr,
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


def central_variants() -> list[OrderBlockCVDConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        OrderBlockCVDConfig('S26_ob_oi_cvd_flow', 'oi_cvd_flow'),
        OrderBlockCVDConfig('S26_ob_oi_cvd_divergence', 'oi_cvd_divergence'),
    ]


def _recent(event: np.ndarray, window: int = 3) -> np.ndarray:
    return pd.Series(event).rolling(window, min_periods=1).max().astype(bool).to_numpy()


def cvd_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                 config: OrderBlockCVDConfig) -> pd.DataFrame:
    """S18's order-block/regime/OBV/OI features plus a CVD EMA for the flow
    role. `order_block_features` already computes `cvd` and `rsi14` (used by
    S17's divergence route) — reused here, not recomputed."""
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)
    bars['cvd_ema'] = bars.cvd.ewm(span=config.cvd_ema_period, adjust=False).mean()
    return bars


def generate_cvd_signals(bars: pd.DataFrame, config: OrderBlockCVDConfig,
                          symbol: str) -> list[dict]:
    """Same zone bookkeeping as S18/S20 (first touch, one attempt per zone)."""
    recent_cvd_div = {}
    if config.route == 'oi_cvd_divergence':
        for side in (1, -1):
            _, cvd_events = divergence_events(bars, side)
            recent_cvd_div[side] = _recent(cvd_events)

    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    cvd, cvd_ema = bars.cvd.to_numpy(), bars.cvd_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
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

            if config.route == 'oi_cvd_flow':
                flow_ok = cvd[i] > cvd_ema[i] if side == 1 else cvd[i] < cvd_ema[i]
            else:
                flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue

            if not np.isfinite(oi_change[i]):
                continue
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue

            if config.route == 'oi_cvd_divergence' and not recent_cvd_div[side][i]:
                continue

            zone = touched[0]
            stop = (zone['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                    else zone['top'] + config.stop_buffer_atr_mult * atr[i])
            risk = side * (close[i] - stop)
            if risk <= 0:
                continue
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
                'setup': f'order_block_cvd_{config.route}',
                'setup_id': (
                    f'OBCVD:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
