"""Causal strong-level liquidity sweep and failed-auction entries.

The setup is deliberately independent of FVG discovery.  It asks whether a
well-tested 15-minute liquidity level was swept by crowded, aggressive flow,
then waits for a later candle to break the sweep candle in the opposite
direction.  Global daily regime and the last completed 4-hour trend choose
the only permitted side.
"""
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FailedAuctionConfig:
    decision_minutes: int = 15
    atr_period: int = 14
    volume_lookback: int = 20
    liquidity_lookback_bars: int = 96
    level_touch_tolerance_atr: float = 0.25
    minimum_level_touches: int = 2
    sweep_buffer_atr: float = 0.02
    confirmation_buffer_atr: float = 0.03
    confirmation_window_bars: int = 3
    ema4h_span: int = 50
    oi_lookback_minutes: int = 60
    minimum_sweep_oi_change_pct: float = 0.05
    minimum_sweep_relative_volume: float = 1.10
    sweep_sell_taker_ratio: float = 0.48
    sweep_buy_taker_ratio: float = 0.52
    confirmation_buy_taker_ratio: float = 0.52
    confirmation_sell_taker_ratio: float = 0.48
    funding_lookback_days: int = 7
    maximum_long_mean_funding: float = 0.00005
    minimum_short_mean_funding: float = -0.00005
    maximum_metrics_age_minutes: float = 15.0
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 1.25
    maximum_stop_atr: float = 3.50
    minimum_target_r: float = 1.80
    maximum_target_r: float = 3.00
    target_front_run_fraction: float = 0.90
    max_hold_minutes: int = 24 * 60
    risk_scale: float = 0.50

    def validate(self) -> None:
        if self.decision_minutes < 5 or self.decision_minutes % 5:
            raise ValueError('Decision timeframe must be a positive 5m multiple')
        if self.atr_period < 2 or self.volume_lookback < 2:
            raise ValueError('Invalid rolling-feature lookback')
        if self.liquidity_lookback_bars < 8:
            raise ValueError('Liquidity lookback is too short')
        if not 0 < self.level_touch_tolerance_atr <= 1:
            raise ValueError('Invalid level-touch tolerance')
        if not 1 <= self.minimum_level_touches <= self.liquidity_lookback_bars:
            raise ValueError('Invalid minimum level touches')
        if self.sweep_buffer_atr < 0 or self.confirmation_buffer_atr < 0:
            raise ValueError('Invalid sweep or confirmation buffer')
        if self.confirmation_window_bars < 1 or self.ema4h_span < 2:
            raise ValueError('Invalid confirmation lifetime or 4h trend')
        if self.oi_lookback_minutes < self.decision_minutes:
            raise ValueError('OI lookback is shorter than one decision bar')
        if self.oi_lookback_minutes % self.decision_minutes:
            raise ValueError('OI lookback must align to decision bars')
        if not 0 < self.sweep_sell_taker_ratio < 0.5:
            raise ValueError('Invalid sell-aggression threshold')
        if not 0.5 < self.sweep_buy_taker_ratio < 1:
            raise ValueError('Invalid buy-aggression threshold')
        if not 0.5 < self.confirmation_buy_taker_ratio < 1:
            raise ValueError('Invalid long confirmation threshold')
        if not 0 < self.confirmation_sell_taker_ratio < 0.5:
            raise ValueError('Invalid short confirmation threshold')
        if self.funding_lookback_days < 1 or self.maximum_metrics_age_minutes < 0:
            raise ValueError('Invalid funding or freshness horizon')
        if not 0 < self.minimum_stop_atr < self.maximum_stop_atr:
            raise ValueError('Invalid stop bounds')
        if not 0 < self.minimum_target_r <= self.maximum_target_r:
            raise ValueError('Invalid target bounds')
        if not 0 < self.target_front_run_fraction <= 1:
            raise ValueError('Invalid target front-run fraction')
        if self.max_hold_minutes <= 0 or not 0 < self.risk_scale <= 1:
            raise ValueError('Invalid hold time or risk scale')


def _closed_resample(prices: pd.DataFrame, minutes: int) -> pd.DataFrame:
    expected = minutes // 5
    grouped = prices.resample(
        f'{minutes}min', origin='epoch', label='right', closed='left')
    bars = grouped.agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum',
    })
    complete = grouped.close.count() == expected
    if 'synthetic' in prices:
        complete &= ~grouped.synthetic.max().fillna(True).astype(bool)
    return bars.loc[complete].copy()


def _liquidity_features(bars: pd.DataFrame, config: FailedAuctionConfig) -> None:
    highs = bars.high.to_numpy(dtype=float)
    lows = bars.low.to_numpy(dtype=float)
    atr = bars.atr.to_numpy(dtype=float)
    prior_high = np.full(len(bars), np.nan)
    prior_low = np.full(len(bars), np.nan)
    high_touches = np.zeros(len(bars), dtype=int)
    low_touches = np.zeros(len(bars), dtype=int)
    width = config.liquidity_lookback_bars
    for index in range(width, len(bars)):
        high_window = highs[index - width:index]
        low_window = lows[index - width:index]
        high_level = float(np.max(high_window))
        low_level = float(np.min(low_window))
        prior_high[index] = high_level
        prior_low[index] = low_level
        tolerance = config.level_touch_tolerance_atr * atr[index]
        if np.isfinite(tolerance):
            high_touches[index] = int(np.sum(high_window >= high_level - tolerance))
            low_touches[index] = int(np.sum(low_window <= low_level + tolerance))
    bars['prior_liquidity_high'] = prior_high
    bars['prior_liquidity_low'] = prior_low
    bars['prior_target_liquidity_high'] = prior_high
    bars['prior_target_liquidity_low'] = prior_low
    bars['prior_high_touches'] = high_touches
    bars['prior_low_touches'] = low_touches


def build_failed_auction_features(
    prices_5m: pd.DataFrame,
    metrics_5m: pd.DataFrame,
    funding: pd.Series,
    config: FailedAuctionConfig = FailedAuctionConfig(),
) -> pd.DataFrame:
    """Build decision-time features from fully closed candles only."""
    config.validate()
    required_prices = {
        'open', 'high', 'low', 'close', 'volume', 'taker_buy_volume'}
    required_metrics = {
        'open_interest', 'taker_buy_sell_vol_ratio', 'metrics_age_minutes'}
    if not required_prices.issubset(prices_5m):
        raise ValueError('Five-minute prices lack required columns')
    if not required_metrics.issubset(metrics_5m):
        raise ValueError('Five-minute metrics lack required columns')
    if not prices_5m.index.equals(metrics_5m.index):
        raise ValueError('Price and metrics grids must match')

    bars = _closed_resample(prices_5m, config.decision_minutes)
    true_range = pd.concat([
        bars.high - bars.low,
        (bars.high - bars.close.shift()).abs(),
        (bars.low - bars.close.shift()).abs(),
    ], axis=1).max(axis=1)
    bars['atr'] = true_range.rolling(
        config.atr_period, min_periods=config.atr_period).mean()
    bars['relative_volume'] = bars.volume.div(
        bars.volume.shift().rolling(
            config.volume_lookback,
            min_periods=config.volume_lookback,
        ).median())
    bars['taker_ratio'] = bars.taker_buy_volume.div(
        bars.volume.where(bars.volume > 0))
    _liquidity_features(bars, config)

    metric_groups = metrics_5m.resample(
        f'{config.decision_minutes}min', origin='epoch',
        label='right', closed='left')
    metric_rows = metric_groups.agg({
        'open_interest': 'last',
        'taker_buy_sell_vol_ratio': 'last',
        'metrics_age_minutes': 'last',
    })
    complete_metrics = (
        metric_groups.open_interest.count() == config.decision_minutes // 5)
    bars = bars.join(metric_rows.loc[complete_metrics], how='left')
    oi_steps = config.oi_lookback_minutes // config.decision_minutes
    bars['oi_change_pct'] = (
        bars.open_interest / bars.open_interest.shift(oi_steps) - 1) * 100

    four_hour = _closed_resample(prices_5m, 240)
    four_hour['ema'] = four_hour.close.ewm(
        span=config.ema4h_span, adjust=False,
        min_periods=config.ema4h_span).mean()
    four_hour['trend4h'] = np.where(
        four_hour.close > four_hour.ema, 1,
        np.where(four_hour.close < four_hour.ema, -1, 0))
    bars['trend4h'] = four_hour.trend4h.reindex(bars.index, method='ffill')

    funding = funding.sort_index().astype(float)
    if funding.index.has_duplicates:
        raise ValueError('Funding timestamps must be unique')
    sparse_funding = funding.reindex(bars.index)
    bars['mean_funding'] = sparse_funding.rolling(
        f'{config.funding_lookback_days}D', closed='left', min_periods=3).mean()
    return bars


def _regime_series(regimes: pd.DataFrame | pd.Series,
                   index: pd.DatetimeIndex) -> pd.Series:
    source = regimes if isinstance(regimes, pd.Series) else regimes['regime']
    if source.empty or source.index.has_duplicates:
        raise ValueError('Regime series must be non-empty and unique')
    return source.sort_index().reindex(index, method='ffill').fillna('SIDEWAYS')


def generate_failed_auction_signals_from_bars(
    bars: pd.DataFrame,
    regimes: pd.DataFrame | pd.Series,
    symbol: str,
    config: FailedAuctionConfig = FailedAuctionConfig(),
) -> tuple[list[dict], dict]:
    """Arm on a crowded sweep, enter only on a later failed-auction break."""
    config.validate()
    required = {
        'open', 'high', 'low', 'close', 'atr', 'relative_volume',
        'taker_ratio', 'open_interest', 'oi_change_pct',
        'taker_buy_sell_vol_ratio', 'metrics_age_minutes', 'mean_funding',
        'trend4h', 'prior_liquidity_high', 'prior_liquidity_low',
        'prior_high_touches', 'prior_low_touches',
    }
    if not required.issubset(bars):
        raise ValueError(f'Feature bars lack {sorted(required - set(bars))}')
    regime = _regime_series(regimes, bars.index)
    signals: list[dict] = []
    diagnostics = Counter()
    state = None
    bar_delta = pd.Timedelta(minutes=config.decision_minutes)

    for timestamp, row in bars.iterrows():
        current_regime = str(regime.loc[timestamp])
        if not np.isfinite(row.atr) or row.atr <= 0:
            continue
        if state is not None:
            state['bars_waited'] += 1
            side = state['side']
            if (state['bars_waited'] > config.confirmation_window_bars
                    or current_regime != ('UP' if side == 1 else 'DOWN')
                    or int(row.trend4h) != side):
                diagnostics['armed_expired_or_regime_flip'] += 1
                state = None
            else:
                buffer = config.confirmation_buffer_atr * float(row.atr)
                broke = (
                    row.close > state['reaction_high'] + buffer
                    and row.close > row.open
                    if side == 1 else
                    row.close < state['reaction_low'] - buffer
                    and row.close < row.open
                )
                flow_flip = (
                    row.taker_ratio >= config.confirmation_buy_taker_ratio
                    and row.taker_buy_sell_vol_ratio > 1.0
                    if side == 1 else
                    row.taker_ratio <= config.confirmation_sell_taker_ratio
                    and row.taker_buy_sell_vol_ratio < 1.0
                )
                fresh = (
                    np.isfinite(row.metrics_age_minutes)
                    and row.metrics_age_minutes <= config.maximum_metrics_age_minutes)
                if broke and flow_flip and fresh:
                    reference_entry = float(row.close)
                    structural = (
                        state['sweep_extreme'] - config.stop_buffer_atr * row.atr
                        if side == 1 else
                        state['sweep_extreme'] + config.stop_buffer_atr * row.atr)
                    minimum = (
                        reference_entry - config.minimum_stop_atr * row.atr
                        if side == 1 else
                        reference_entry + config.minimum_stop_atr * row.atr)
                    stop = min(structural, minimum) if side == 1 else max(
                        structural, minimum)
                    stop_atr = side * (reference_entry - stop) / float(row.atr)
                    target_level = (
                        float(row.get(
                            'prior_target_liquidity_high',
                            row.prior_liquidity_high))
                        if side == 1 else
                        float(row.get(
                            'prior_target_liquidity_low',
                            row.prior_liquidity_low)))
                    raw_target = (
                        reference_entry
                        + config.target_front_run_fraction * (target_level - reference_entry))
                    price_risk = side * (reference_entry - stop)
                    raw_target_r = side * (raw_target - reference_entry) / price_risk
                    if not config.minimum_stop_atr <= stop_atr <= config.maximum_stop_atr:
                        diagnostics['blocked_stop_width'] += 1
                    elif not np.isfinite(raw_target_r) or raw_target_r < config.minimum_target_r:
                        diagnostics['blocked_target_space'] += 1
                    else:
                        target_r = min(config.maximum_target_r, raw_target_r)
                        target = reference_entry + side * target_r * price_risk
                        signals.append({
                            'timestamp': timestamp,
                            'side': side,
                            'stop': float(stop),
                            'atr': float(row.atr),
                            'target_price': float(target),
                            'min_target_r': config.minimum_target_r,
                            'max_hold_minutes': config.max_hold_minutes,
                            'risk_scale': config.risk_scale,
                            'score': float(
                                state['level_touches']
                                + state['sweep_oi_change_pct']
                                + state['sweep_relative_volume']),
                            'setup': 'failed_auction_long' if side == 1
                                     else 'failed_auction_short',
                            'setup_id': (
                                f'{symbol}:{state["sweep_at"].isoformat()}:'
                                f'{"LONG" if side == 1 else "SHORT"}'),
                            'evidence': {
                                'regime': current_regime,
                                'trend4h': int(row.trend4h),
                                'sweep_at': str(state['sweep_at']),
                                'level': state['level'],
                                'level_touches': state['level_touches'],
                                'sweep_extreme': state['sweep_extreme'],
                                'sweep_oi_change_pct': state['sweep_oi_change_pct'],
                                'sweep_relative_volume': state['sweep_relative_volume'],
                                'sweep_taker_ratio': state['sweep_taker_ratio'],
                                'sweep_archive_taker_ratio': (
                                    state['sweep_archive_taker_ratio']),
                                'mean_funding': state['mean_funding'],
                                'confirmation_taker_ratio': float(row.taker_ratio),
                                'confirmation_archive_taker_ratio': float(
                                    row.taker_buy_sell_vol_ratio),
                                'raw_target_r': float(raw_target_r),
                                'target_r': float(target_r),
                                'stop_atr': float(stop_atr),
                            },
                        })
                        diagnostics['signals'] += 1
                        diagnostics['long_signals' if side == 1 else 'short_signals'] += 1
                    state = None
                    continue
                if broke and not (flow_flip and fresh):
                    diagnostics['confirmation_without_flow_flip'] += 1

        if state is not None:
            continue
        fresh = (
            np.isfinite(row.metrics_age_minutes)
            and row.metrics_age_minutes <= config.maximum_metrics_age_minutes)
        common = (
            fresh
            and np.isfinite(row.oi_change_pct)
            and row.oi_change_pct >= config.minimum_sweep_oi_change_pct
            and np.isfinite(row.relative_volume)
            and row.relative_volume >= config.minimum_sweep_relative_volume
            and np.isfinite(row.mean_funding)
        )
        if not common:
            continue
        threshold = config.sweep_buffer_atr * float(row.atr)
        if current_regime == 'UP' and int(row.trend4h) == 1:
            side = 1
            level = float(row.prior_liquidity_low)
            touches = int(row.prior_low_touches)
            swept = (
                np.isfinite(level) and row.low < level - threshold
                and row.close > level
                and row.taker_ratio <= config.sweep_sell_taker_ratio
                and row.taker_buy_sell_vol_ratio < 1.0
                and row.mean_funding <= config.maximum_long_mean_funding)
            extreme = float(row.low)
        elif current_regime == 'DOWN' and int(row.trend4h) == -1:
            side = -1
            level = float(row.prior_liquidity_high)
            touches = int(row.prior_high_touches)
            swept = (
                np.isfinite(level) and row.high > level + threshold
                and row.close < level
                and row.taker_ratio >= config.sweep_buy_taker_ratio
                and row.taker_buy_sell_vol_ratio > 1.0
                and row.mean_funding >= config.minimum_short_mean_funding)
            extreme = float(row.high)
        else:
            continue
        if swept and touches >= config.minimum_level_touches:
            state = {
                'side': side,
                'sweep_at': timestamp,
                'bars_waited': 0,
                'reaction_high': float(row.high),
                'reaction_low': float(row.low),
                'sweep_extreme': extreme,
                'level': level,
                'level_touches': touches,
                'sweep_oi_change_pct': float(row.oi_change_pct),
                'sweep_relative_volume': float(row.relative_volume),
                'sweep_taker_ratio': float(row.taker_ratio),
                'sweep_archive_taker_ratio': float(
                    row.taker_buy_sell_vol_ratio),
                'mean_funding': float(row.mean_funding),
            }
            diagnostics['armed'] += 1
            diagnostics['long_armed' if side == 1 else 'short_armed'] += 1
    diagnostics['config'] = asdict(config)
    return signals, dict(diagnostics)


def generate_failed_auction_signals(
    prices_5m: pd.DataFrame,
    metrics_5m: pd.DataFrame,
    funding: pd.Series,
    regimes: pd.DataFrame | pd.Series,
    symbol: str,
    config: FailedAuctionConfig = FailedAuctionConfig(),
) -> tuple[list[dict], dict]:
    bars = build_failed_auction_features(prices_5m, metrics_5m, funding, config)
    return generate_failed_auction_signals_from_bars(
        bars, regimes, symbol, config)
