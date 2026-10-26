"""S44A: S20's exact entry/exit, with exactly one change -- the open
interest confirmation is corrected from an asymmetric sign flip
(`oi_change >= 0` for longs, `oi_change <= 0` for shorts) to the same
condition for both sides (`oi_change >= 0`), matching the classic
price/OI quadrant this project's own S18 docstring already claimed to
implement: "healthy continuation" means fresh capital entering in the
trade's direction (OI rising), for EITHER a long or a short, not merely
the opposite side capitulating. The as-shipped code instead required OI
FALLING for shorts -- the long-liquidation/exhaustion quadrant, not the
fresh-short-interest continuation quadrant -- an asymmetry inconsistent
with the strategy's own stated rationale, flagged by an outside trader
review of S43.

This is the smallest possible isolated test of that one hypothesis: every
other parameter, both hypotheses (patient/very-patient exit, matching
S20's own H1/H2), the universe and the windows are copied unmodified from
S20 (docs/research/s20_ob_oi_patient_runner). If this alone changes the
outcome materially, the bug explains part of this project's short-side
fragility across the entire S18-S43 lineage, which all share the buggy
function. If it does not, the bug was real but not load-bearing for this
project's results.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class OrderBlockOIFixedConfig:
    name: str
    route: str  # 'patient' or 'very_patient' -- matches S20 H1/H2 exactly
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

    def __post_init__(self):
        if self.route not in ('patient', 'very_patient'):
            raise ValueError('Unknown OI-fixed route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.oi_lookback_bars < 1):
            raise ValueError('Invalid OI-fixed parameters')

    def execution(self) -> ScalpConfig:
        # H1='patient' copies S20 H1 exactly (partial_r=1.5, trail_atr=2.5,
        # target_r=8.0); H2='very_patient' copies S20 H2 exactly
        # (partial_r=2.0, trail_atr=3.0, target_r=10.0). No other change.
        partial_r, trail_atr, target_r = (
            (1.5, 2.5, 8.0) if self.route == 'patient' else (2.0, 3.0, 10.0)
        )
        return ScalpConfig(
            name=self.name, minutes=15, target_r=target_r, partial_r=partial_r,
            partial_fraction=0.0, trailing=True, trail_atr=trail_atr,
            max_hold_minutes=240, risk_fraction=0.0020, max_notional_equity=0.50,
            daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
            min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
            margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
            fixed_margin_usd=25.0, fixed_risk_usd=0.50,
        )


def central_variants() -> list[OrderBlockOIFixedConfig]:
    return [
        OrderBlockOIFixedConfig('S44A_ob_oi_fixed_patient', 'patient'),
        OrderBlockOIFixedConfig('S44A_ob_oi_fixed_very_patient', 'very_patient'),
    ]


def oi_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                 config: OrderBlockOIFixedConfig) -> pd.DataFrame:
    """Identical to order_block_oi_confirmation_scalp.oi_features -- the bug
    is in signal generation, not feature computation."""
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)
    return bars


def generate_fixed_signals(bars: pd.DataFrame, config: OrderBlockOIFixedConfig,
                            symbol: str) -> list[dict]:
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
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
            flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue
            if not np.isfinite(oi_change[i]):
                continue
            # THE FIX: OI must be rising for BOTH longs and shorts -- fresh
            # capital entering in the trade's direction, for either side,
            # not a sign flip. This is the only line that differs from
            # order_block_oi_confirmation_scalp.generate_order_block_oi_signals.
            if not oi_change[i] >= 0:
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
                'setup': f'order_block_oi_fixed_{config.route}',
                'setup_id': (
                    f'OBOIF:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
