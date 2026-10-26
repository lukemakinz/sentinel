"""S18: S17's order-block continuation entry (regime + structure + OBV —
the best-performing directional mechanism tested in this project, PF 0.66
on development but still short of breakeven), plus a genuinely new evidence
family that no prior strategy in this codebase has used in a backtest:
derivatives-market positioning from Binance's public 'metrics' archive
(open interest, top-trader position ratio) — the same free, unauthenticated
data source already used for klines/funding, at 5-minute granularity.

Two frozen hypotheses layer this on progressively, matching the base/
confluence pattern used throughout S16-S17b:
  - H1 (route 'oi'): open interest must confirm the trade direction over a
    recent window (long: OI non-decreasing — new long positioning behind
    the rally, not a pure short squeeze burning out; short: mirrored). This
    is the classic price/OI quadrant used by derivatives desks: price up +
    OI up = healthy continuation; price up + OI down = squeeze, more likely
    to fade.
  - H2 (route 'oi_toptrader'): H1 PLUS top-trader position ratio must not
    already be at a statistical extreme in the SAME direction as the trade
    (a z-score vs its own trailing distribution) — avoiding entries where
    the "smart money" cohort is already maximally crowded into the move.

Execution (stop management, target cap, breakeven+chandelier trailing) is
intentionally identical to S16/S17/S17b, isolating the new evidence family
as the only variable.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class OrderBlockOIConfig:
    name: str
    route: str  # 'oi' or 'oi_toptrader'
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
    oi_lookback_bars: int = 8
    toptrader_zscore_window: int = 672
    toptrader_extreme_z: float = 1.5
    partial_r: float = 1.0
    trail_atr: float = 1.5
    fixed_risk_usd: float = 0.50
    fixed_margin_usd: float = 25.0
    max_notional_equity: float = 0.50
    max_margin_fraction: float = 0.10
    leverage: float = 5.0
    risk_fraction: float = 0.0020
    trailing: bool = True
    max_hold_minutes: int = 240

    def __post_init__(self):
        if self.route not in ('oi', 'oi_toptrader'):
            raise ValueError('Unknown order block OI confirmation route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.target_r <= 0 or self.oi_lookback_bars < 1
                or self.toptrader_zscore_window < 20 or self.toptrader_extreme_z <= 0
                or self.partial_r <= 0 or self.partial_r >= self.target_r
                or self.trail_atr <= 0 or self.fixed_risk_usd <= 0
                or self.fixed_margin_usd <= 0 or not 0 < self.max_notional_equity <= 1
                or not 0 < self.max_margin_fraction <= 1 or self.leverage < 1
                or not 0 < self.risk_fraction < 1 or self.max_hold_minutes < 1):
            raise ValueError('Invalid order block OI confirmation parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S16/S17/S17b by default (partial_r=1.0, trail_atr=1.5,
        # fixed_risk_usd=0.50) so entry-quality effects stay isolated; S19/S20
        # override the exit shape, S22 overrides position sizing. Actual
        # position size is min(cash * risk_fraction, fixed_risk_usd) — both
        # must be raised together or fixed_risk_usd alone changes nothing.
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=self.partial_r,
            partial_fraction=0.0,
            trailing=self.trailing,
            trail_atr=self.trail_atr,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=self.risk_fraction,
            max_notional_equity=self.max_notional_equity,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=self.leverage,
            max_margin_fraction=self.max_margin_fraction,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=self.fixed_margin_usd,
            fixed_risk_usd=self.fixed_risk_usd,
        )


def central_variants() -> list[OrderBlockOIConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        OrderBlockOIConfig('S18_ob_oi_base', 'oi'),
        OrderBlockOIConfig('S18_ob_oi_toptrader', 'oi_toptrader'),
    ]


def oi_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                 config: OrderBlockOIConfig) -> pd.DataFrame:
    """S17's order-block/regime/OBV features, plus causal OI-change and
    top-trader-positioning z-score. `metrics` is Binance's 5-minute archive
    (backtest.metrics_data.load_metrics); its snapshot values are already
    known as of their own timestamp, same treatment as funding-rate
    settlement elsewhere in this codebase — no additional shift needed."""
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)

    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)

    window = config.toptrader_zscore_window
    ratio = bars.toptrader_position_ratio
    mean = ratio.rolling(window, min_periods=window).mean()
    std = ratio.rolling(window, min_periods=window).std(ddof=0)
    bars['toptrader_zscore'] = (ratio - mean) / std.where(std > 0)
    return bars


def generate_order_block_oi_signals(bars: pd.DataFrame, config: OrderBlockOIConfig,
                                     symbol: str) -> list[dict]:
    """Same zone bookkeeping as S17 (first touch, one attempt per zone),
    plus OI/top-trader confirmation evaluated at the touch bar."""
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close, open_ = (bars.low.to_numpy(), bars.high.to_numpy(),
                               bars.close.to_numpy(), bars.open.to_numpy())
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
    toptrader_zscore = bars.toptrader_zscore.to_numpy()
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
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue
            if config.route == 'oi_toptrader':
                if not np.isfinite(toptrader_zscore[i]):
                    continue
                crowded = (toptrader_zscore[i] >= config.toptrader_extreme_z if side == 1
                          else toptrader_zscore[i] <= -config.toptrader_extreme_z)
                if crowded:
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
                'setup': f'order_block_oi_{config.route}',
                'setup_id': (
                    f'OBOI:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
