"""Causal, research-only 4h time-series momentum signals.

Input candle indices are open times.  Resampled indices are availability
times: a bar stamped ``T`` contains only source candles whose close is no
later than ``T``.  An execution engine may therefore first trade at ``T``.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib


@dataclass(frozen=True)
class TSM4HConfig:
    name: str = 'S15_tsm_4h_donchian'
    entry_channel: int = 20
    exit_channel: int = 10
    ema_days: int = 50
    ema_slope_days: int = 3
    atr_period: int = 14
    stop_atr: float = 2.0

    def __post_init__(self):
        if (self.entry_channel < 2 or self.exit_channel < 2
                or self.exit_channel >= self.entry_channel
                or self.ema_days < 2 or self.ema_slope_days < 1
                or self.atr_period < 2 or self.stop_atr <= 0):
            raise ValueError('Invalid TSM-4H configuration')


def _resample_complete(frame: pd.DataFrame, rule: str, expected: int) -> pd.DataFrame:
    bars = frame.resample(rule, label='right', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum',
    })
    if 'synthetic' in frame:
        # A carried outage price is useful for a continuous portfolio clock,
        # but it must never turn an incomplete signal bar into a real one.
        counts = (~frame.synthetic.astype(bool)).resample(
            rule, label='right', closed='left').sum()
    else:
        counts = frame.close.resample(rule, label='right', closed='left').count()
    return bars.loc[counts == expected].copy()


def build_tsm_features(
    five_minutes: pd.DataFrame,
    config: TSM4HConfig = TSM4HConfig(),
) -> dict[str, pd.DataFrame]:
    """Return complete 4h and daily features without forward filling future data."""
    four_hour = _resample_complete(five_minutes, '4h', 48)
    daily = _resample_complete(five_minutes, '1D', 288)

    high = four_hour.high.to_numpy(dtype=float)
    low = four_hour.low.to_numpy(dtype=float)
    close = four_hour.close.to_numpy(dtype=float)
    four_hour['atr'] = talib.ATR(high, low, close, timeperiod=config.atr_period)
    four_hour['entry_high'] = four_hour.high.shift(1).rolling(
        config.entry_channel, min_periods=config.entry_channel).max()
    four_hour['entry_low'] = four_hour.low.shift(1).rolling(
        config.entry_channel, min_periods=config.entry_channel).min()
    four_hour['exit_high'] = four_hour.high.shift(1).rolling(
        config.exit_channel, min_periods=config.exit_channel).max()
    four_hour['exit_low'] = four_hour.low.shift(1).rolling(
        config.exit_channel, min_periods=config.exit_channel).min()

    daily_close = daily.close.to_numpy(dtype=float)
    daily['ema50'] = talib.EMA(daily_close, timeperiod=config.ema_days)
    slope = daily.ema50 - daily.ema50.shift(config.ema_slope_days)
    daily['regime'] = np.where(
        (daily.close > daily.ema50) & (slope > 0), 1,
        np.where((daily.close < daily.ema50) & (slope < 0), -1, 0),
    ).astype(int)
    return {'four_hour': four_hour, 'daily': daily}


def generate_tsm_events(
    alt: dict[str, pd.DataFrame],
    btc_daily: pd.DataFrame,
    symbol: str,
    config: TSM4HConfig = TSM4HConfig(),
) -> tuple[list[dict], list[dict]]:
    """Generate entries and common Donchian exits at closed 4h timestamps."""
    bars = alt['four_hour'].copy()
    # One UTC day is the normal maximum age of a completed daily regime.
    # Longer staleness can occur during an archive/exchange outage and must
    # veto a signal instead of silently inheriting an old trend state.
    bars['alt_regime'] = alt['daily'].regime.reindex(
        bars.index, method='ffill', tolerance=pd.Timedelta(days=1))
    bars['btc_regime'] = btc_daily.regime.reindex(
        bars.index, method='ffill', tolerance=pd.Timedelta(days=1))

    entries: list[dict] = []
    exits: list[dict] = []
    previous_entry_high = bars.entry_high.shift(1)
    previous_entry_low = bars.entry_low.shift(1)
    previous_exit_high = bars.exit_high.shift(1)
    previous_exit_low = bars.exit_low.shift(1)

    for row, prior_close, prior_high, prior_low, prior_exit_high, prior_exit_low in zip(
        bars.itertuples(), bars.close.shift(1), previous_entry_high, previous_entry_low,
        previous_exit_high, previous_exit_low,
    ):
        if not np.isfinite(row.atr) or row.atr <= 0:
            continue

        # An exit event names the side of an already-open position it can close.
        if (np.isfinite(row.exit_low) and np.isfinite(prior_close)
                and np.isfinite(prior_exit_low)
                and row.close < row.exit_low
                and prior_close >= prior_exit_low):
            exits.append({'timestamp': row.Index, 'position_side': 1,
                          'reason': 'OPPOSITE_DONCHIAN_10'})
        if (np.isfinite(row.exit_high) and np.isfinite(prior_close)
                and np.isfinite(prior_exit_high)
                and row.close > row.exit_high
                and prior_close <= prior_exit_high):
            exits.append({'timestamp': row.Index, 'position_side': -1,
                          'reason': 'OPPOSITE_DONCHIAN_10'})

        for side, boundary, prior_boundary in (
            (1, row.entry_high, prior_high), (-1, row.entry_low, prior_low),
        ):
            if (not np.isfinite(boundary) or not np.isfinite(prior_close)
                    or not np.isfinite(prior_boundary)):
                continue
            crossed = (side * (row.close - boundary) > 0
                       and side * (prior_close - prior_boundary) <= 0)
            if not crossed or row.alt_regime != side or row.btc_regime != side:
                continue
            breakout_atr = side * (row.close - boundary) / row.atr
            entries.append({
                'timestamp': row.Index,
                'side': side,
                'reference': float(row.close),
                'stop': float(row.close - side * config.stop_atr * row.atr),
                'atr': float(row.atr),
                'score': float(breakout_atr),
                'setup': 'tsm_4h_donchian_dual_daily_regime',
                'setup_id': f'{symbol}:{row.Index.isoformat()}:'
                            f'{"long" if side == 1 else "short"}',
                'evidence': {
                    'symbol': symbol,
                    'donchian_boundary': float(boundary),
                    'breakout_atr': float(breakout_atr),
                    'alt_daily_regime': int(row.alt_regime),
                    'btc_daily_regime': int(row.btc_regime),
                },
            })

    entries.sort(key=lambda item: item['timestamp'])
    exits.sort(key=lambda item: item['timestamp'])
    return entries, exits
