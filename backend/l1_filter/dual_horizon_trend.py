"""S97 causal dual-horizon trend targets with a funding-crowding veto."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class DualHorizonTrendConfig:
    name: str = 'S97_dual_horizon_trend'
    fast_days: int = 28
    slow_days: int = 112
    vol_days: int = 28
    covariance_days: int = 60
    funding_days: int = 28
    max_adverse_mean_funding: float = 0.0001
    max_positions: int = 3
    min_positions: int = 2
    max_asset_weight: float = 0.45
    portfolio_vol_target_annual: float = 0.25

    def validate(self) -> None:
        if not 2 <= self.fast_days < self.slow_days:
            raise ValueError('Trend horizons must be ordered')
        if self.vol_days < 5 or self.covariance_days < self.vol_days:
            raise ValueError('Invalid volatility lookbacks')
        if self.funding_days < 1 or self.max_adverse_mean_funding < 0:
            raise ValueError('Invalid funding veto')
        if not 1 <= self.min_positions <= self.max_positions:
            raise ValueError('Invalid position count')
        if not 0 < self.max_asset_weight <= 1:
            raise ValueError('Invalid asset cap')
        if not 0 < self.portfolio_vol_target_annual <= 1:
            raise ValueError('Invalid volatility target')


def _known_closes(frame: pd.DataFrame, decision: pd.Timestamp) -> pd.Series:
    if not {'close', 'close_time'}.issubset(frame):
        raise ValueError('Daily data requires close and close_time')
    close_time = pd.to_datetime(frame.close_time, utc=True)
    closes = frame.loc[close_time < decision, 'close'].astype(float)
    if closes.index.has_duplicates or not closes.index.is_monotonic_increasing:
        raise ValueError('Daily closes must be sorted and unique')
    return closes


def _capped_inverse_vol(volatility: dict[str, float], cap: float) -> dict[str, float]:
    """Allocate inverse-vol weights, leaving cash if the cap cannot be filled."""
    remaining = set(volatility)
    weights: dict[str, float] = {}
    budget = 1.0
    while remaining and budget > 1e-12:
        inverse = {symbol: 1.0 / volatility[symbol] for symbol in remaining}
        denominator = sum(inverse.values())
        proposed = {symbol: budget * inverse[symbol] / denominator for symbol in remaining}
        capped = [symbol for symbol, weight in proposed.items() if weight > cap]
        if not capped:
            weights.update(proposed)
            break
        for symbol in capped:
            weights[symbol] = cap
            budget -= cap
            remaining.remove(symbol)
    return weights


def weekly_dual_horizon_targets(
    daily: dict[str, pd.DataFrame],
    funding: dict[str, pd.Series],
    start,
    end,
    config: DualHorizonTrendConfig = DualHorizonTrendConfig(),
    symbol_order=(),
) -> list[dict]:
    """Build Monday targets from information strictly known before 00:00 UTC."""
    config.validate()
    start, end = _utc(start), _utc(end)
    if start.weekday() != 0 or start.time() != pd.Timestamp('00:00').time():
        raise ValueError('Research window must start Monday 00:00 UTC')
    symbols = tuple(symbol_order or daily)
    if set(symbols) != set(daily) or set(symbols) != set(funding):
        raise ValueError('Symbol order, daily data and funding must match')
    decisions = pd.date_range(start, end, freq='7D', inclusive='left')
    targets = []

    def flat_target(decision, reason):
        return {
            'timestamp': decision,
            'weights': {},
            'gross_weight': 0.0,
            'estimated_vol_annual': 0.0,
            'vol_scale': 0.0,
            'selected': {},
            'flat_reason': reason,
        }

    for decision in decisions:
        candidates = {}
        returns_by_symbol = {}
        for symbol in symbols:
            closes = _known_closes(daily[symbol], decision)
            if len(closes) < config.slow_days + 1:
                continue
            returns = np.log(closes).diff().dropna()
            if len(returns) < max(config.slow_days, config.covariance_days):
                continue
            fast_return = float(closes.iloc[-1] / closes.iloc[-1 - config.fast_days] - 1)
            slow_return = float(closes.iloc[-1] / closes.iloc[-1 - config.slow_days] - 1)
            if fast_return == 0 or slow_return == 0 or np.sign(fast_return) != np.sign(slow_return):
                continue
            daily_vol = float(returns.iloc[-config.vol_days:].std(ddof=1))
            annual_vol = daily_vol * np.sqrt(365)
            if not np.isfinite(annual_vol) or annual_vol <= 1e-8:
                continue
            side = int(np.sign(fast_return))
            known_funding = funding[symbol].loc[
                (funding[symbol].index < decision)
                & (funding[symbol].index >= decision - pd.Timedelta(days=config.funding_days))
            ]
            if known_funding.empty or not np.isfinite(known_funding.to_numpy(dtype=float)).all():
                continue
            mean_funding = float(known_funding.mean())
            adverse_funding = side * mean_funding
            if adverse_funding > config.max_adverse_mean_funding:
                continue
            fast_strength = abs(fast_return) / (daily_vol * np.sqrt(config.fast_days))
            slow_strength = abs(slow_return) / (daily_vol * np.sqrt(config.slow_days))
            score = float(min(fast_strength, slow_strength))
            if not np.isfinite(score) or score <= 0:
                continue
            candidates[symbol] = {
                'side': side,
                'score': score,
                'fast_return': fast_return,
                'slow_return': slow_return,
                'annual_vol': annual_vol,
                'mean_funding': mean_funding,
                'adverse_funding': adverse_funding,
                'last_completed_daily_open': str(closes.index[-1]),
            }
            returns_by_symbol[symbol] = returns.iloc[-config.covariance_days:]

        ranked = sorted(
            candidates,
            key=lambda symbol: (-candidates[symbol]['score'], symbols.index(symbol)),
        )[:config.max_positions]
        if len(ranked) < config.min_positions:
            targets.append(flat_target(decision, 'INSUFFICIENT_ELIGIBLE_ASSETS'))
            continue
        vol = {symbol: candidates[symbol]['annual_vol'] for symbol in ranked}
        absolute_weights = _capped_inverse_vol(vol, config.max_asset_weight)
        aligned = pd.concat(
            [returns_by_symbol[symbol].rename(symbol) for symbol in ranked],
            axis=1,
            join='inner',
        ).dropna().iloc[-config.covariance_days:]
        if len(aligned) < config.covariance_days:
            targets.append(flat_target(decision, 'INSUFFICIENT_ALIGNED_COVARIANCE'))
            continue
        signed = np.array([
            candidates[symbol]['side'] * absolute_weights[symbol] for symbol in ranked
        ])
        covariance = aligned[ranked].cov().to_numpy(dtype=float) * 365
        variance = float(signed @ covariance @ signed)
        if not np.isfinite(variance) or variance <= 0:
            targets.append(flat_target(decision, 'INVALID_PORTFOLIO_VARIANCE'))
            continue
        estimated_vol = float(np.sqrt(variance))
        scale = min(1.0, config.portfolio_vol_target_annual / estimated_vol)
        weights = {
            symbol: candidates[symbol]['side'] * absolute_weights[symbol] * scale
            for symbol in ranked
        }
        targets.append({
            'timestamp': decision,
            'weights': weights,
            'gross_weight': float(sum(abs(weight) for weight in weights.values())),
            'estimated_vol_annual': estimated_vol,
            'vol_scale': scale,
            'selected': {symbol: candidates[symbol] for symbol in ranked},
        })
    return targets
