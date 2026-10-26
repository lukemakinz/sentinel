"""S98 long-only dual momentum with independent asset trend gates."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .dual_horizon_trend import _capped_inverse_vol, _known_closes, _utc


@dataclass(frozen=True)
class IndependentDualMomentumConfig:
    name: str = 'S98_independent_dual_momentum'
    momentum_days: int = 84
    sma_days: int = 200
    vol_days: int = 42
    covariance_days: int = 60
    funding_days: int = 28
    max_mean_funding: float = 0.0001
    max_positions: int = 3
    max_asset_weight: float = 0.45
    portfolio_vol_target_annual: float = 0.20

    def validate(self) -> None:
        if not 2 <= self.momentum_days < self.sma_days:
            raise ValueError('Momentum must be shorter than the SMA gate')
        if self.vol_days < 5 or self.covariance_days < self.vol_days:
            raise ValueError('Invalid volatility lookbacks')
        if self.funding_days < 1 or self.max_mean_funding < 0:
            raise ValueError('Invalid funding rule')
        if self.max_positions < 1 or not 0 < self.max_asset_weight <= 1:
            raise ValueError('Invalid concentration controls')
        if not 0 < self.portfolio_vol_target_annual <= 1:
            raise ValueError('Invalid volatility target')


def weekly_independent_momentum_targets(
    daily: dict[str, pd.DataFrame],
    funding: dict[str, pd.Series],
    start,
    end,
    config: IndependentDualMomentumConfig = IndependentDualMomentumConfig(),
    symbol_order=(),
) -> list[dict]:
    """Return an explicit target, including cash-only, at every weekly decision."""
    config.validate()
    start, end = _utc(start), _utc(end)
    symbols = tuple(symbol_order or daily)
    if set(symbols) != set(daily) or set(symbols) != set(funding):
        raise ValueError('Symbol order, daily data and funding must match')
    decisions = pd.date_range(start, end, freq='7D', inclusive='left')
    targets = []

    for decision in decisions:
        candidates, returns_by_symbol = {}, {}
        for symbol in symbols:
            closes = _known_closes(daily[symbol], decision)
            needed = max(config.sma_days, config.momentum_days, config.covariance_days) + 1
            if len(closes) < needed:
                continue
            sma = float(closes.iloc[-config.sma_days:].mean())
            momentum = float(closes.iloc[-1] / closes.iloc[-1 - config.momentum_days] - 1)
            if float(closes.iloc[-1]) <= sma or momentum <= 0:
                continue
            returns = np.log(closes).diff().dropna()
            daily_vol = float(returns.iloc[-config.vol_days:].std(ddof=1))
            annual_vol = daily_vol * np.sqrt(365)
            if not np.isfinite(annual_vol) or annual_vol <= 1e-8:
                continue
            known_funding = funding[symbol].loc[
                (funding[symbol].index < decision)
                & (funding[symbol].index >= decision - pd.Timedelta(days=config.funding_days))
            ]
            if known_funding.empty or not np.isfinite(known_funding.to_numpy(dtype=float)).all():
                continue
            mean_funding = float(known_funding.mean())
            if mean_funding > config.max_mean_funding:
                continue
            score = momentum / (daily_vol * np.sqrt(config.momentum_days))
            if not np.isfinite(score) or score <= 0:
                continue
            candidates[symbol] = {
                'score': float(score),
                'momentum': momentum,
                'last_close': float(closes.iloc[-1]),
                'sma': sma,
                'annual_vol': annual_vol,
                'mean_funding': mean_funding,
                'last_completed_daily_open': str(closes.index[-1]),
            }
            returns_by_symbol[symbol] = returns.iloc[-config.covariance_days:]

        ranked = sorted(
            candidates,
            key=lambda symbol: (-candidates[symbol]['score'], symbols.index(symbol)),
        )[:config.max_positions]
        if not ranked:
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'estimated_vol_annual': 0.0, 'vol_scale': 0.0,
                'selected': {}, 'flat_reason': 'NO_ELIGIBLE_ASSET',
            })
            continue
        volatility = {symbol: candidates[symbol]['annual_vol'] for symbol in ranked}
        weights = _capped_inverse_vol(volatility, config.max_asset_weight)
        aligned = pd.concat(
            [returns_by_symbol[symbol].rename(symbol) for symbol in ranked],
            axis=1, join='inner',
        ).dropna().iloc[-config.covariance_days:]
        if len(aligned) < config.covariance_days:
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'estimated_vol_annual': 0.0, 'vol_scale': 0.0,
                'selected': {}, 'flat_reason': 'INSUFFICIENT_ALIGNED_COVARIANCE',
            })
            continue
        vector = np.array([weights[symbol] for symbol in ranked])
        covariance = aligned[ranked].cov().to_numpy(dtype=float) * 365
        variance = float(vector @ covariance @ vector)
        if not np.isfinite(variance) or variance <= 0:
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'estimated_vol_annual': 0.0, 'vol_scale': 0.0,
                'selected': {}, 'flat_reason': 'INVALID_PORTFOLIO_VARIANCE',
            })
            continue
        estimated_vol = float(np.sqrt(variance))
        scale = min(1.0, config.portfolio_vol_target_annual / estimated_vol)
        scaled = {symbol: weights[symbol] * scale for symbol in ranked}
        targets.append({
            'timestamp': decision,
            'weights': scaled,
            'gross_weight': float(sum(scaled.values())),
            'estimated_vol_annual': estimated_vol,
            'vol_scale': scale,
            'selected': {symbol: candidates[symbol] for symbol in ranked},
        })
    return targets
