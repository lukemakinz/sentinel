"""S17: Order block retest continuation, confirmed by OBV and — route
'divergence' only — a recent RSI/price divergence.

This is a continuation strategy, not a reversal call (unlike S1/S10): trade
in the direction of an already-established higher-timeframe trend, entering
where a real displacement candle already broke structure (the order block),
not on an arbitrary indicator threshold. Three evidence families:
  - regime:    4h EMA200 trend + slope, confirmed by 1h ADX (identical to
               S16 — that filter was not implicated in S16's failure)
  - structure: a displacement-confirmed order block, tracked until its
               first retest or expiry ("first mitigation")
  - flow:      OBV must still support the trend direction at the retest
               (route 'base'), PLUS a recent RSI/price divergence pivot
               (route 'divergence', reusing scalp_strategy.divergence_events)

Exactly two frozen central hypotheses; no parameter grid. All bar indices
are close-time availability timestamps. Execution (stop management, target
cap, breakeven+chandelier trailing) is intentionally identical to S16's, so
any performance difference is attributable to entry quality, not risk model.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, divergence_events, resample_closed


@dataclass(frozen=True)
class OrderBlockContinuationConfig:
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

    def __post_init__(self):
        if self.route not in ('base', 'divergence'):
            raise ValueError('Unknown order block continuation route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.target_r <= 1):
            raise ValueError('Invalid order block continuation parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S16's execution() on purpose — see module docstring.
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


def central_variants() -> list[OrderBlockContinuationConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        OrderBlockContinuationConfig('S17_ob_continuation_base', 'base'),
        OrderBlockContinuationConfig('S17_ob_continuation_divergence', 'divergence'),
    ]


def order_block_features(minutes: pd.DataFrame, config: OrderBlockContinuationConfig) -> pd.DataFrame:
    """Causal 15m order-block, OBV and regime features, plus RSI/CVD columns
    required by scalp_strategy.divergence_events."""
    bars = resample_closed(minutes, 15)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, timeperiod=14)
    bars['rsi14'] = talib.RSI(close, timeperiod=14)
    bars['cvd'] = (2 * bars.taker_buy_volume - bars.volume).cumsum()
    bars['obv'] = (np.sign(bars.close.diff().fillna(0.0)) * bars.volume).cumsum()
    bars['obv_ema'] = bars.obv.ewm(span=config.obv_ema_period, adjust=False).mean()

    hourly = resample_closed(minutes, 60)
    hourly['adx'] = talib.ADX(hourly.high.to_numpy(), hourly.low.to_numpy(),
                              hourly.close.to_numpy(), timeperiod=14)
    bars['htf_adx'] = hourly.adx.reindex(bars.index, method='ffill')

    four_hour = resample_closed(minutes, 240)
    four_hour['ema'] = talib.EMA(four_hour.close.to_numpy(), timeperiod=config.ema_period)
    slope = four_hour.ema - four_hour.ema.shift(config.ema_slope_lookback)
    four_hour['trend_up'] = (four_hour.close > four_hour.ema) & (slope > 0)
    four_hour['trend_down'] = (four_hour.close < four_hour.ema) & (slope < 0)
    bars['htf_trend_up'] = four_hour.trend_up.reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)
    bars['htf_trend_down'] = four_hour.trend_down.reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)

    # Order block confirmed 3 bars after formation (idx = j - 3), evaluated
    # entirely from data available at the confirmation bar j.
    open_idx = bars.open.shift(3)
    close_idx = bars.close.shift(3)
    atr_idx = bars.atr.shift(3)
    displacement = bars.close - close_idx
    volume_peak = bars.volume.rolling(3).max()
    volume_baseline = bars.volume.shift(4).rolling(config.volume_avg_lookback).mean()
    volume_ok = volume_peak >= config.volume_mult * volume_baseline

    prior_candle_bearish = close_idx < open_idx  # -> bullish (demand) OB candidate
    prior_candle_bullish = close_idx > open_idx  # -> bearish (supply) OB candidate

    bars['ob_bull_confirmed'] = (
        prior_candle_bearish & volume_ok
        & (displacement >= config.displacement_atr_mult * atr_idx)
    ).fillna(False)
    bars['ob_bull_top'] = open_idx
    bars['ob_bull_bottom'] = close_idx

    bars['ob_bear_confirmed'] = (
        prior_candle_bullish & volume_ok
        & (-displacement >= config.displacement_atr_mult * atr_idx)
    ).fillna(False)
    bars['ob_bear_top'] = close_idx
    bars['ob_bear_bottom'] = open_idx
    return bars


def _recent(event: np.ndarray, window: int = 3) -> np.ndarray:
    return pd.Series(event).rolling(window, min_periods=1).max().astype(bool).to_numpy()


def generate_order_block_signals(bars: pd.DataFrame, config: OrderBlockContinuationConfig,
                                  symbol: str) -> list[dict]:
    """Track order-block zones until their first retest ('first mitigation')
    or expiry. Execution fills at the next 1m open (bars.index is already
    the bar's close time)."""
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
            if config.route == 'divergence' and not recent_div[side][i]:
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
                'setup': f'order_block_continuation_{config.route}',
                'setup_id': (
                    f'OBC:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
