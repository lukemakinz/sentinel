"""S16: RSI(2)/Connors RSI pullback inside an established higher-timeframe
trend, gated by a 1h ADX regime filter.

Three orthogonal evidence families, not several correlated votes on the same
thing:
  - regime:  4h EMA200 trend + slope, confirmed by 1h ADX >= threshold
  - trigger: RSI(2) and Connors RSI both reach a frozen extreme on the same
             closed 15m bar (a momentary pullback, not a reversal call)
  - structure (route == 'confluence' only): the pullback bar must sweep a
             real recent liquidity level (rolling extreme of the last N
             *prior* closed bars) and reclaim it intrabar — the SMC
             "stop hunt then reversal" concept, causally approximated
             without any live order-book/DB dependency.

Exactly two frozen central hypotheses (base vs confluence); no parameter
grid. All bar indices are close-time availability timestamps.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class RSICRSIPullbackConfig:
    name: str
    route: str  # 'base' or 'confluence'
    rsi2_threshold: float = 10.0
    crsi_threshold: float = 15.0
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    sweep_lookback: int = 20
    stop_lookback: int = 5
    stop_buffer_atr_mult: float = 0.15
    target_r: float = 5.0

    def __post_init__(self):
        if self.route not in ('base', 'confluence'):
            raise ValueError('Unknown RSI/CRSI pullback route')
        if (not 0 < self.rsi2_threshold < 50 or not 0 < self.crsi_threshold < 50
                or self.ema_period < 2 or self.ema_slope_lookback < 1
                or self.adx_threshold <= 0 or self.sweep_lookback < 2
                or self.stop_lookback < 1 or self.stop_buffer_atr_mult < 0
                or self.target_r <= 1):
            raise ValueError('Invalid RSI/CRSI pullback parameters')

    def execution(self) -> ScalpConfig:
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


def central_variants() -> list[RSICRSIPullbackConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        RSICRSIPullbackConfig('S16_rsi_crsi_base', 'base'),
        RSICRSIPullbackConfig('S16_rsi_crsi_confluence', 'confluence'),
    ]


def _connors_rsi(close: pd.Series, rsi_period: int = 3, streak_period: int = 2,
                  rank_period: int = 100) -> pd.Series:
    """Causal Connors RSI: average of short RSI, streak RSI and the percentile
    rank of the latest 1-bar return against the previous `rank_period`
    returns. Every component only ever looks backward from its own index."""
    values = close.to_numpy(dtype=float)
    price_rsi = talib.RSI(values, timeperiod=rsi_period)

    diffs = np.diff(values, prepend=values[0])
    streak = np.zeros(len(values))
    for i in range(1, len(values)):
        if diffs[i] > 0:
            streak[i] = streak[i - 1] + 1 if streak[i - 1] > 0 else 1
        elif diffs[i] < 0:
            streak[i] = streak[i - 1] - 1 if streak[i - 1] < 0 else -1
        else:
            streak[i] = 0
    streak_rsi = talib.RSI(streak, timeperiod=streak_period)

    returns = close.pct_change()
    rank = returns.rolling(rank_period + 1).apply(
        lambda window: float(np.sum(window[:-1] < window[-1])) / rank_period * 100.0,
        raw=True,
    )
    return (pd.Series(price_rsi, index=close.index)
            + pd.Series(streak_rsi, index=close.index) + rank) / 3.0


def rsi_crsi_features(minutes: pd.DataFrame, config: RSICRSIPullbackConfig) -> pd.DataFrame:
    """Causal 15m trigger features plus frozen, fully-closed 1h/4h regime
    context (resample_closed already drops any not-yet-complete bin, so
    ffill-reindexing onto 15m bars never leaks an in-progress higher-TF bar)."""
    bars = resample_closed(minutes, 15)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, timeperiod=14)
    bars['rsi2'] = talib.RSI(close, timeperiod=2)
    bars['crsi'] = _connors_rsi(bars.close)

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

    # Recent-liquidity proxy: rolling extreme of the PRIOR `sweep_lookback`
    # closed bars (excludes the trigger bar itself, so it cannot sweep a
    # level defined by its own wick).
    bars['sweep_level_long'] = bars.low.shift(1).rolling(config.sweep_lookback).min()
    bars['sweep_level_short'] = bars.high.shift(1).rolling(config.sweep_lookback).max()

    bars['stop_long'] = bars.low.rolling(config.stop_lookback).min() - config.stop_buffer_atr_mult * bars.atr
    bars['stop_short'] = bars.high.rolling(config.stop_lookback).max() + config.stop_buffer_atr_mult * bars.atr
    return bars


def _recent(event: pd.Series, window: int = 3) -> pd.Series:
    """True if `event` fired at this bar or either of the previous two —
    the climax bar and the reclaim/reaction bar are rarely identical."""
    return event.rolling(window, min_periods=1).max().astype(bool)


def generate_rsi_crsi_signals(bars: pd.DataFrame, config: RSICRSIPullbackConfig,
                               symbol: str) -> list[dict]:
    """Return auditable candidates at closed-15m-bar timestamps; execution
    layer fills at the next 1m open (bars.index is already the bar's close
    time, i.e. the first following minute).

    The RSI(2)/CRSI extreme and the sweep-then-reclaim (confluence route) are
    evaluated as events that may have fired on this bar or either of the
    previous two, not necessarily all on the identical bar: a bar with a
    deeply oversold RSI(2) close is, by construction, usually a down bar, so
    requiring the SAME bar to also be a bullish reclaim candle would make the
    two conditions nearly mutually exclusive. Reclaim itself is still
    required on the current bar — that is what makes it a reclaim.
    """
    records = []
    for side in (1, -1):
        if side == 1:
            trend_ok = bars.htf_trend_up
            momentum_extreme = (bars.rsi2 <= config.rsi2_threshold) & (bars.crsi <= config.crsi_threshold)
            stop = bars.stop_long
            sweep_level = bars.sweep_level_long
            swept = bars.low < sweep_level
            reclaimed = (bars.close > sweep_level) & (bars.close > bars.open)
        else:
            trend_ok = bars.htf_trend_down
            momentum_extreme = (bars.rsi2 >= 100 - config.rsi2_threshold) & (bars.crsi >= 100 - config.crsi_threshold)
            stop = bars.stop_short
            sweep_level = bars.sweep_level_short
            swept = bars.high > sweep_level
            reclaimed = (bars.close < sweep_level) & (bars.close < bars.open)

        adx_ok = bars.htf_adx >= config.adx_threshold
        required = (trend_ok & adx_ok & _recent(momentum_extreme)
                    & bars.atr.notna() & stop.notna() & sweep_level.notna())
        if config.route == 'confluence':
            required = required & _recent(swept) & reclaimed

        risk = side * (bars.close - stop)
        selected = required & (risk > 0)
        for i in np.flatnonzero(selected.to_numpy()):
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': bars.index[i],
                'side': side,
                'reference': float(bars.close.iloc[i]),
                'stop': float(stop.iloc[i]),
                'min_stop_atr': 0.5,
                'max_stop_atr': 2.0,
                'atr': float(bars.atr.iloc[i]),
                'score': 6,
                'setup': f'rsi_crsi_pullback_{config.route}',
                'setup_id': (
                    f'RCP:v1:{config.route}:{symbol}:{direction}:'
                    f'{bars.index[i].isoformat()}'
                ),
            })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
