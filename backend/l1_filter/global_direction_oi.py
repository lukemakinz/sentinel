"""S100: independent global direction model plus OI-confirmed execution.

The first layer classifies the market as UP, DOWN or SIDEWAYS without using
open interest.  The second layer may open longs only in UP and shorts only in
DOWN.  Open interest confirms participation; it never supplies direction on
its own.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _known_rows(frame: pd.DataFrame, decision) -> pd.DataFrame:
    """Daily bars whose close was observable strictly before ``decision``."""
    decision = _utc(decision)
    if 'close_time' not in frame:
        raise ValueError('Daily frame requires close_time for causal selection')
    close_time = pd.to_datetime(frame.close_time, utc=True)
    return frame.loc[close_time < decision]


@dataclass(frozen=True)
class GlobalDirectionConfig:
    btc_symbol: str = 'BTCUSDT'
    slow_days: int = 200
    slow_slope_days: int = 20
    momentum_days: int = 84
    breadth_sma_days: int = 100
    breadth_up: float = 2 / 3
    breadth_down: float = 1 / 3
    cross_momentum_days: int = 28
    directional_score: int = 3
    confirmation_days: int = 2

    def validate(self) -> None:
        if self.slow_days < 50 or not 1 <= self.slow_slope_days < self.slow_days:
            raise ValueError('Invalid slow-trend definition')
        if min(self.momentum_days, self.breadth_sma_days,
               self.cross_momentum_days) < 2:
            raise ValueError('Invalid lookback')
        if not 0 < self.breadth_down < self.breadth_up < 1:
            raise ValueError('Invalid breadth thresholds')
        if not 1 <= self.directional_score <= 4 or self.confirmation_days < 1:
            raise ValueError('Invalid regime threshold')


@dataclass(frozen=True)
class OIExecutionConfig:
    oi_fast_days: int = 7
    oi_slow_days: int = 28
    oi_velocity_days: int = 3
    minimum_oi_oscillator_pct: float = 0.05
    oi_collapse_exit_pct: float = -0.25
    ema_pullback_days: int = 20
    local_trend_days: int = 50
    pullback_window_days: int = 3
    pullback_tolerance: float = 0.005
    momentum_days: int = 28
    volatility_days: int = 28
    covariance_days: int = 60
    funding_days: int = 7
    max_long_mean_funding: float = 0.0002
    min_short_mean_funding: float = -0.0002
    rebalance_days: int = 3
    max_positions: int = 2
    max_long_hold_days: int = 21
    max_short_hold_days: int = 12
    max_asset_weight: float = 0.40
    gross_cap: float = 0.75
    annual_volatility_target: float = 0.12
    short_risk_multiplier: float = 0.75

    def validate(self) -> None:
        if not 2 <= self.oi_fast_days < self.oi_slow_days:
            raise ValueError('OI fast span must be shorter than slow span')
        if self.oi_velocity_days < 1 or self.pullback_window_days < 1:
            raise ValueError('Invalid confirmation window')
        if not 2 <= self.ema_pullback_days < self.local_trend_days:
            raise ValueError('Invalid local trend definition')
        if min(self.momentum_days, self.volatility_days,
               self.covariance_days, self.funding_days) < 2:
            raise ValueError('Invalid risk lookback')
        if self.rebalance_days < 1 or self.max_positions < 1:
            raise ValueError('Invalid decision cadence')
        if min(self.max_long_hold_days, self.max_short_hold_days) < 1:
            raise ValueError('Invalid maximum hold')
        if not 0 < self.max_asset_weight <= self.gross_cap <= 1:
            raise ValueError('Invalid exposure caps')
        if not 0 < self.annual_volatility_target <= 1:
            raise ValueError('Invalid volatility target')
        if not 0 < self.short_risk_multiplier <= 1:
            raise ValueError('Invalid short risk multiplier')


def global_direction_series(
    daily: dict[str, pd.DataFrame],
    start,
    end,
    config: GlobalDirectionConfig = GlobalDirectionConfig(),
) -> pd.DataFrame:
    """Causal daily UP/DOWN/SIDEWAYS classification available at each UTC open."""
    config.validate()
    if config.btc_symbol not in daily or len(daily) < 3:
        raise ValueError('Global model requires BTC and at least two breadth assets')
    decisions = pd.date_range(_utc(start), _utc(end), freq='1D', inclusive='left')
    records = []
    minimum = max(
        config.slow_days + config.slow_slope_days,
        config.momentum_days + 1,
        config.breadth_sma_days,
        config.cross_momentum_days + 1,
    )
    for decision in decisions:
        histories = {
            symbol: _known_rows(frame, decision).close.astype(float)
            for symbol, frame in daily.items()
        }
        btc = histories[config.btc_symbol]
        if len(btc) < minimum:
            records.append({
                'timestamp': decision, 'raw_regime': 'SIDEWAYS', 'score': 0,
                'btc_trend': 0, 'btc_momentum': 0, 'breadth': np.nan,
                'cross_momentum': np.nan,
            })
            continue
        sma_now = float(btc.iloc[-config.slow_days:].mean())
        sma_then = float(
            btc.iloc[-config.slow_days - config.slow_slope_days:
                     -config.slow_slope_days].mean())
        btc_trend = (
            1 if btc.iloc[-1] > sma_now and sma_now > sma_then
            else -1 if btc.iloc[-1] < sma_now and sma_now < sma_then
            else 0
        )
        btc_return = float(btc.iloc[-1] / btc.iloc[-1 - config.momentum_days] - 1)
        btc_momentum = 1 if btc_return > 0 else -1 if btc_return < 0 else 0

        above, cross_returns = [], []
        for closes in histories.values():
            if len(closes) >= config.breadth_sma_days:
                above.append(
                    float(closes.iloc[-1])
                    > float(closes.iloc[-config.breadth_sma_days:].mean()))
            if len(closes) >= config.cross_momentum_days + 1:
                cross_returns.append(float(
                    closes.iloc[-1] / closes.iloc[-1 - config.cross_momentum_days] - 1))
        breadth = float(np.mean(above)) if above else np.nan
        breadth_vote = (
            1 if breadth >= config.breadth_up
            else -1 if breadth <= config.breadth_down
            else 0
        )
        cross_momentum = float(np.median(cross_returns)) if cross_returns else np.nan
        cross_vote = (
            1 if cross_momentum > 0 else -1 if cross_momentum < 0 else 0)
        score = btc_trend + btc_momentum + breadth_vote + cross_vote
        raw = (
            'UP' if score >= config.directional_score
            else 'DOWN' if score <= -config.directional_score
            else 'SIDEWAYS'
        )
        records.append({
            'timestamp': decision, 'raw_regime': raw, 'score': int(score),
            'btc_trend': btc_trend, 'btc_momentum': btc_momentum,
            'breadth': breadth, 'cross_momentum': cross_momentum,
        })

    result = pd.DataFrame(records).set_index('timestamp')
    raw = result.raw_regime.to_numpy(dtype=object)
    confirmed = np.full(len(result), 'SIDEWAYS', dtype=object)
    width = config.confirmation_days
    for i in range(width - 1, len(result)):
        window = raw[i - width + 1:i + 1]
        if len(set(window)) == 1:
            confirmed[i] = window[-1]
    result['regime'] = confirmed
    return result


def oi_oscillator(open_interest: pd.Series, config: OIExecutionConfig) -> pd.DataFrame:
    """Percent fast/slow OI spread and its causal change."""
    config.validate()
    values = open_interest.astype(float).sort_index()
    if values.index.has_duplicates or (values <= 0).any() or not np.isfinite(values).all():
        raise ValueError('OI series must be positive, finite, sorted and unique')
    fast = values.ewm(span=config.oi_fast_days, adjust=False).mean()
    slow = values.ewm(span=config.oi_slow_days, adjust=False).mean()
    oscillator = 100 * (fast / slow - 1)
    return pd.DataFrame({
        'oi_oscillator_pct': oscillator,
        'oi_velocity_pct': oscillator.diff(config.oi_velocity_days),
    })


def _asset_snapshot(
    frame: pd.DataFrame,
    oi: pd.Series,
    funding: pd.Series,
    decision,
    side: int,
    config: OIExecutionConfig,
) -> dict | None:
    rows = _known_rows(frame, decision)
    needed = max(config.local_trend_days, config.momentum_days + 1,
                 config.volatility_days + 1, config.covariance_days + 1)
    if len(rows) < needed:
        return None
    closes = rows.close.astype(float)
    ema_pullback = closes.ewm(span=config.ema_pullback_days, adjust=False).mean()
    ema_trend = closes.ewm(span=config.local_trend_days, adjust=False).mean()
    returns = np.log(closes).diff().dropna()
    annual_vol = float(returns.iloc[-config.volatility_days:].std(ddof=1) * np.sqrt(365))
    if not np.isfinite(annual_vol) or annual_vol <= 1e-8:
        return None
    momentum = float(closes.iloc[-1] / closes.iloc[-1 - config.momentum_days] - 1)
    local_trend = side * (float(closes.iloc[-1]) - float(ema_trend.iloc[-1])) > 0
    directional_momentum = side * momentum > 0

    recent = rows.iloc[-config.pullback_window_days:]
    recent_ema = ema_pullback.reindex(recent.index)
    if side == 1:
        touched = bool((recent.low <= recent_ema * (1 + config.pullback_tolerance)).any())
        reclaimed = closes.iloc[-1] > ema_pullback.iloc[-1] and closes.iloc[-1] > closes.iloc[-2]
    else:
        touched = bool((recent.high >= recent_ema * (1 - config.pullback_tolerance)).any())
        reclaimed = closes.iloc[-1] < ema_pullback.iloc[-1] and closes.iloc[-1] < closes.iloc[-2]

    decision = _utc(decision)
    oi_history = oi.loc[oi.index < decision]
    if len(oi_history) < config.oi_slow_days + config.oi_velocity_days:
        return None
    oi_features = oi_oscillator(oi_history, config).iloc[-1]
    known_funding = funding.loc[
        (funding.index < decision)
        & (funding.index >= decision - pd.Timedelta(days=config.funding_days))
    ]
    if known_funding.empty or not np.isfinite(known_funding.to_numpy(dtype=float)).all():
        return None
    mean_funding = float(known_funding.mean())
    funding_ok = (
        mean_funding <= config.max_long_mean_funding if side == 1
        else mean_funding >= config.min_short_mean_funding)
    entry_ok = bool(
        local_trend and directional_momentum and touched and reclaimed
        and oi_features.oi_oscillator_pct >= config.minimum_oi_oscillator_pct
        and oi_features.oi_velocity_pct > 0 and funding_ok)
    score = (
        side * momentum / (annual_vol / np.sqrt(365) * np.sqrt(config.momentum_days))
        + min(float(oi_features.oi_oscillator_pct), 5.0) / 5.0
    )
    return {
        'entry_ok': entry_ok,
        'local_trend_ok': bool(local_trend),
        'oi_not_collapsing': bool(
            oi_features.oi_oscillator_pct >= config.oi_collapse_exit_pct),
        'score': float(score), 'annual_vol': annual_vol,
        'momentum': momentum,
        'oi_oscillator_pct': float(oi_features.oi_oscillator_pct),
        'oi_velocity_pct': float(oi_features.oi_velocity_pct),
        'mean_funding': mean_funding,
        'returns': returns.iloc[-config.covariance_days:],
        'last_completed_daily_open': str(rows.index[-1]),
    }


def regime_oi_targets(
    daily: dict[str, pd.DataFrame],
    open_interest: dict[str, pd.Series],
    funding: dict[str, pd.Series],
    regimes: pd.DataFrame,
    start,
    end,
    config: OIExecutionConfig = OIExecutionConfig(),
    symbol_order=(),
) -> list[dict]:
    """Stateful three-day swing targets with explicit cash decisions."""
    config.validate()
    symbols = tuple(symbol_order or open_interest)
    if set(symbols) != set(open_interest) or not set(symbols).issubset(daily):
        raise ValueError('Trade universe and OI series must match')
    if not set(symbols).issubset(funding):
        raise ValueError('Funding missing for trade universe')
    decisions = pd.date_range(
        _utc(start), _utc(end), freq=f'{config.rebalance_days}D', inclusive='left')
    active: dict[str, dict] = {}
    targets = []

    for decision in decisions:
        if decision not in regimes.index:
            raise ValueError(f'Missing global regime at {decision}')
        regime = str(regimes.loc[decision, 'regime'])
        side = 1 if regime == 'UP' else -1 if regime == 'DOWN' else 0
        if side == 0:
            active = {}
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'selected': {}, 'regime': regime, 'flat_reason': 'SIDEWAYS',
            })
            continue

        snapshots = {
            symbol: _asset_snapshot(
                daily[symbol], open_interest[symbol], funding[symbol],
                decision, side, config)
            for symbol in symbols
        }
        max_hold = (
            config.max_long_hold_days if side == 1 else config.max_short_hold_days)
        kept = {}
        for symbol, position in active.items():
            snapshot = snapshots.get(symbol)
            age = (decision - position['opened_at']).days
            if (position['side'] == side and snapshot is not None
                    and snapshot['local_trend_ok']
                    and snapshot['oi_not_collapsing'] and age <= max_hold):
                kept[symbol] = position
        active = kept

        entrants = sorted(
            (symbol for symbol in symbols
             if symbol not in active and snapshots[symbol] is not None
             and snapshots[symbol]['entry_ok']),
            key=lambda symbol: (-snapshots[symbol]['score'], symbols.index(symbol)),
        )
        for symbol in entrants:
            if len(active) >= config.max_positions:
                break
            active[symbol] = {'side': side, 'opened_at': decision}

        selected_symbols = tuple(active)
        if not selected_symbols:
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'selected': {}, 'regime': regime, 'flat_reason': 'NO_CONFIRMED_PULLBACK',
            })
            continue

        inverse = {
            symbol: 1 / snapshots[symbol]['annual_vol'] for symbol in selected_symbols}
        total_inverse = sum(inverse.values())
        base = {
            symbol: min(config.max_asset_weight, inverse[symbol] / total_inverse)
            for symbol in selected_symbols}
        total_base = sum(base.values())
        if total_base > 1:
            base = {symbol: weight / total_base for symbol, weight in base.items()}
        aligned = pd.concat(
            [snapshots[symbol]['returns'].rename(symbol) for symbol in selected_symbols],
            axis=1, join='inner').dropna().iloc[-config.covariance_days:]
        vector = np.array([base[symbol] * side for symbol in selected_symbols])
        covariance = aligned[list(selected_symbols)].cov().to_numpy(dtype=float) * 365
        variance = float(vector @ covariance @ vector)
        estimated_vol = float(np.sqrt(variance)) if variance > 0 else np.nan
        if not np.isfinite(estimated_vol) or estimated_vol <= 0:
            active = {}
            targets.append({
                'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                'selected': {}, 'regime': regime, 'flat_reason': 'INVALID_COVARIANCE',
            })
            continue
        risk_multiplier = 1.0 if side == 1 else config.short_risk_multiplier
        scale = min(
            config.gross_cap / max(sum(base.values()), 1e-12),
            config.annual_volatility_target / estimated_vol,
        ) * risk_multiplier
        weights = {symbol: side * base[symbol] * scale for symbol in selected_symbols}
        targets.append({
            'timestamp': decision, 'weights': weights,
            'gross_weight': float(sum(abs(value) for value in weights.values())),
            'estimated_vol_annual': estimated_vol, 'vol_scale': scale,
            'selected': {
                symbol: {key: value for key, value in snapshots[symbol].items()
                         if key != 'returns'}
                for symbol in selected_symbols
            },
            'regime': regime,
        })
    return targets


def evaluate_regime_forward_returns(
    regimes: pd.DataFrame,
    btc_daily: pd.DataFrame,
    horizon_days: int = 20,
    sample_every_days: int = 7,
) -> dict:
    """Non-overlapping-ish diagnostic of subsequent BTC return by label."""
    if horizon_days < 1 or sample_every_days < 1:
        raise ValueError('Invalid regime diagnostic horizon')
    closes = btc_daily.close.astype(float)
    rows = []
    for decision, row in regimes.iloc[::sample_every_days].iterrows():
        known = _known_rows(btc_daily, decision)
        future = closes.loc[closes.index >= decision]
        if known.empty or len(future) < horizon_days:
            continue
        forward = float(future.iloc[horizon_days - 1] / known.close.iloc[-1] - 1)
        rows.append((row.regime, forward))
    result = {}
    for label in ('UP', 'DOWN', 'SIDEWAYS'):
        values = np.asarray([value for regime, value in rows if regime == label], dtype=float)
        result[label] = {
            'samples': int(len(values)),
            'mean_forward_return_pct': float(values.mean() * 100) if len(values) else None,
            'median_forward_return_pct': float(np.median(values) * 100) if len(values) else None,
            'directional_hit_rate': (
                float((values > 0).mean()) if label == 'UP' and len(values)
                else float((values < 0).mean()) if label == 'DOWN' and len(values)
                else None
            ),
        }
    return result
