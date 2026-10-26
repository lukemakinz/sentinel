"""S93 delta-neutral spot/perpetual basis-compression signals."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import resample_closed


@dataclass(frozen=True)
class BasisCompressionConfig:
    name: str = 'S93_basis_compression'
    lookback_hours: int = 2160
    minimum_history_fraction: float = 0.95
    minimum_deviation: float = 0.0132
    quantile: float = 0.95
    mad_floor: float = 0.0001
    funding_lookback_hours: int = 72
    maximum_last_funding_age_hours: int = 12
    cooldown_hours: int = 24
    notional_cap_each_leg_usd: float = 60.0
    futures_collateral_usd: float = 100.0
    compression_fraction: float = 0.75
    extension_stop: float = 0.0075
    maximum_hold_hours: int = 168
    minimum_futures_equity_usd: float = 75.0
    maximum_mark_leverage: float = 1.25


def basis_features(
    spot_minutes: pd.DataFrame,
    perp_minutes: pd.DataFrame,
    config: BasisCompressionConfig = BasisCompressionConfig(),
) -> pd.DataFrame:
    spot = resample_closed(spot_minutes, 60)
    perp = resample_closed(perp_minutes, 60)
    frame = pd.DataFrame({'spot_close': spot.close, 'perp_close': perp.close}).dropna()
    frame['basis'] = frame.perp_close / frame.spot_close - 1.0
    prior = frame.basis.shift(1)
    minimum = int(config.lookback_hours * config.minimum_history_fraction)
    frame['median'] = prior.rolling(config.lookback_hours, min_periods=minimum).median()
    frame['q95'] = prior.rolling(config.lookback_hours, min_periods=minimum).quantile(config.quantile)
    frame['mad'] = prior.rolling(config.lookback_hours, min_periods=minimum).apply(
        lambda values: np.median(np.abs(values - np.median(values))), raw=True)
    frame['score'] = (
        (frame.basis - frame['median']) / frame['mad'].clip(lower=config.mad_floor)
    )
    return frame


def basis_compression_signals(
    features: pd.DataFrame,
    funding: pd.Series,
    symbol: str,
    config: BasisCompressionConfig = BasisCompressionConfig(),
) -> list[dict]:
    funding = funding.sort_index()
    signals, cooldown_until = [], features.index[0]
    for timestamp, row in features.iterrows():
        if timestamp < cooldown_until:
            continue
        required = (row.basis, row['median'], row.q95, row.mad, row.score)
        if not all(np.isfinite(value) for value in required):
            continue
        # Strictly earlier settlements only: a settlement stamped at the entry
        # minute is not treated as known before that minute's open.
        realized = funding.loc[
            (funding.index < timestamp)
            & (funding.index >= timestamp - pd.Timedelta(hours=config.funding_lookback_hours))]
        if realized.empty or float(realized.sum()) <= 0 or float(realized.iloc[-1]) <= 0:
            continue
        if timestamp - realized.index[-1] > pd.Timedelta(hours=config.maximum_last_funding_age_hours):
            continue
        if row.basis <= row.q95 or row.basis - row['median'] < config.minimum_deviation:
            continue
        signals.append({
            'timestamp': timestamp, 'symbol': symbol,
            'basis': float(row.basis), 'median': float(row['median']),
            'mad': float(row.mad), 'score': float(row.score),
            'setup_id': f'{symbol}:{timestamp.isoformat()}',
            'funding_72h': float(realized.sum()),
            'last_funding': float(realized.iloc[-1]),
        })
        cooldown_until = timestamp + pd.Timedelta(hours=config.cooldown_hours)
    return signals
