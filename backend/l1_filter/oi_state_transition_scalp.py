"""Causal S47 OI state-transition research signal."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class OIStateTransitionConfig:
    name: str = 'S47_oi_state_transition'
    pivot_width: int = 2
    sweep_penetration_atr_1h: float = 0.10
    stop_buffer_atr_1h: float = 0.15
    oi_reset_floor_fraction: float = 0.002
    oi_reset_quantile: float = 0.70
    oi_reset_lookback_bars: int = 2880
    oi_rebuild_fraction: float = 0.50
    confirmation_expiry_bars: int = 4
    displacement_body_atr_15m: float = 0.80
    confirmation_close_location: float = 0.75
    metrics_max_age_minutes: float = 10.0
    target_r: float = 2.5
    minimum_target_r: float = 1.5

    def __post_init__(self):
        if (self.pivot_width < 1 or self.sweep_penetration_atr_1h < 0
                or self.stop_buffer_atr_1h < 0
                or not 0 < self.oi_reset_floor_fraction < 1
                or not 0 < self.oi_reset_quantile < 1
                or self.oi_reset_lookback_bars < 2
                or not 0 < self.oi_rebuild_fraction <= 1
                or self.confirmation_expiry_bars < 1
                or self.displacement_body_atr_15m <= 0
                or not 0.5 < self.confirmation_close_location < 1
                or self.metrics_max_age_minutes < 0
                or self.minimum_target_r <= 0
                or self.target_r <= self.minimum_target_r):
            raise ValueError('Invalid S47 configuration')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=240,
            risk_fraction=0.002,
            max_notional_equity=0.5,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=5.0,
            max_margin_fraction=0.1,
            margin_safety_reserve=0.01,
            maker_fee_bps=5.0,
            limit_penetration_bps=0.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.5,
        )


def _confirmed_pivots(bars: pd.DataFrame, width: int) -> pd.DataFrame:
    """Publish pivots at confirmation time, never at the pivot timestamp."""
    highs = bars.high.to_numpy(dtype=float)
    lows = bars.low.to_numpy(dtype=float)
    latest_high = np.full(len(bars), np.nan)
    latest_low = np.full(len(bars), np.nan)
    high_times = np.full(len(bars), None, dtype=object)
    low_times = np.full(len(bars), None, dtype=object)
    current_high = current_low = np.nan
    current_high_time = current_low_time = None
    for known in range(len(bars)):
        if known >= 2 * width:
            pivot = known - width
            high_window = highs[pivot - width:pivot + width + 1]
            low_window = lows[pivot - width:pivot + width + 1]
            if np.isfinite(high_window).all() and highs[pivot] == high_window.max():
                current_high = highs[pivot]
                current_high_time = bars.index[pivot]
            if np.isfinite(low_window).all() and lows[pivot] == low_window.min():
                current_low = lows[pivot]
                current_low_time = bars.index[pivot]
        latest_high[known] = current_high
        latest_low[known] = current_low
        high_times[known] = current_high_time
        low_times[known] = current_low_time
    return pd.DataFrame({
        'latest_high': latest_high,
        'latest_low': latest_low,
        'latest_high_time': high_times,
        'latest_low_time': low_times,
    }, index=bars.index)


def _confirmed_structure(bars: pd.DataFrame, width: int) -> pd.Series:
    pivots = _confirmed_pivots(bars, width)
    last_high_time = last_low_time = None
    confirmed_highs: list[float] = []
    confirmed_lows: list[float] = []
    regime = np.zeros(len(bars), dtype=int)
    for i, row in enumerate(pivots.itertuples()):
        if row.latest_high_time is not None and row.latest_high_time is not pd.NaT:
            if row.latest_high_time != last_high_time:
                confirmed_highs.append(float(row.latest_high))
                last_high_time = row.latest_high_time
        if row.latest_low_time is not None and row.latest_low_time is not pd.NaT:
            if row.latest_low_time != last_low_time:
                confirmed_lows.append(float(row.latest_low))
                last_low_time = row.latest_low_time
        if len(confirmed_highs) >= 2 and len(confirmed_lows) >= 2:
            highs_up = confirmed_highs[-1] > confirmed_highs[-2]
            lows_up = confirmed_lows[-1] > confirmed_lows[-2]
            highs_down = confirmed_highs[-1] < confirmed_highs[-2]
            lows_down = confirmed_lows[-1] < confirmed_lows[-2]
            regime[i] = 1 if highs_up and lows_up else (-1 if highs_down and lows_down else 0)
    return pd.Series(regime, index=bars.index, name='htf_regime')


def build_oi_state_transition_features(
    minutes: pd.DataFrame,
    metrics: pd.DataFrame,
    config: OIStateTransitionConfig,
) -> pd.DataFrame:
    """Build closed-bar features; every value is available at its row timestamp."""
    bars = resample_closed(minutes, 15)
    hourly = resample_closed(minutes, 60)
    four_hour = resample_closed(minutes, 240)

    bars['atr15'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    hourly['atr1h'] = talib.ATR(
        hourly.high.to_numpy(), hourly.low.to_numpy(), hourly.close.to_numpy(), 14)
    bars['atr1h'] = hourly.atr1h.reindex(bars.index, method='ffill')
    bars['htf_regime'] = _confirmed_structure(
        four_hour, config.pivot_width).reindex(bars.index, method='ffill').fillna(0).astype(int)

    hourly_pivots = _confirmed_pivots(hourly, config.pivot_width)
    bars['liquidity_low'] = hourly_pivots.latest_low.reindex(bars.index, method='ffill')
    bars['liquidity_high'] = hourly_pivots.latest_high.reindex(bars.index, method='ffill')
    bars['liquidity_low_time'] = hourly_pivots.latest_low_time.reindex(
        bars.index, method='ffill')
    bars['liquidity_high_time'] = hourly_pivots.latest_high_time.reindex(
        bars.index, method='ffill')
    bars['opposing_1h_high'] = bars.liquidity_high
    bars['opposing_1h_low'] = bars.liquidity_low

    intraday_pivots = _confirmed_pivots(bars, config.pivot_width)
    bars['mss_high'] = intraday_pivots.latest_high
    bars['mss_low'] = intraday_pivots.latest_low

    if 'metrics_age_minutes' not in metrics or 'metrics_observed' not in metrics:
        raise ValueError('S47 requires metrics loaded with include_freshness=True')
    close_metrics = metrics.reindex(bars.index, method='ffill')
    open_index = bars.index - pd.Timedelta(minutes=15)
    open_metrics = metrics.reindex(open_index, method='ffill')
    open_metrics.index = bars.index
    bars['oi_open'] = open_metrics.open_interest
    bars['oi_close'] = close_metrics.open_interest
    bars['metrics_open_age_minutes'] = open_metrics.metrics_age_minutes
    bars['metrics_age_minutes'] = close_metrics.metrics_age_minutes

    absolute_change = (bars.oi_close - bars.oi_open).abs()
    trailing = absolute_change.shift(1).rolling(
        config.oi_reset_lookback_bars,
        min_periods=config.oi_reset_lookback_bars,
    ).quantile(config.oi_reset_quantile)
    bars['oi_reset_threshold'] = np.maximum(
        config.oi_reset_floor_fraction * bars.oi_open, trailing)
    return bars


def generate_oi_state_transition_signals(
    bars: pd.DataFrame,
    config: OIStateTransitionConfig,
    symbol: str,
) -> list[dict]:
    """Run the frozen sweep -> reset -> MSS -> rebuild state machine."""
    active: list[dict] = []
    consumed: set[tuple] = set()
    signals: list[dict] = []

    for i, row in enumerate(bars.itertuples()):
        still_active = []
        for setup in active:
            if i > setup['expires']:
                continue
            side = setup['side']
            setup['extreme'] = (
                min(setup['extreme'], float(row.low)) if side == 1
                else max(setup['extreme'], float(row.high)))
            if i <= setup['sweep_i']:
                still_active.append(setup)
                continue
            age = float(row.metrics_age_minutes)
            if not np.isfinite(age) or age > config.metrics_max_age_minutes:
                still_active.append(setup)
                continue
            candle_range = float(row.high - row.low)
            if candle_range <= 0 or not np.isfinite(row.atr15):
                still_active.append(setup)
                continue
            body = side * float(row.close - row.open)
            close_location = (
                (row.close - row.low) / candle_range if side == 1
                else (row.high - row.close) / candle_range)
            mss = side * float(row.close - setup['mss_level']) > 0
            displaced = body >= config.displacement_body_atr_15m * row.atr15
            flow = (
                row.taker_buy_volume > row.volume / 2 if side == 1
                else row.taker_buy_volume < row.volume / 2)
            rebuild = float(row.oi_close - setup['oi_sweep'])
            rebuild_ok = rebuild >= config.oi_rebuild_fraction * setup['oi_reset']
            if not (mss and displaced and close_location >= config.confirmation_close_location
                    and flow and rebuild_ok):
                still_active.append(setup)
                continue

            stop = (
                setup['extreme'] - config.stop_buffer_atr_1h * setup['atr1h']
                if side == 1 else
                setup['extreme'] + config.stop_buffer_atr_1h * setup['atr1h'])
            reference = float(row.close)
            risk = side * (reference - stop)
            if not np.isfinite(risk) or risk <= 0:
                continue
            fixed_target = reference + side * config.target_r * risk
            opposing = float(
                row.opposing_1h_high if side == 1 else row.opposing_1h_low)
            opposing_is_ahead = np.isfinite(opposing) and side * (opposing - reference) > 0
            target = (
                opposing if opposing_is_ahead
                and side * (opposing - fixed_target) < 0
                else fixed_target)
            achieved_r = side * (target - reference) / risk
            if achieved_r < config.minimum_target_r:
                continue
            direction = 'long' if side == 1 else 'short'
            signals.append({
                'timestamp': row.Index,
                'side': side,
                'reference': reference,
                'stop': float(stop),
                'target_price': float(target),
                'target_boundary': opposing if opposing_is_ahead else None,
                'min_target_r': config.minimum_target_r,
                'min_stop_atr': 0.5,
                'max_stop_atr': 6.0,
                'atr': float(row.atr15),
                'score': 0,
                'setup': 'oi_state_transition',
                'setup_id': (
                    f'S47:v1:{symbol}:{direction}:{setup["level_time"]}:'
                    f'{setup["sweep_time"].isoformat()}'),
                'evidence': {
                    'liquidity_level': setup['level'],
                    'oi_reset': setup['oi_reset'],
                    'oi_rebuild': rebuild,
                    'mss_level': setup['mss_level'],
                    'metrics_age_minutes': age,
                },
            })
        active = still_active

        side = int(row.htf_regime)
        if side not in (-1, 1):
            continue
        required = (
            row.atr1h, row.oi_open, row.oi_close, row.oi_reset_threshold,
            row.metrics_age_minutes,
        )
        if not all(np.isfinite(value) for value in required):
            continue
        open_age = float(getattr(row, 'metrics_open_age_minutes',
                                 row.metrics_age_minutes))
        if (open_age > config.metrics_max_age_minutes
                or row.metrics_age_minutes > config.metrics_max_age_minutes):
            continue
        oi_reset = float(row.oi_open - row.oi_close)
        if oi_reset < row.oi_reset_threshold:
            continue
        if side == 1:
            level = float(row.liquidity_low)
            level_time = row.liquidity_low_time
            swept = (np.isfinite(level)
                     and row.low <= level - config.sweep_penetration_atr_1h * row.atr1h
                     and row.close > level)
            mss_level = float(row.mss_high)
        else:
            level = float(row.liquidity_high)
            level_time = row.liquidity_high_time
            swept = (np.isfinite(level)
                     and row.high >= level + config.sweep_penetration_atr_1h * row.atr1h
                     and row.close < level)
            mss_level = float(row.mss_low)
        if not swept or not np.isfinite(mss_level):
            continue
        level_key = (side, str(level_time), level)
        if level_key in consumed:
            continue
        consumed.add(level_key)
        active.append({
            'side': side,
            'sweep_i': i,
            'expires': i + config.confirmation_expiry_bars,
            'sweep_time': row.Index,
            'level': level,
            'level_time': level_time,
            'mss_level': mss_level,
            'oi_sweep': float(row.oi_close),
            'oi_reset': oi_reset,
            'atr1h': float(row.atr1h),
            'extreme': float(row.low if side == 1 else row.high),
        })

    signals.sort(key=lambda item: item['timestamp'])
    return signals
