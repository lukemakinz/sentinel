"""S96: causal asymmetric alt/BTC residual-shock features and entries."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import resample_closed


@dataclass(frozen=True)
class AsymmetricResidualConfig:
    name: str = 'S96_asymmetric_residual_reversal'
    beta_hours: int = 720
    z_hours: int = 720
    min_beta: float = 0.20
    max_beta: float = 2.00
    entry_z: float = -3.00
    minimum_negative_residual: float = -0.015
    volume_lookback_hours: int = 168
    minimum_volume_multiple: float = 1.50
    maximum_taker_buy_fraction: float = 0.42
    exit_z: float = -0.50
    stop_z: float = -5.00
    max_hold_hours: int = 24
    cooldown_hours: int = 24
    alt_notional_usd: float = 60.0
    maximum_btc_hedge_usd: float = 120.0
    hard_stop_usd: float = 4.0
    drawdown_halt_fraction: float = 0.06


def residual_features(
    alt_minutes: pd.DataFrame,
    btc_minutes: pd.DataFrame,
    config: AsymmetricResidualConfig = AsymmetricResidualConfig(),
) -> pd.DataFrame:
    alt = resample_closed(alt_minutes, 60)
    btc = resample_closed(btc_minutes, 60)
    frame = pd.DataFrame({
        'alt_close': alt.close,
        'btc_close': btc.close,
        'alt_volume': alt.volume,
        'alt_taker_buy_volume': alt.taker_buy_volume,
    }).dropna()
    alt_ret = frame.alt_close.pct_change()
    btc_ret = frame.btc_close.pct_change()
    # Every estimator is shifted: the current completed return is scored only
    # with coefficients and distribution moments known one hour earlier.
    cov = alt_ret.rolling(config.beta_hours).cov(btc_ret).shift(1)
    var = btc_ret.rolling(config.beta_hours).var().shift(1)
    frame['beta'] = cov / var.replace(0.0, np.nan)
    frame['residual'] = alt_ret - frame.beta * btc_ret
    frame['residual_mean'] = frame.residual.rolling(config.z_hours).mean().shift(1)
    frame['residual_std'] = frame.residual.rolling(config.z_hours).std().shift(1)
    frame['z'] = (
        (frame.residual - frame.residual_mean)
        / frame.residual_std.replace(0.0, np.nan)
    )
    frame['volume_median'] = (
        frame.alt_volume.rolling(config.volume_lookback_hours).median().shift(1)
    )
    frame['volume_multiple'] = frame.alt_volume / frame.volume_median.replace(0.0, np.nan)
    frame['taker_buy_fraction'] = (
        frame.alt_taker_buy_volume / frame.alt_volume.replace(0.0, np.nan)
    )
    return frame


def asymmetric_residual_signals(
    features: pd.DataFrame,
    symbol: str,
    config: AsymmetricResidualConfig = AsymmetricResidualConfig(),
) -> list[dict]:
    signals, cooldown_until = [], features.index[0]
    for timestamp, row in features.iterrows():
        if timestamp < cooldown_until:
            continue
        values = (row.beta, row.residual, row.z, row.volume_multiple, row.taker_buy_fraction)
        if not all(np.isfinite(value) for value in values):
            continue
        if not config.min_beta <= row.beta <= config.max_beta:
            continue
        if row.z > config.entry_z or row.residual > config.minimum_negative_residual:
            continue
        if (row.volume_multiple < config.minimum_volume_multiple
                or row.taker_buy_fraction > config.maximum_taker_buy_fraction):
            continue
        signals.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'beta': float(row.beta),
            'z': float(row.z),
            'residual': float(row.residual),
            'score': float(-row.z * row.volume_multiple),
            'setup_id': f'{symbol}:{timestamp.isoformat()}',
            'evidence': {
                'volume_multiple': float(row.volume_multiple),
                'taker_buy_fraction': float(row.taker_buy_fraction),
                'residual_mean': float(row.residual_mean),
                'residual_std': float(row.residual_std),
            },
        })
        cooldown_until = timestamp + pd.Timedelta(hours=config.cooldown_hours)
    return signals


def build_asymmetric_residual(
    alt_minutes: pd.DataFrame,
    btc_minutes: pd.DataFrame,
    symbol: str,
    config: AsymmetricResidualConfig = AsymmetricResidualConfig(),
) -> tuple[pd.DataFrame, list[dict]]:
    features = residual_features(alt_minutes, btc_minutes, config)
    return features, asymmetric_residual_signals(features, symbol, config)
