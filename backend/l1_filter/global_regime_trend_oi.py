"""S101: asymmetric global regime with S99-style longs and OI-confirmed shorts."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .global_direction_oi import _known_rows, _utc, oi_oscillator, OIExecutionConfig


@dataclass(frozen=True)
class AsymmetricRegimeConfig:
    btc_symbol: str = 'BTCUSDT'
    long_sma_days: int = 200
    long_momentum_days: int = 84
    down_ema_days: int = 50
    down_fast_momentum_days: int = 28
    down_slow_momentum_days: int = 84
    up_breadth_threshold: float = 0.50
    down_breadth_threshold: float = 1 / 3
    confirmation_days: int = 2

    def validate(self):
        if self.long_sma_days < 50 or self.long_momentum_days < 10:
            raise ValueError('Invalid UP regime lookback')
        if not 5 <= self.down_ema_days < self.long_sma_days:
            raise ValueError('Invalid DOWN EMA')
        if not 2 <= self.down_fast_momentum_days < self.down_slow_momentum_days:
            raise ValueError('Invalid DOWN momentum')
        if not 0 < self.down_breadth_threshold < self.up_breadth_threshold < 1:
            raise ValueError('Invalid breadth thresholds')
        if self.confirmation_days < 1:
            raise ValueError('Invalid confirmation')


@dataclass(frozen=True)
class RegimeTrendOIConfig:
    long_momentum_days: int = 84
    long_sma_days: int = 200
    short_fast_momentum_days: int = 28
    short_slow_momentum_days: int = 84
    short_ema_days: int = 50
    vol_days: int = 42
    covariance_days: int = 60
    funding_days: int = 28
    max_long_mean_funding: float = 0.0001
    min_short_mean_funding: float = -0.0001
    minimum_short_oi_oscillator_pct: float = 0.05
    max_long_positions: int = 3
    max_short_positions: int = 2
    max_asset_weight: float = 0.45
    long_vol_target_annual: float = 0.15
    short_vol_target_annual: float = 0.075
    long_low_attention_scale: float = 0.75
    oi_attention_fraction: float = 2 / 3

    def validate(self):
        if not 2 <= self.long_momentum_days < self.long_sma_days:
            raise ValueError('Invalid long horizons')
        if not 2 <= self.short_fast_momentum_days < self.short_slow_momentum_days:
            raise ValueError('Invalid short momentum horizons')
        if not 5 <= self.short_ema_days < self.long_sma_days:
            raise ValueError('Invalid short EMA')
        if self.vol_days < 5 or self.covariance_days < self.vol_days:
            raise ValueError('Invalid risk horizons')
        if self.funding_days < 1 or self.max_long_positions < 1 or self.max_short_positions < 1:
            raise ValueError('Invalid portfolio settings')
        if not 0 < self.max_asset_weight <= 1:
            raise ValueError('Invalid concentration cap')
        if not 0 < self.short_vol_target_annual < self.long_vol_target_annual <= 1:
            raise ValueError('Invalid directional risk budgets')
        if not 0 < self.long_low_attention_scale <= 1:
            raise ValueError('Invalid attention scale')
        if not 0 <= self.oi_attention_fraction <= 1:
            raise ValueError('Invalid OI attention fraction')


def asymmetric_global_regimes(
    daily: dict[str, pd.DataFrame], start, end,
    config: AsymmetricRegimeConfig = AsymmetricRegimeConfig(),
) -> pd.DataFrame:
    """UP favors persistent bull trends; DOWN reacts faster to broad weakness."""
    config.validate()
    if config.btc_symbol not in daily or len(daily) < 3:
        raise ValueError('BTC and breadth assets are required')
    decisions = pd.date_range(_utc(start), _utc(end), freq='1D', inclusive='left')
    records = []
    minimum = max(config.long_sma_days, config.down_slow_momentum_days + 1)
    for decision in decisions:
        histories = {
            symbol: _known_rows(frame, decision).close.astype(float)
            for symbol, frame in daily.items()
        }
        btc = histories[config.btc_symbol]
        if len(btc) < minimum:
            records.append({'timestamp': decision, 'raw_regime': 'SIDEWAYS'})
            continue
        btc_sma = float(btc.iloc[-config.long_sma_days:].mean())
        btc_ema = float(btc.ewm(span=config.down_ema_days, adjust=False).mean().iloc[-1])
        btc_long_momentum = float(
            btc.iloc[-1] / btc.iloc[-1 - config.long_momentum_days] - 1)
        btc_fast_momentum = float(
            btc.iloc[-1] / btc.iloc[-1 - config.down_fast_momentum_days] - 1)
        btc_slow_momentum = float(
            btc.iloc[-1] / btc.iloc[-1 - config.down_slow_momentum_days] - 1)
        above_sma, positive_long, positive_fast = [], [], []
        for closes in histories.values():
            if len(closes) < minimum:
                continue
            above_sma.append(
                float(closes.iloc[-1]) > float(closes.iloc[-config.long_sma_days:].mean()))
            positive_long.append(
                float(closes.iloc[-1] / closes.iloc[-1 - config.long_momentum_days] - 1) > 0)
            positive_fast.append(
                float(closes.iloc[-1] / closes.iloc[-1 - config.down_fast_momentum_days] - 1) > 0)
        sma_breadth = float(np.mean(above_sma))
        long_momentum_breadth = float(np.mean(positive_long))
        fast_momentum_breadth = float(np.mean(positive_fast))
        up = (
            btc.iloc[-1] > btc_sma and btc_long_momentum > 0
            and sma_breadth >= config.up_breadth_threshold
            and long_momentum_breadth >= config.up_breadth_threshold)
        down = (
            btc.iloc[-1] < btc_ema and btc_fast_momentum < 0 and btc_slow_momentum < 0
            and fast_momentum_breadth <= config.down_breadth_threshold)
        raw = 'UP' if up else 'DOWN' if down else 'SIDEWAYS'
        records.append({
            'timestamp': decision, 'raw_regime': raw,
            'btc_vs_long_sma_pct': float((btc.iloc[-1] / btc_sma - 1) * 100),
            'btc_vs_down_ema_pct': float((btc.iloc[-1] / btc_ema - 1) * 100),
            'btc_long_momentum_pct': btc_long_momentum * 100,
            'btc_fast_momentum_pct': btc_fast_momentum * 100,
            'sma_breadth': sma_breadth,
            'long_momentum_breadth': long_momentum_breadth,
            'fast_momentum_breadth': fast_momentum_breadth,
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


def _oi_snapshot(oi: pd.Series, decision, minimum_days: int) -> dict | None:
    history = oi.loc[oi.index < _utc(decision)]
    oi_config = OIExecutionConfig()
    if len(history) < max(minimum_days, oi_config.oi_slow_days + oi_config.oi_velocity_days):
        return None
    row = oi_oscillator(history, oi_config).iloc[-1]
    return {
        'oscillator': float(row.oi_oscillator_pct),
        'velocity': float(row.oi_velocity_pct),
    }


def _candidate_snapshot(frame, funding, decision, regime, config):
    rows = _known_rows(frame, decision)
    required = max(config.long_sma_days, config.short_slow_momentum_days + 1,
                   config.covariance_days + 1)
    if len(rows) < required:
        return None
    closes = rows.close.astype(float)
    returns = np.log(closes).diff().dropna()
    annual_vol = float(returns.iloc[-config.vol_days:].std(ddof=1) * np.sqrt(365))
    if not np.isfinite(annual_vol) or annual_vol <= 1e-8:
        return None
    known_funding = funding.loc[
        (funding.index < _utc(decision))
        & (funding.index >= _utc(decision) - pd.Timedelta(days=config.funding_days))]
    if known_funding.empty:
        return None
    mean_funding = float(known_funding.mean())
    if regime == 'UP':
        momentum = float(closes.iloc[-1] / closes.iloc[-1 - config.long_momentum_days] - 1)
        sma = float(closes.iloc[-config.long_sma_days:].mean())
        eligible = (
            closes.iloc[-1] > sma and momentum > 0
            and mean_funding <= config.max_long_mean_funding)
        score = momentum / (annual_vol / np.sqrt(365) * np.sqrt(config.long_momentum_days))
    else:
        fast = float(closes.iloc[-1] / closes.iloc[-1 - config.short_fast_momentum_days] - 1)
        slow = float(closes.iloc[-1] / closes.iloc[-1 - config.short_slow_momentum_days] - 1)
        ema = float(closes.ewm(span=config.short_ema_days, adjust=False).mean().iloc[-1])
        eligible = (
            closes.iloc[-1] < ema and fast < 0 and slow < 0
            and mean_funding >= config.min_short_mean_funding)
        momentum = slow
        score = -fast / (annual_vol / np.sqrt(365) * np.sqrt(config.short_fast_momentum_days))
    return {
        'eligible': bool(eligible), 'score': float(score),
        'annual_vol': annual_vol, 'momentum': momentum,
        'mean_funding': mean_funding,
        'returns': returns.iloc[-config.covariance_days:],
        'last_completed_daily_open': str(rows.index[-1]),
    }


def weekly_regime_trend_oi_targets(
    daily: dict[str, pd.DataFrame], funding: dict[str, pd.Series],
    open_interest: dict[str, pd.Series], regimes: pd.DataFrame,
    start, end, config: RegimeTrendOIConfig = RegimeTrendOIConfig(),
    symbol_order=(), short_symbols=None,
) -> list[dict]:
    config.validate()
    symbols = tuple(symbol_order or daily)
    if set(symbols) != set(daily) or set(symbols) != set(funding):
        raise ValueError('Daily, funding and symbol universe must match')
    if not set(open_interest).issubset(symbols):
        raise ValueError('OI symbols must be in the trade universe')
    short_symbols = tuple(open_interest) if short_symbols is None else tuple(short_symbols)
    if not set(short_symbols).issubset(open_interest):
        raise ValueError('Short symbols require open-interest history')
    decisions = pd.date_range(_utc(start), _utc(end), freq='7D', inclusive='left')
    targets = []
    for decision in decisions:
        regime = str(regimes.loc[decision, 'regime'])
        if regime == 'SIDEWAYS':
            targets.append({'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                            'selected': {}, 'regime': regime, 'flat_reason': 'SIDEWAYS'})
            continue
        snapshots = {
            symbol: _candidate_snapshot(
                daily[symbol], funding[symbol], decision, regime, config)
            for symbol in symbols
        }
        oi_snapshots = {
            symbol: _oi_snapshot(series, decision, config.covariance_days)
            for symbol, series in open_interest.items()
        }
        if regime == 'UP':
            candidates = [symbol for symbol in symbols
                          if snapshots[symbol] is not None and snapshots[symbol]['eligible']]
            max_positions = config.max_long_positions
            side, vol_target = 1, config.long_vol_target_annual
            valid_oi = [row for row in oi_snapshots.values() if row is not None]
            attention = (float(np.mean([row['oscillator'] > 0 for row in valid_oi]))
                         if valid_oi else 0.0)
            attention_scale = (
                1.0 if attention >= config.oi_attention_fraction
                else config.long_low_attention_scale)
        else:
            candidates = [
                symbol for symbol in symbols
                if symbol in short_symbols and snapshots[symbol] is not None
                and snapshots[symbol]['eligible'] and oi_snapshots[symbol] is not None
                and oi_snapshots[symbol]['oscillator']
                >= config.minimum_short_oi_oscillator_pct
            ]
            max_positions = config.max_short_positions
            side, vol_target, attention, attention_scale = -1, config.short_vol_target_annual, 1.0, 1.0
        ranked = sorted(
            candidates, key=lambda symbol: (-snapshots[symbol]['score'], symbols.index(symbol))
        )[:max_positions]
        if not ranked:
            targets.append({'timestamp': decision, 'weights': {}, 'gross_weight': 0.0,
                            'selected': {}, 'regime': regime,
                            'flat_reason': 'NO_ELIGIBLE_ASSET'})
            continue
        inverse = {symbol: 1 / snapshots[symbol]['annual_vol'] for symbol in ranked}
        raw = {symbol: inverse[symbol] / sum(inverse.values()) for symbol in ranked}
        capped = {symbol: min(config.max_asset_weight, raw[symbol]) for symbol in ranked}
        aligned = pd.concat(
            [snapshots[symbol]['returns'].rename(symbol) for symbol in ranked],
            axis=1, join='inner').dropna().iloc[-config.covariance_days:]
        vector = np.array([capped[symbol] * side for symbol in ranked])
        covariance = aligned[ranked].cov().to_numpy(dtype=float) * 365
        variance = float(vector @ covariance @ vector)
        estimated_vol = float(np.sqrt(variance)) if variance > 0 else np.nan
        if not np.isfinite(estimated_vol) or estimated_vol <= 0:
            weights = {}
            scale = 0.0
        else:
            scale = min(1.0, vol_target / estimated_vol) * attention_scale
            weights = {symbol: side * capped[symbol] * scale for symbol in ranked}
        targets.append({
            'timestamp': decision, 'weights': weights,
            'gross_weight': float(sum(abs(value) for value in weights.values())),
            'estimated_vol_annual': estimated_vol, 'vol_scale': scale,
            'oi_attention_fraction': attention, 'regime': regime,
            'selected': {
                symbol: {
                    **{key: value for key, value in snapshots[symbol].items()
                       if key != 'returns'},
                    **({'oi_oscillator_pct': oi_snapshots[symbol]['oscillator']}
                       if symbol in oi_snapshots and oi_snapshots[symbol] is not None else {}),
                } for symbol in ranked
            },
        })
    return targets
