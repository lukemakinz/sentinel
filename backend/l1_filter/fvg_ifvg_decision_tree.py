"""Causal FVG/IFVG decision tree with regime and attention confluence.

The strategy does not enter merely because price touches an imbalance.  A
fresh 1h FVG is observed on closed 15m bars and can take one of two routes:

* DEFENSE: the original zone is reclaimed, then a later candle breaks the
  reaction candle in the original direction.
* IFVG: a candle closes through the far edge, the failed zone is retested from
  the other side, and a later candle breaks the rejection candle.

All timestamps are decision times.  A signal stamped 12:15 may therefore only
fill at the 12:15 five-minute open, after the 12:00-12:15 candle has closed.
"""
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FVGIFVGConfig:
    formation_minutes: int = 60
    confirmation_minutes: int = 15
    atr_period: int = 14
    volume_lookback: int = 20
    displacement_atr: float = 0.80
    displacement_volume: float = 1.15
    min_gap_atr: float = 0.05
    max_gap_atr: float = 1.25
    max_zone_age_hours: int = 120
    break_buffer_atr: float = 0.03
    reaction_body_atr: float = 0.10
    confirmation_window_bars: int = 3
    ema4h_span: int = 50
    oi_lookback_minutes: int = 60
    min_oi_change_pct: float = 0.05
    long_taker_ratio: float = 0.52
    short_taker_ratio: float = 0.48
    min_relative_volume: float = 1.0
    max_metrics_age_minutes: float = 15.0
    min_micro_confluence: int = 2
    require_liquidity_sweep: bool = False
    liquidity_lookback_bars: int = 20
    liquidity_sweep_atr: float = 0.02
    require_liquidity_reset: bool = False
    maximum_sweep_oi_change_15m_pct: float = 0.0
    require_liquidity_target: bool = False
    target_liquidity_lookback_bars: int = 20
    minimum_liquidity_target_r: float = 2.5
    maximum_liquidity_target_r: float | None = None
    target_front_run_fraction: float = 0.90
    stop_buffer_atr: float = 0.15
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 4.0
    target_r: float = 2.5
    max_hold_minutes: int = 12 * 60

    def validate(self) -> None:
        if self.formation_minutes % 5 or self.confirmation_minutes % 5:
            raise ValueError('Timeframes must be multiples of five minutes')
        if self.formation_minutes <= self.confirmation_minutes:
            raise ValueError('Formation timeframe must exceed confirmation timeframe')
        if self.atr_period < 2 or self.volume_lookback < 2:
            raise ValueError('Invalid feature lookback')
        if not 0 < self.min_gap_atr < self.max_gap_atr:
            raise ValueError('Invalid FVG depth bounds')
        if self.confirmation_window_bars < 1 or self.max_zone_age_hours < 1:
            raise ValueError('Invalid state lifetime')
        if not 0 <= self.min_micro_confluence <= 3:
            raise ValueError('Invalid confluence threshold')
        if self.liquidity_lookback_bars < 3 or self.liquidity_sweep_atr < 0:
            raise ValueError('Invalid liquidity sweep definition')
        if self.require_liquidity_reset and not self.require_liquidity_sweep:
            raise ValueError('Liquidity reset requires a structural sweep')
        if self.require_liquidity_target and not self.require_liquidity_sweep:
            raise ValueError('Liquidity target requires a structural sweep')
        if self.target_liquidity_lookback_bars < 3:
            raise ValueError('Invalid target-liquidity lookback')
        if (self.minimum_liquidity_target_r <= 0
                or not 0 < self.target_front_run_fraction <= 1):
            raise ValueError('Invalid liquidity target policy')
        if (self.maximum_liquidity_target_r is not None
                and self.maximum_liquidity_target_r
                < self.minimum_liquidity_target_r):
            raise ValueError('Maximum liquidity target must exceed minimum')
        if not 0 < self.short_taker_ratio < 0.5 < self.long_taker_ratio < 1:
            raise ValueError('Invalid taker thresholds')
        if not 0 < self.minimum_stop_atr < self.maximum_stop_atr:
            raise ValueError('Invalid stop bounds')
        if self.target_r <= 0 or self.max_hold_minutes <= 0:
            raise ValueError('Invalid exit policy')


@dataclass(frozen=True)
class FVGZone:
    zone_id: str
    created_at: pd.Timestamp
    direction: str
    bottom: float
    top: float
    formation_atr: float
    displacement_atr: float
    displacement_relative_volume: float

    @property
    def depth(self) -> float:
        return self.top - self.bottom


def _validate_five_minute(frame: pd.DataFrame) -> None:
    required = {'open', 'high', 'low', 'close', 'volume', 'taker_buy_volume'}
    if not required.issubset(frame.columns):
        raise ValueError(f'Missing columns: {sorted(required.difference(frame.columns))}')
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError('Five-minute bars must be non-empty, unique and sorted')
    if not (frame.index.to_series().diff().dropna() == pd.Timedelta(minutes=5)).all():
        raise ValueError('Five-minute bars are discontinuous')


def _closed_resample(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate open-time bars and label each row by its availability time."""
    if minutes % 5:
        raise ValueError('Resample interval must be a multiple of five minutes')
    expected = minutes // 5
    rule = f'{minutes}min'
    grouped = frame.resample(rule, origin='epoch', label='right', closed='left')
    result = grouped.agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum',
    })
    counts = grouped['close'].count()
    complete = counts == expected
    if 'synthetic' in frame:
        complete &= ~grouped['synthetic'].max().fillna(True).astype(bool)
    result = result.loc[complete].copy()
    true_range = pd.concat([
        result.high - result.low,
        (result.high - result.close.shift()).abs(),
        (result.low - result.close.shift()).abs(),
    ], axis=1).max(axis=1)
    result['atr'] = true_range.rolling(14, min_periods=14).mean()
    result['relative_volume'] = (
        result.volume / result.volume.shift().rolling(20, min_periods=20).median())
    result['taker_ratio'] = result.taker_buy_volume.div(
        result.volume.where(result.volume > 0))
    return result


def build_fvg_ifvg_features(
    prices_5m: pd.DataFrame,
    metrics_5m: pd.DataFrame,
    config: FVGIFVGConfig = FVGIFVGConfig(),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build closed 1h formation bars and closed 15m decision bars."""
    config.validate()
    _validate_five_minute(prices_5m)
    required_metrics = {
        'open_interest', 'taker_buy_sell_vol_ratio', 'metrics_age_minutes',
    }
    if not required_metrics.issubset(metrics_5m.columns):
        raise ValueError('Missing OI/taker/freshness metrics')
    if not prices_5m.index.equals(metrics_5m.index):
        raise ValueError('Price and metrics grids must match exactly')

    formation = _closed_resample(prices_5m, config.formation_minutes)
    confirmation = _closed_resample(prices_5m, config.confirmation_minutes)
    formation_true_range = pd.concat([
        formation.high - formation.low,
        (formation.high - formation.close.shift()).abs(),
        (formation.low - formation.close.shift()).abs(),
    ], axis=1).max(axis=1)
    formation['atr'] = formation_true_range.rolling(
        config.atr_period, min_periods=config.atr_period).mean()
    confirmation['atr'] = pd.concat([
        confirmation.high - confirmation.low,
        (confirmation.high - confirmation.close.shift()).abs(),
        (confirmation.low - confirmation.close.shift()).abs(),
    ], axis=1).max(axis=1).rolling(
        config.atr_period, min_periods=config.atr_period).mean()
    confirmation['relative_volume'] = (
        confirmation.volume
        / confirmation.volume.shift().rolling(
            config.volume_lookback, min_periods=config.volume_lookback).median())
    confirmation['prior_liquidity_high'] = confirmation.high.shift().rolling(
        config.liquidity_lookback_bars,
        min_periods=config.liquidity_lookback_bars).max()
    confirmation['prior_liquidity_low'] = confirmation.low.shift().rolling(
        config.liquidity_lookback_bars,
        min_periods=config.liquidity_lookback_bars).min()
    confirmation['prior_target_liquidity_high'] = (
        confirmation.high.shift().rolling(
            config.target_liquidity_lookback_bars,
            min_periods=config.target_liquidity_lookback_bars).max())
    confirmation['prior_target_liquidity_low'] = (
        confirmation.low.shift().rolling(
            config.target_liquidity_lookback_bars,
            min_periods=config.target_liquidity_lookback_bars).min())

    metric_groups = metrics_5m.resample(
        f'{config.confirmation_minutes}min', origin='epoch',
        label='right', closed='left')
    metric_rows = metric_groups.agg({
        'open_interest': 'last',
        'taker_buy_sell_vol_ratio': 'last',
        'metrics_age_minutes': 'last',
    })
    metric_counts = metric_groups['open_interest'].count()
    metric_rows = metric_rows.loc[
        metric_counts == config.confirmation_minutes // 5]
    confirmation = confirmation.join(metric_rows, how='left')
    oi_steps = config.oi_lookback_minutes // config.confirmation_minutes
    confirmation['oi_change_pct'] = (
        confirmation.open_interest
        / confirmation.open_interest.shift(oi_steps) - 1) * 100
    confirmation['oi_change_15m_pct'] = (
        confirmation.open_interest / confirmation.open_interest.shift() - 1) * 100

    four_hour = _closed_resample(prices_5m, 240)
    four_hour['ema4h'] = four_hour.close.ewm(
        span=config.ema4h_span, adjust=False,
        min_periods=config.ema4h_span).mean()
    four_hour['trend4h'] = np.where(
        four_hour.close > four_hour.ema4h, 1,
        np.where(four_hour.close < four_hour.ema4h, -1, 0))
    confirmation['trend4h'] = four_hour.trend4h.reindex(
        confirmation.index, method='ffill')
    return formation, confirmation


def detect_fvg_zones(
    formation: pd.DataFrame,
    symbol: str,
    config: FVGIFVGConfig = FVGIFVGConfig(),
) -> list[FVGZone]:
    """Detect directionally displaced three-candle imbalances on closed bars."""
    config.validate()
    required = {'open', 'high', 'low', 'close', 'volume', 'atr'}
    if not required.issubset(formation.columns):
        raise ValueError('Formation bars lack required OHLCV/ATR fields')
    baseline = formation.volume.shift().rolling(
        config.volume_lookback, min_periods=config.volume_lookback).median()
    zones: list[FVGZone] = []
    for i in range(2, len(formation)):
        first, displacement, third = (
            formation.iloc[i - 2], formation.iloc[i - 1], formation.iloc[i])
        atr = float(displacement.atr)
        median_volume = float(baseline.iloc[i - 1])
        if not np.isfinite(atr) or atr <= 0 or not np.isfinite(median_volume):
            continue
        body_atr = abs(float(displacement.close - displacement.open)) / atr
        relative_volume = float(displacement.volume) / max(median_volume, 1e-12)
        if (body_atr < config.displacement_atr
                or relative_volume < config.displacement_volume):
            continue
        created_at = pd.Timestamp(formation.index[i])
        candidates = []
        if displacement.close > displacement.open and first.high < third.low:
            candidates.append(('bullish', float(first.high), float(third.low)))
        if displacement.close < displacement.open and third.high < first.low:
            candidates.append(('bearish', float(third.high), float(first.low)))
        for direction, bottom, top in candidates:
            gap_atr = (top - bottom) / atr
            if not config.min_gap_atr <= gap_atr <= config.max_gap_atr:
                continue
            zones.append(FVGZone(
                zone_id=f'{symbol}:{created_at.isoformat()}:{direction}',
                created_at=created_at, direction=direction,
                bottom=bottom, top=top, formation_atr=atr,
                displacement_atr=body_atr,
                displacement_relative_volume=relative_volume,
            ))
    return zones


def _regime_at(regimes: pd.DataFrame | pd.Series, timestamp: pd.Timestamp) -> str:
    series = regimes if isinstance(regimes, pd.Series) else regimes['regime']
    known = series.loc[series.index <= timestamp]
    return str(known.iloc[-1]) if not known.empty else 'SIDEWAYS'


def _confluence(row: pd.Series, side: int, regime: str,
                config: FVGIFVGConfig) -> tuple[bool, dict]:
    regime_ok = regime == ('UP' if side == 1 else 'DOWN')
    trend_ok = int(row.trend4h) == side if np.isfinite(row.trend4h) else False
    fresh = (np.isfinite(row.metrics_age_minutes)
             and row.metrics_age_minutes <= config.max_metrics_age_minutes)
    oi_ok = fresh and np.isfinite(row.oi_change_pct) and (
        row.oi_change_pct >= config.min_oi_change_pct)
    taker_value = float(row.taker_ratio)
    archive_taker = float(row.taker_buy_sell_vol_ratio)
    taker_ok = (
        taker_value >= config.long_taker_ratio and archive_taker > 1
        if side == 1 else
        taker_value <= config.short_taker_ratio and archive_taker < 1)
    volume_ok = (np.isfinite(row.relative_volume)
                 and row.relative_volume >= config.min_relative_volume)
    micro = int(oi_ok) + int(taker_ok) + int(volume_ok)
    evidence = {
        'regime': regime, 'regime_ok': regime_ok, 'trend4h_ok': trend_ok,
        'oi_change_pct': float(row.oi_change_pct), 'oi_expansion_ok': bool(oi_ok),
        'taker_ratio': taker_value,
        'archive_taker_buy_sell_ratio': archive_taker,
        'taker_ok': bool(taker_ok), 'relative_volume': float(row.relative_volume),
        'relative_volume_ok': bool(volume_ok), 'micro_score': micro,
        'metrics_age_minutes': float(row.metrics_age_minutes),
    }
    return bool(regime_ok and trend_ok and micro >= config.min_micro_confluence), evidence


def _liquidity_sweep_extreme(
    row: pd.Series, side: int, config: FVGIFVGConfig,
) -> float | None:
    """Return the sweep extreme only after price closes back through liquidity."""
    threshold = config.liquidity_sweep_atr * float(row.atr)
    if side == 1:
        level = float(row.prior_liquidity_low)
        if (np.isfinite(level) and row.low < level - threshold
                and row.close > level):
            return float(row.low)
    else:
        level = float(row.prior_liquidity_high)
        if (np.isfinite(level) and row.high > level + threshold
                and row.close < level):
            return float(row.high)
    return None


def _liquidity_reset_evidence(
    state: dict, row: pd.Series, side: int, config: FVGIFVGConfig,
) -> tuple[bool, dict]:
    snapshot = state.get('sweep_snapshot') or {}
    sweep_oi = float(snapshot.get('oi_change_15m_pct', np.nan))
    sweep_taker = float(snapshot.get('taker_ratio', np.nan))
    confirm_oi = float(row.oi_change_15m_pct)
    confirm_taker = float(row.taker_ratio)
    sweep_flow_ok = (
        sweep_taker <= config.short_taker_ratio if side == 1
        else sweep_taker >= config.long_taker_ratio)
    confirmation_flow_ok = (
        confirm_taker >= config.long_taker_ratio if side == 1
        else confirm_taker <= config.short_taker_ratio)
    oi_flush_ok = (np.isfinite(sweep_oi)
                   and sweep_oi <= config.maximum_sweep_oi_change_15m_pct)
    oi_stabilized = np.isfinite(confirm_oi) and confirm_oi > sweep_oi
    evidence = {
        'sweep_oi_change_15m_pct': sweep_oi,
        'sweep_taker_ratio': sweep_taker,
        'confirmation_oi_change_15m_pct': confirm_oi,
        'confirmation_taker_ratio': confirm_taker,
        'sweep_flow_ok': bool(sweep_flow_ok),
        'confirmation_flow_ok': bool(confirmation_flow_ok),
        'oi_flush_ok': bool(oi_flush_ok),
        'oi_stabilized': bool(oi_stabilized),
    }
    return bool(sweep_flow_ok and confirmation_flow_ok
                and oi_flush_ok and oi_stabilized), evidence


def generate_fvg_ifvg_signals_from_bars(
    formation: pd.DataFrame,
    confirmation: pd.DataFrame,
    regimes: pd.DataFrame | pd.Series,
    symbol: str,
    config: FVGIFVGConfig = FVGIFVGConfig(),
) -> tuple[list[dict], dict]:
    """Run the causal zone state machine and return next-open entry signals."""
    config.validate()
    zones = detect_fvg_zones(formation, symbol, config)
    required = {
        'open', 'high', 'low', 'close', 'atr', 'relative_volume',
        'taker_ratio', 'open_interest', 'oi_change_pct',
        'taker_buy_sell_vol_ratio', 'metrics_age_minutes', 'trend4h',
    }
    if not required.issubset(confirmation.columns):
        raise ValueError(f'Confirmation bars lack {sorted(required - set(confirmation))}')
    if config.require_liquidity_sweep:
        liquidity_columns = {'prior_liquidity_high', 'prior_liquidity_low'}
        if not liquidity_columns.issubset(confirmation.columns):
            raise ValueError('Liquidity-sweep mode requires prior high/low features')
    if config.require_liquidity_target:
        target_columns = {
            'prior_target_liquidity_high', 'prior_target_liquidity_low',
        }
        if not target_columns.issubset(confirmation.columns):
            raise ValueError(
                'Liquidity-target mode requires external liquidity features')
    if config.require_liquidity_reset and 'oi_change_15m_pct' not in confirmation:
        raise ValueError('Liquidity-reset mode requires 15m OI change')
    states = []
    zone_cursor = 0
    signals: list[dict] = []
    diagnostics = Counter(zones=len(zones))
    bar_delta = pd.Timedelta(minutes=config.confirmation_minutes)

    def arm(state, row, timestamp, status):
        state['status'] = status
        state['armed_at'] = timestamp
        state['reaction_high'] = float(row.high)
        state['reaction_low'] = float(row.low)

    for timestamp, row in confirmation.iterrows():
        if not np.isfinite(row.atr) or row.atr <= 0:
            continue
        while zone_cursor < len(zones) and zones[zone_cursor].created_at < timestamp:
            states.append({
                'zone': zones[zone_cursor], 'status': 'FRESH', 'touch_at': None,
                'touch_extreme': None, 'armed_at': None, 'reaction_high': None,
                'reaction_low': None, 'sweep_extreme': None,
                'sweep_snapshot': None,
            })
            zone_cursor += 1
        for state in states:
            zone = state['zone']
            if state['status'] == 'DONE' or timestamp <= zone.created_at:
                continue
            if timestamp - zone.created_at > pd.Timedelta(
                    hours=config.max_zone_age_hours):
                state['status'] = 'DONE'
                diagnostics['expired'] += 1
                continue
            buffer = config.break_buffer_atr * float(row.atr)
            touched = row.low <= zone.top and row.high >= zone.bottom
            original_side = 1 if zone.direction == 'bullish' else -1
            invalidated = (
                row.close < zone.bottom - buffer if original_side == 1
                else row.close > zone.top + buffer)
            reclaimed = (
                row.close > zone.top + buffer and row.close > row.open
                if original_side == 1 else
                row.close < zone.bottom - buffer and row.close < row.open)
            body_ok = abs(float(row.close - row.open)) >= (
                config.reaction_body_atr * float(row.atr))

            if state['status'] == 'FRESH':
                if not touched:
                    continue
                state['status'] = 'TOUCHED'
                state['touch_at'] = timestamp
                state['touch_extreme'] = float(
                    row.low if original_side == 1 else row.high)
                diagnostics['touched'] += 1

            if state['status'] == 'TOUCHED':
                state['touch_extreme'] = (
                    min(state['touch_extreme'], float(row.low)) if original_side == 1
                    else max(state['touch_extreme'], float(row.high)))
                sweep = (_liquidity_sweep_extreme(row, original_side, config)
                         if config.require_liquidity_sweep else None)
                if sweep is not None:
                    state['sweep_extreme'] = (
                        min(state['sweep_extreme'], sweep)
                        if original_side == 1 and state['sweep_extreme'] is not None
                        else max(state['sweep_extreme'], sweep)
                        if original_side == -1 and state['sweep_extreme'] is not None
                        else sweep)
                    diagnostics['liquidity_sweep_seen'] += 1
                    state['sweep_snapshot'] = {
                        'oi_change_15m_pct': float(
                            row.get('oi_change_15m_pct', np.nan)),
                        'taker_ratio': float(row.taker_ratio),
                        'timestamp': str(timestamp),
                    }
                if invalidated:
                    state['status'] = 'INVALIDATED'
                    state['armed_at'] = timestamp
                    diagnostics['invalidated_by_close'] += 1
                    continue
                if reclaimed and body_ok:
                    if (config.require_liquidity_sweep
                            and state['sweep_extreme'] is None):
                        state['status'] = 'DONE'
                        diagnostics['defense_without_liquidity_sweep'] += 1
                        continue
                    arm(state, row, timestamp, 'DEFENSE_ARMED')
                    diagnostics['defense_armed'] += 1
                    continue

            if state['status'] == 'INVALIDATED':
                if timestamp <= state['armed_at']:
                    continue
                if touched:
                    rejection = (
                        row.close < zone.bottom - buffer and row.close < row.open
                        if original_side == 1 else
                        row.close > zone.top + buffer and row.close > row.open)
                    crossed_back = (
                        row.close > zone.top + buffer if original_side == 1
                        else row.close < zone.bottom - buffer)
                    if crossed_back:
                        state['status'] = 'DONE'
                        diagnostics['ifvg_failed_reclaim'] += 1
                    elif rejection and body_ok:
                        sweep = (
                            _liquidity_sweep_extreme(row, -original_side, config)
                            if config.require_liquidity_sweep else None)
                        if config.require_liquidity_sweep and sweep is None:
                            state['status'] = 'DONE'
                            diagnostics['ifvg_without_liquidity_sweep'] += 1
                            continue
                        if sweep is not None:
                            state['sweep_extreme'] = sweep
                            state['sweep_snapshot'] = {
                                'oi_change_15m_pct': float(
                                    row.get('oi_change_15m_pct', np.nan)),
                                'taker_ratio': float(row.taker_ratio),
                                'timestamp': str(timestamp),
                            }
                            diagnostics['liquidity_sweep_seen'] += 1
                        arm(state, row, timestamp, 'IFVG_ARMED')
                        diagnostics['ifvg_armed'] += 1
                    else:
                        state['status'] = 'DONE'
                        diagnostics['ifvg_first_retest_no_rejection'] += 1
                continue

            if state['status'] not in ('DEFENSE_ARMED', 'IFVG_ARMED'):
                continue
            if state['status'] == 'DEFENSE_ARMED' and invalidated:
                state['status'] = 'INVALIDATED'
                state['armed_at'] = timestamp
                diagnostics['defense_failed_to_ifvg'] += 1
                continue
            if state['status'] == 'IFVG_ARMED':
                if ((original_side == 1 and row.close > zone.top + buffer)
                        or (original_side == -1
                            and row.close < zone.bottom - buffer)):
                    state['status'] = 'DONE'
                    diagnostics['ifvg_rejection_failed'] += 1
                    continue
            elapsed = int((timestamp - state['armed_at']) / bar_delta)
            if elapsed < 1:
                continue
            if elapsed > config.confirmation_window_bars:
                state['status'] = 'DONE'
                diagnostics['confirmation_expired'] += 1
                continue
            route = 'DEFENSE' if state['status'] == 'DEFENSE_ARMED' else 'IFVG'
            side = original_side if route == 'DEFENSE' else -original_side
            broke = (
                row.high > state['reaction_high'] if side == 1
                else row.low < state['reaction_low'])
            if not broke:
                continue
            regime = _regime_at(regimes, timestamp)
            allowed, evidence = _confluence(row, side, regime, config)
            state['status'] = 'DONE'
            diagnostics['break_confirmed'] += 1
            if not allowed:
                diagnostics['confluence_veto'] += 1
                continue
            reset_evidence = {}
            if config.require_liquidity_reset:
                reset_ok, reset_evidence = _liquidity_reset_evidence(
                    state, row, side, config)
                if not reset_ok:
                    diagnostics['liquidity_reset_veto'] += 1
                    continue
            if config.require_liquidity_sweep:
                raw_stop = state['sweep_extreme'] - side * (
                    config.stop_buffer_atr * float(row.atr))
                stop = raw_stop
            else:
                raw_stop = (
                    min(state['touch_extreme'], state['reaction_low'])
                    - config.stop_buffer_atr * float(row.atr)
                    if side == 1 else
                    max(state['touch_extreme'], state['reaction_high'])
                    + config.stop_buffer_atr * float(row.atr))
                minimum_stop = float(row.close) - side * (
                    config.minimum_stop_atr * float(row.atr))
                stop = min(raw_stop, minimum_stop) if side == 1 else max(
                    raw_stop, minimum_stop)
            stop_atr = side * (float(row.close) - stop) / float(row.atr)
            if stop_atr < config.minimum_stop_atr:
                diagnostics['stop_too_tight'] += 1
                continue
            if stop_atr > config.maximum_stop_atr:
                diagnostics['stop_too_wide'] += 1
                continue
            target_fields = {'target_r': config.target_r}
            target_evidence = {}
            if config.require_liquidity_target:
                pool = float(
                    row.prior_target_liquidity_high if side == 1
                    else row.prior_target_liquidity_low)
                raw_decision_target = (
                    float(row.close) + config.target_front_run_fraction * (
                    pool - float(row.close))
                )
                available_target_r = side * (
                    raw_decision_target - float(row.close)) / (
                    side * (float(row.close) - stop))
                target_evidence = {
                    'opposing_liquidity_pool': pool,
                    'raw_decision_target_price': raw_decision_target,
                    'available_target_r': available_target_r,
                }
                if (not np.isfinite(available_target_r)
                        or available_target_r
                        < config.minimum_liquidity_target_r):
                    diagnostics['insufficient_liquidity_target_space'] += 1
                    continue
                decision_target_r = available_target_r
                if config.maximum_liquidity_target_r is not None:
                    decision_target_r = min(
                        decision_target_r,
                        config.maximum_liquidity_target_r)
                decision_target = (
                    float(row.close) + side * decision_target_r
                    * side * (float(row.close) - stop))
                target_evidence.update({
                    'decision_target_price': decision_target,
                    'decision_target_r': decision_target_r,
                })
                target_fields = {
                    'target_price': decision_target,
                    'min_target_r': config.minimum_liquidity_target_r,
                }
            score = (
                float(evidence['micro_score'])
                + min(zone.displacement_atr, 2.0)
                + min(zone.displacement_relative_volume, 2.0) / 2)
            signals.append({
                'timestamp': timestamp, 'side': side, 'stop': float(stop),
                'atr': float(row.atr), 'score': score,
                'setup': f'fvg_ifvg_{route.lower()}',
                'setup_id': f'{zone.zone_id}:{route}',
                **target_fields,
                'max_hold_minutes': config.max_hold_minutes,
                'evidence': {
                    **evidence, **reset_evidence, **target_evidence,
                    'route': route, 'zone_id': zone.zone_id,
                    'zone_direction': zone.direction, 'zone_bottom': zone.bottom,
                    'zone_top': zone.top, 'zone_age_hours': (
                        timestamp - zone.created_at).total_seconds() / 3600,
                    'formation_displacement_atr': zone.displacement_atr,
                    'formation_relative_volume': zone.displacement_relative_volume,
                    'liquidity_sweep_required': config.require_liquidity_sweep,
                    'liquidity_sweep_extreme': state['sweep_extreme'],
                    'stop_distance_atr_at_decision': stop_atr,
                },
            })
            diagnostics[f'signals_{route.lower()}'] += 1
            diagnostics['signals_long' if side == 1 else 'signals_short'] += 1
        states = [state for state in states if state['status'] != 'DONE']

    # Multiple old zones can resolve on one candle.  Keep the strongest causal
    # interpretation per symbol/timestamp so one event is not double-counted.
    best = {}
    for signal in signals:
        key = signal['timestamp']
        if key not in best or signal['score'] > best[key]['score']:
            best[key] = signal
    diagnostics['deduplicated_signals'] = len(best)
    diagnostics['config'] = asdict(config)
    return sorted(best.values(), key=lambda item: item['timestamp']), dict(diagnostics)


def generate_fvg_ifvg_signals(
    prices_5m: pd.DataFrame,
    metrics_5m: pd.DataFrame,
    regimes: pd.DataFrame | pd.Series,
    symbol: str,
    config: FVGIFVGConfig = FVGIFVGConfig(),
) -> tuple[list[dict], dict]:
    formation, confirmation = build_fvg_ifvg_features(
        prices_5m, metrics_5m, config)
    return generate_fvg_ifvg_signals_from_bars(
        formation, confirmation, regimes, symbol, config)
