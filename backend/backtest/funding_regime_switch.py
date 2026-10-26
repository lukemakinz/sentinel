"""Causal S36 funding-regime signal generation.

The module deliberately stops at an immutable entry candidate.  It does not
size positions, simulate fills, or inspect PnL.  Five-minute frame indices are
bar-open timestamps: for a funding event at ``T``, ``B0`` opens at ``T-5m``;
``B1`` through ``B3`` open at ``T`` through ``T+10m``; classification is
available at ``T+15m``.  A candidate can only enter at the open after a later
fully completed retest bar.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from backtest.post_funding_exhaustion import wilder_atr


FIVE_MINUTES = pd.Timedelta(minutes=5)
DEFAULT_SYMBOL_PRIORITY = (
    'SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT',
)


class Regime(str, Enum):
    FADE = 'FADE'
    CONTINUATION = 'CONTINUATION'
    NO_TRADE = 'NO_TRADE'


@dataclass(frozen=True)
class FundingRegimeConfig:
    """Frozen S36 signal parameters; no execution or PnL parameters."""

    history_events: int = 180
    funding_floor: float = .0001
    funding_quantile: float = .75
    event_quorum: int = 3
    premium_floor: float = .0002
    premium_quantile: float = .75
    return_60m_quantile: float = .65
    return_4h_quantile: float = .60
    bollinger_period: int = 20
    bollinger_event_z: float = 1.50
    volume_event_bars: int = 12
    volume_history_bars: int = 2016
    volume_expansion: float = 1.50
    atr_period: int = 14
    fade_structure_atr: float = .05
    continuation_structure_atr: float = .05
    premium_fade_ratio: float = .50
    premium_continuation_ratio: float = .75
    premium_continuation_bar_ratio: float = .50
    displacement_body_atr: float = .50
    displacement_close_fraction: float = .25
    delta_threshold: float = .10
    observation_move_atr: float = .50
    continuation_bollinger_z: float = 1.00
    soft_quorum: int = 2
    retest_bars: int = 3
    retest_touch_atr: float = .10
    retest_acceptance_atr: float = .05
    retest_fade_premium_ratio: float = .75
    retest_continuation_premium_ratio: float = .50
    retest_invalid_atr: float = .15
    retest_extension_atr: float = 1.50
    liquidity_lookback_bars: int = 12
    maximum_quote_volume_fraction: float = .001
    symbol_priority: tuple[str, ...] = DEFAULT_SYMBOL_PRIORITY

    def validate(self) -> None:
        quantiles = (
            self.funding_quantile, self.premium_quantile,
            self.return_60m_quantile, self.return_4h_quantile,
        )
        if self.history_events < 2 or any(not 0 < q < 1 for q in quantiles):
            raise ValueError('Invalid S36 event history or quantile')
        if (self.event_quorum < 1 or self.event_quorum > 5
                or self.soft_quorum < 1 or self.soft_quorum > 3):
            raise ValueError('Invalid S36 quorum')
        integer_windows = (
            self.bollinger_period, self.volume_event_bars,
            self.volume_history_bars, self.atr_period, self.retest_bars,
            self.liquidity_lookback_bars,
        )
        if min(integer_windows) < 2:
            raise ValueError('Invalid S36 bar window')
        positive = (
            self.funding_floor, self.premium_floor, self.bollinger_event_z,
            self.volume_expansion, self.fade_structure_atr,
            self.continuation_structure_atr, self.displacement_body_atr,
            self.delta_threshold, self.observation_move_atr,
            self.continuation_bollinger_z, self.retest_touch_atr,
            self.retest_acceptance_atr, self.retest_invalid_atr,
            self.retest_extension_atr, self.maximum_quote_volume_fraction,
        )
        if min(positive) <= 0:
            raise ValueError('S36 thresholds must be positive')
        ratios = (
            self.premium_fade_ratio, self.premium_continuation_ratio,
            self.premium_continuation_bar_ratio,
            self.retest_fade_premium_ratio,
            self.retest_continuation_premium_ratio,
            self.displacement_close_fraction,
        )
        if any(not 0 < value <= 1 for value in ratios):
            raise ValueError('Invalid S36 ratio')
        if not 0 < self.maximum_quote_volume_fraction <= 1:
            raise ValueError('Invalid S36 liquidity fraction')
        if len(set(self.symbol_priority)) != len(self.symbol_priority):
            raise ValueError('Duplicate S36 symbol priority')


@dataclass(frozen=True)
class EventSignal:
    symbol: str
    funding_time: pd.Timestamp
    b0_time: pd.Timestamp
    direction: int
    funding_rate: float
    funding_threshold: float
    funding_ratio: float
    event_criteria: tuple[str, ...]
    event_criteria_count: int
    pre_premium: float
    return_60m: float
    return_4h: float
    bollinger_z: float
    volume_ratio: float
    atr: float
    b0_close: float
    fade_level: float
    continuation_level: float
    setup_id: str


@dataclass(frozen=True)
class RegimeClassification:
    event: EventSignal
    regime: Regime
    classification_time: pd.Timestamp
    side: int
    breakout_level: float | None
    aggregate_delta: float | None
    soft_criteria: tuple[str, ...]
    soft_count: int
    reason: str


@dataclass(frozen=True)
class RetestCandidate:
    """Immutable S36 signal at the earliest causally executable open."""

    timestamp: pd.Timestamp
    funding_time: pd.Timestamp
    classification_time: pd.Timestamp
    retest_time: pd.Timestamp
    feature_cutoff: pd.Timestamp
    symbol: str
    side: int
    side_name: str
    regime: str
    atr: float
    structural_extreme: float
    breakout_level: float
    minimum_prior_12_quote_volume: float
    liquidity_notional_cap_usd: float
    soft_count: int
    event_criteria_count: int
    funding_ratio: float
    score: float
    funding_rate: float
    funding_threshold: float
    pre_premium: float
    aggregate_delta: float
    retest_premium: float
    event_criteria: tuple[str, ...]
    soft_criteria: tuple[str, ...]
    setup_id: str


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _validate_price_frame(frame: pd.DataFrame, label: str,
                          perpetual: bool = False) -> None:
    required = {'open', 'high', 'low', 'close'}
    if perpetual:
        required |= {'quote_volume', 'taker_buy_quote_volume'}
    if (not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
            or frame.empty or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing
            or not required.issubset(frame.columns)):
        raise ValueError(f'Invalid {label} 5m data')
    if not (frame.index.minute % 5 == 0).all() or not (frame.index.second == 0).all():
        raise ValueError(f'Off-grid {label} timestamps')
    ohlc = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    if (not np.isfinite(ohlc).all() or (ohlc <= 0).any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError(f'Malformed {label} OHLC')
    if perpetual:
        volumes = frame[['quote_volume', 'taker_buy_quote_volume']].to_numpy(dtype=float)
        if (not np.isfinite(volumes).all() or (volumes < 0).any()
                or (frame.taker_buy_quote_volume > frame.quote_volume).any()):
            raise ValueError(f'Malformed {label} volume')


def _validate_funding(funding: pd.Series, symbol: str) -> pd.Series:
    if (not isinstance(funding, pd.Series)
            or not isinstance(funding.index, pd.DatetimeIndex)
            or funding.index.tz is None or funding.index.has_duplicates
            or not funding.index.is_monotonic_increasing
            or not np.isfinite(funding.to_numpy(dtype=float)).all()):
        raise ValueError(f'Invalid {symbol} funding data')
    result = funding.astype(float).copy()
    result.index = result.index.tz_convert('UTC')
    if not (result.index.minute % 5 == 0).all() or not (result.index.second == 0).all():
        raise ValueError(f'Off-grid {symbol} funding timestamps')
    return result


def _complete_times(end_open: pd.Timestamp, bars: int) -> pd.DatetimeIndex:
    """Exactly ``bars`` consecutive bar opens ending at ``end_open``."""
    return pd.date_range(end_open - FIVE_MINUTES * (bars - 1), end_open, freq='5min')


def _values(frame: pd.DataFrame, times: pd.DatetimeIndex,
            column: str) -> np.ndarray | None:
    if not times.isin(frame.index).all():
        return None
    values = frame.loc[times, column].to_numpy(dtype=float)
    return values if np.isfinite(values).all() else None


def _event_return(perpetual: pd.DataFrame, funding_time: pd.Timestamp,
                  minutes: int) -> float:
    b0 = funding_time - FIVE_MINUTES
    older = b0 - pd.Timedelta(minutes=minutes)
    times = pd.date_range(older, b0, freq='5min')
    closes = _values(perpetual, times, 'close')
    if closes is None:
        return np.nan
    return float(closes[-1] / closes[0] - 1)


def _premium_at(streams: dict, bar_time: pd.Timestamp) -> float:
    if bar_time not in streams['mark'].index or bar_time not in streams['index'].index:
        return np.nan
    mark = float(streams['mark'].at[bar_time, 'close'])
    index = float(streams['index'].at[bar_time, 'close'])
    return mark / index - 1 if mark > 0 and index > 0 else np.nan


def _bollinger_z(perpetual: pd.DataFrame, bar_time: pd.Timestamp,
                 period: int) -> float:
    closes = _values(perpetual, _complete_times(bar_time, period), 'close')
    if closes is None:
        return np.nan
    deviation = float(np.std(closes, ddof=0))
    return float((closes[-1] - closes.mean()) / deviation) if deviation > 0 else np.nan


def _history_feature(streams: dict, funding_times: pd.DatetimeIndex,
                     feature: str, config: FundingRegimeConfig) -> np.ndarray | None:
    if feature == 'premium':
        output = np.asarray([
            _premium_at(streams, timestamp - FIVE_MINUTES)
            for timestamp in funding_times
        ], dtype=float)
    elif feature == 'return_60m':
        output = np.asarray([
            _event_return(streams['perpetual'], timestamp, 60)
            for timestamp in funding_times
        ], dtype=float)
    elif feature == 'return_4h':
        output = np.asarray([
            _event_return(streams['perpetual'], timestamp, 240)
            for timestamp in funding_times
        ], dtype=float)
    else:
        raise ValueError(f'Unknown S36 history feature {feature}')
    return output if np.isfinite(output).all() else None


def _event_signal_for_number(symbol: str, streams: dict, funding: pd.Series,
                             event_number: int, atr: pd.Series,
                             config: FundingRegimeConfig) -> EventSignal | None:
    if event_number < config.history_events:
        return None
    funding_time = funding.index[event_number]
    b0_time = funding_time - FIVE_MINUTES
    rate = float(funding.iloc[event_number])
    direction = int(np.sign(rate))
    funding_history = funding.iloc[
        event_number - config.history_events:event_number].to_numpy(dtype=float)
    if direction == 0 or len(funding_history) != config.history_events:
        return None
    funding_threshold = max(
        config.funding_floor,
        float(np.quantile(np.abs(funding_history), config.funding_quantile)),
    )
    if abs(rate) < funding_threshold:
        return None

    atr_value = float(atr.get(b0_time, np.nan))
    b0_close = float(streams['perpetual'].at[b0_time, 'close']) \
        if b0_time in streams['perpetual'].index else np.nan
    if not np.isfinite(atr_value) or atr_value <= 0 or not np.isfinite(b0_close):
        return None

    previous_times = funding.index[
        event_number - config.history_events:event_number]
    pre_premium = _premium_at(streams, b0_time)
    return_60m = _event_return(streams['perpetual'], funding_time, 60)
    return_4h = _event_return(streams['perpetual'], funding_time, 240)
    bollinger_z = _bollinger_z(
        streams['perpetual'], b0_time, config.bollinger_period)

    criteria = []
    premium_history = _history_feature(streams, previous_times, 'premium', config)
    if premium_history is not None and np.isfinite(pre_premium):
        premium_threshold = max(
            config.premium_floor,
            float(np.quantile(np.abs(premium_history), config.premium_quantile)),
        )
        if direction * pre_premium > 0 and abs(pre_premium) >= premium_threshold:
            criteria.append('premium')

    return_60m_history = _history_feature(
        streams, previous_times, 'return_60m', config)
    if return_60m_history is not None and np.isfinite(return_60m):
        threshold = float(np.quantile(
            np.abs(return_60m_history), config.return_60m_quantile))
        if direction * return_60m > 0 and abs(return_60m) >= threshold:
            criteria.append('return_60m')

    return_4h_history = _history_feature(
        streams, previous_times, 'return_4h', config)
    if return_4h_history is not None and np.isfinite(return_4h):
        threshold = float(np.quantile(
            np.abs(return_4h_history), config.return_4h_quantile))
        if direction * return_4h > 0 and abs(return_4h) >= threshold:
            criteria.append('return_4h')

    if np.isfinite(bollinger_z) and direction * bollinger_z >= config.bollinger_event_z:
        criteria.append('bollinger')

    event_times = _complete_times(b0_time, config.volume_event_bars)
    history_end = event_times[0] - FIVE_MINUTES
    history_times = _complete_times(history_end, config.volume_history_bars)
    event_volume = _values(streams['perpetual'], event_times, 'quote_volume')
    history_volume = _values(streams['perpetual'], history_times, 'quote_volume')
    volume_ratio = np.nan
    if event_volume is not None and history_volume is not None:
        baseline = float(np.median(history_volume))
        if baseline > 0:
            volume_ratio = float(event_volume.mean() / baseline)
            if volume_ratio >= config.volume_expansion:
                criteria.append('volume')

    if len(criteria) < config.event_quorum:
        return None

    fade_times = _complete_times(b0_time, 4)
    continuation_times = _complete_times(b0_time, 6)
    if (not fade_times.isin(streams['perpetual'].index).all()
            or not continuation_times.isin(streams['perpetual'].index).all()):
        return None
    if direction > 0:
        fade_level = float(streams['perpetual'].loc[fade_times, 'low'].min())
        continuation_level = float(
            streams['perpetual'].loc[continuation_times, 'high'].max())
    else:
        fade_level = float(streams['perpetual'].loc[fade_times, 'high'].max())
        continuation_level = float(
            streams['perpetual'].loc[continuation_times, 'low'].min())
    return EventSignal(
        symbol=symbol,
        funding_time=funding_time,
        b0_time=b0_time,
        direction=direction,
        funding_rate=rate,
        funding_threshold=funding_threshold,
        funding_ratio=abs(rate) / funding_threshold,
        event_criteria=tuple(criteria),
        event_criteria_count=len(criteria),
        pre_premium=float(pre_premium),
        return_60m=float(return_60m),
        return_4h=float(return_4h),
        bollinger_z=float(bollinger_z),
        volume_ratio=float(volume_ratio),
        atr=atr_value,
        b0_close=b0_close,
        fade_level=fade_level,
        continuation_level=continuation_level,
        setup_id=f'S36|{symbol}|{funding_time.isoformat()}',
    )


def build_event_signals(markets: dict,
                        config: FundingRegimeConfig | None = None
                        ) -> list[EventSignal]:
    """Return all pre-qualified funding events; no post-event PnL is read."""
    config = config or FundingRegimeConfig()
    config.validate()
    signals = []
    for symbol, streams in markets.items():
        if symbol not in config.symbol_priority:
            raise ValueError(f'No frozen S36 priority for {symbol}')
        required = {'perpetual', 'mark', 'index', 'funding'}
        if not required.issubset(streams):
            raise ValueError(f'Invalid S36 streams for {symbol}')
        _validate_price_frame(streams['perpetual'], f'{symbol} perpetual', True)
        _validate_price_frame(streams['mark'], f'{symbol} mark')
        _validate_price_frame(streams['index'], f'{symbol} index')
        funding = _validate_funding(streams['funding'], symbol)
        atr = wilder_atr(streams['perpetual'], config.atr_period)
        for number in range(config.history_events, len(funding)):
            signal = _event_signal_for_number(
                symbol, streams, funding, number, atr, config)
            if signal is not None:
                signals.append(signal)
    priority = {symbol: rank for rank, symbol in enumerate(config.symbol_priority)}
    return sorted(signals, key=lambda event: (
        event.funding_time, -event.event_criteria_count, -event.funding_ratio,
        priority[event.symbol], event.symbol,
    ))


def _bar_delta(perpetual: pd.DataFrame, times: pd.DatetimeIndex
               ) -> tuple[np.ndarray, float] | None:
    quote = _values(perpetual, times, 'quote_volume')
    taker = _values(perpetual, times, 'taker_buy_quote_volume')
    if quote is None or taker is None or (quote <= 0).any():
        return None
    bar_delta = (2 * taker - quote) / quote
    aggregate = float((2 * taker.sum() - quote.sum()) / quote.sum())
    return bar_delta, aggregate


def classify_event(streams: dict, event: EventSignal,
                   config: FundingRegimeConfig | None = None
                   ) -> RegimeClassification:
    """Classify FADE/CONTINUATION only after all three observation bars."""
    config = config or FundingRegimeConfig()
    config.validate()
    classification_time = event.funding_time + pd.Timedelta(minutes=15)
    observation_times = pd.date_range(
        event.funding_time, periods=3, freq='5min')
    perpetual = streams['perpetual']
    required_frames = (perpetual, streams['mark'], streams['index'])
    if any(not observation_times.isin(frame.index).all() for frame in required_frames):
        return RegimeClassification(
            event, Regime.NO_TRADE, classification_time, 0, None, None,
            (), 0, 'missing_observation_data')
    delta_result = _bar_delta(perpetual, observation_times)
    premiums = np.asarray([
        _premium_at(streams, timestamp) for timestamp in observation_times
    ], dtype=float)
    if delta_result is None or not np.isfinite(premiums).all():
        return RegimeClassification(
            event, Regime.NO_TRADE, classification_time, 0, None, None,
            (), 0, 'missing_observation_data')
    deltas, aggregate_delta = delta_result
    closes = perpetual.loc[observation_times, 'close'].to_numpy(dtype=float)
    opens = perpetual.loc[observation_times, 'open'].to_numpy(dtype=float)
    highs = perpetual.loc[observation_times, 'high'].to_numpy(dtype=float)
    lows = perpetual.loc[observation_times, 'low'].to_numpy(dtype=float)
    direction = event.direction
    atr = event.atr

    fade_side = -direction
    fade_distance = fade_side * (closes - event.fade_level)
    fade_broke = bool((fade_distance >= config.fade_structure_atr * atr).any())
    fade_held = bool(fade_distance[-1] >= config.fade_structure_atr * atr)
    fade_structure = fade_broke and fade_held
    fade_premium = bool(
        abs(premiums[-1]) <= config.premium_fade_ratio * abs(event.pre_premium)
        and abs(premiums[-1]) <= abs(premiums[-2]))

    fade_soft = []
    ranges = highs - lows
    bodies = closes - opens
    terminal = np.divide(
        closes - lows, ranges, out=np.full(3, .5), where=ranges > 0)
    displacement = (
        (fade_side * bodies >= config.displacement_body_atr * atr)
        & ((terminal >= 1 - config.displacement_close_fraction)
           if fade_side > 0 else
           (terminal <= config.displacement_close_fraction)))
    if displacement.any():
        fade_soft.append('displacement')
    if (direction * aggregate_delta <= -config.delta_threshold
            and int((direction * deltas < 0).sum()) >= 2):
        fade_soft.append('delta')
    if fade_side * (closes[-1] - event.b0_close) >= config.observation_move_atr * atr:
        fade_soft.append('price_move')
    fade_qualified = (
        fade_structure and fade_premium
        and len(fade_soft) >= config.soft_quorum)

    continuation_side = direction
    continuation_distance = continuation_side * (
        closes - event.continuation_level)
    continuation_broke = bool((
        continuation_distance >= config.continuation_structure_atr * atr).any())
    continuation_held = bool(
        continuation_distance[-1] >= config.continuation_structure_atr * atr)
    continuation_premium = bool(
        direction * premiums[-1]
        >= config.premium_continuation_ratio * abs(event.pre_premium)
        and int((direction * premiums
                 >= config.premium_continuation_bar_ratio
                 * abs(event.pre_premium)).sum()) >= 2)

    continuation_soft = []
    if direction * (closes[-1] - event.b0_close) >= config.observation_move_atr * atr:
        continuation_soft.append('price_move')
    if (direction * aggregate_delta >= config.delta_threshold
            and int((direction * deltas > 0).sum()) >= 2):
        continuation_soft.append('delta')
    return_4h = _event_return(perpetual, classification_time, 240)
    b3_time = observation_times[-1]
    b3_bollinger = _bollinger_z(
        perpetual, b3_time, config.bollinger_period)
    if (np.isfinite(return_4h) and direction * return_4h > 0
            and np.isfinite(b3_bollinger)
            and direction * b3_bollinger >= config.continuation_bollinger_z):
        continuation_soft.append('trend_bollinger')
    continuation_qualified = (
        not fade_structure and continuation_broke and continuation_held
        and continuation_premium
        and len(continuation_soft) >= config.soft_quorum)

    if fade_qualified == continuation_qualified:
        reason = 'ambiguous_states' if fade_qualified else 'no_state_qualified'
        return RegimeClassification(
            event, Regime.NO_TRADE, classification_time, 0, None,
            aggregate_delta, (), 0, reason)
    if fade_qualified:
        return RegimeClassification(
            event, Regime.FADE, classification_time, fade_side,
            event.fade_level, aggregate_delta, tuple(fade_soft),
            len(fade_soft), 'qualified')
    return RegimeClassification(
        event, Regime.CONTINUATION, classification_time, continuation_side,
        event.continuation_level, aggregate_delta, tuple(continuation_soft),
        len(continuation_soft), 'qualified')


def find_retest_candidate(streams: dict, classification: RegimeClassification,
                          config: FundingRegimeConfig | None = None
                          ) -> RetestCandidate | None:
    """Return the first causal retest candidate, or ``None`` on veto/expiry."""
    config = config or FundingRegimeConfig()
    config.validate()
    if classification.regime is Regime.NO_TRADE:
        return None
    event = classification.event
    perpetual = streams['perpetual']
    level = float(classification.breakout_level)
    side = classification.side
    atr = event.atr
    observation_times = pd.date_range(
        event.funding_time, periods=3, freq='5min')
    lows_seen = list(perpetual.loc[observation_times, 'low'].to_numpy(dtype=float))
    highs_seen = list(perpetual.loc[observation_times, 'high'].to_numpy(dtype=float))

    retest_times = pd.date_range(
        classification.classification_time,
        periods=config.retest_bars, freq='5min')
    for retest_time in retest_times:
        if (retest_time not in perpetual.index
                or retest_time not in streams['mark'].index
                or retest_time not in streams['index'].index):
            return None
        row = perpetual.loc[retest_time]
        low, high = float(row.low), float(row.high)
        open_, close = float(row.open), float(row.close)
        lows_seen.append(low)
        highs_seen.append(high)
        premium = _premium_at(streams, retest_time)
        if not np.isfinite(premium):
            return None

        # A close on the invalid side takes precedence over later acceptance.
        if side * (close - level) <= -config.retest_invalid_atr * atr:
            return None
        touch = (
            high >= level - config.retest_touch_atr * atr
            and low <= level + config.retest_touch_atr * atr)
        acceptance = (
            side * (close - level) >= config.retest_acceptance_atr * atr
            and side * (close - open_) > 0)
        if classification.regime is Regime.FADE:
            premium_ok = (
                abs(premium)
                <= config.retest_fade_premium_ratio * abs(event.pre_premium))
        else:
            premium_ok = (
                event.direction * premium
                >= config.retest_continuation_premium_ratio
                * abs(event.pre_premium))
        if touch and acceptance and premium_ok:
            entry_time = retest_time + FIVE_MINUTES
            if entry_time not in perpetual.index:
                return None
            liquidity_times = _complete_times(
                entry_time - FIVE_MINUTES, config.liquidity_lookback_bars)
            liquidity = _values(perpetual, liquidity_times, 'quote_volume')
            if liquidity is None or (liquidity <= 0).any():
                return None
            minimum_liquidity = float(liquidity.min())
            structural_extreme = (
                min(lows_seen) if side > 0 else max(highs_seen))
            # Numeric score preserves the mandated ordering, but consumers
            # should still sort on the three explicit fields.
            score = (
                classification.soft_count * 1000
                + event.event_criteria_count * 100
                + min(event.funding_ratio, 99.999999))
            return RetestCandidate(
                timestamp=entry_time,
                funding_time=event.funding_time,
                classification_time=classification.classification_time,
                retest_time=retest_time,
                feature_cutoff=entry_time,
                symbol=event.symbol,
                side=side,
                side_name='LONG' if side > 0 else 'SHORT',
                regime=classification.regime.value,
                atr=atr,
                structural_extreme=float(structural_extreme),
                breakout_level=level,
                minimum_prior_12_quote_volume=minimum_liquidity,
                liquidity_notional_cap_usd=(
                    minimum_liquidity * config.maximum_quote_volume_fraction),
                soft_count=classification.soft_count,
                event_criteria_count=event.event_criteria_count,
                funding_ratio=event.funding_ratio,
                score=float(score),
                funding_rate=event.funding_rate,
                funding_threshold=event.funding_threshold,
                pre_premium=event.pre_premium,
                aggregate_delta=float(classification.aggregate_delta),
                retest_premium=float(premium),
                event_criteria=event.event_criteria,
                soft_criteria=classification.soft_criteria,
                setup_id=(
                    f'{event.setup_id}|{classification.regime.value}'),
            )
        # Extension only expires an event that has not produced a valid retest.
        if abs(close - level) > config.retest_extension_atr * atr:
            return None
    return None


def build_funding_regime_candidates(
        markets: dict, start, end,
        config: FundingRegimeConfig | None = None) -> list[RetestCandidate]:
    """Build immutable S36 entry candidates inside half-open ``[start, end)``."""
    config = config or FundingRegimeConfig()
    config.validate()
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError('S36 range must have start before end')
    candidates = []
    for event in build_event_signals(markets, config):
        classification = classify_event(markets[event.symbol], event, config)
        candidate = find_retest_candidate(
            markets[event.symbol], classification, config)
        if candidate is not None and start <= candidate.timestamp < end:
            candidates.append(candidate)
    priority = {symbol: rank for rank, symbol in enumerate(config.symbol_priority)}
    return sorted(candidates, key=lambda row: (
        row.timestamp, -row.soft_count, -row.event_criteria_count,
        -row.funding_ratio, priority[row.symbol], row.symbol,
    ))

