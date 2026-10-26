from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from backtest.funding_regime_switch import (
    EventSignal,
    FundingRegimeConfig,
    Regime,
    build_event_signals,
    classify_event,
    find_retest_candidate,
)


def _set_bar(frame, timestamp, *, open_, high, low, close,
             delta=None, quote_volume=1_000.0):
    frame.loc[timestamp, ['open', 'high', 'low', 'close']] = [
        open_, high, low, close,
    ]
    if 'quote_volume' in frame:
        frame.at[timestamp, 'quote_volume'] = quote_volume
    if delta is not None:
        frame.at[timestamp, 'taker_buy_quote_volume'] = (
            quote_volume * (1 + delta) / 2)


def _set_premium(streams, timestamp, premium):
    reference = 100.0
    streams['index'].loc[timestamp, ['open', 'high', 'low', 'close']] = [
        reference, reference * 1.0001, reference * .9999, reference,
    ]
    mark = reference * (1 + premium)
    streams['mark'].loc[timestamp, ['open', 'high', 'low', 'close']] = [
        mark, mark * 1.0001, mark * .9999, mark,
    ]


def _streams():
    index = pd.date_range(
        '2025-12-31 18:00', '2026-01-01 02:00', freq='5min', tz='UTC')
    perpetual = pd.DataFrame({
        'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.0,
        'quote_volume': 1_000.0, 'taker_buy_quote_volume': 500.0,
    }, index=index)
    price = perpetual[['open', 'high', 'low', 'close']].copy()
    return {
        'perpetual': perpetual,
        'mark': price.copy(),
        'index': price.copy(),
        'funding': pd.Series(dtype=float,
                             index=pd.DatetimeIndex([], tz='UTC')),
    }


def _event(direction=1):
    funding_time = pd.Timestamp('2026-01-01 00:00', tz='UTC')
    return EventSignal(
        symbol='DOGEUSDT', funding_time=funding_time,
        b0_time=funding_time - pd.Timedelta(minutes=5),
        direction=direction, funding_rate=direction * .001,
        funding_threshold=.0005, funding_ratio=2.0,
        event_criteria=('premium', 'return_60m', 'bollinger'),
        event_criteria_count=3, pre_premium=direction * .001,
        return_60m=direction * .02, return_4h=direction * .03,
        bollinger_z=direction * 2.0, volume_ratio=2.0,
        atr=1.0, b0_close=100.0,
        fade_level=99.0 if direction > 0 else 101.0,
        continuation_level=101.0 if direction > 0 else 99.0,
        setup_id=f'S36|DOGEUSDT|{funding_time.isoformat()}',
    )


def _qualifying_fade():
    streams = _streams()
    times = pd.date_range('2026-01-01 00:00', periods=3, freq='5min', tz='UTC')
    _set_bar(streams['perpetual'], times[0], open_=100.0, high=100.1,
             low=98.7, close=98.8, delta=-.20)
    _set_bar(streams['perpetual'], times[1], open_=98.8, high=98.9,
             low=98.5, close=98.6, delta=-.20)
    _set_bar(streams['perpetual'], times[2], open_=98.6, high=98.8,
             low=98.5, close=98.7, delta=.05)
    for timestamp, premium in zip(times, (.0006, .00045, .0004)):
        _set_premium(streams, timestamp, premium)
    classification = classify_event(streams, _event())
    assert classification.regime is Regime.FADE
    return streams, classification


def test_false_one_bar_reversal_is_no_trade_after_three_bar_reclaim():
    streams = _streams()
    times = pd.date_range('2026-01-01 00:00', periods=3, freq='5min', tz='UTC')
    _set_bar(streams['perpetual'], times[0], open_=100.0, high=100.1,
             low=98.7, close=98.8, delta=-.20)
    _set_bar(streams['perpetual'], times[1], open_=98.8, high=99.3,
             low=98.7, close=99.2, delta=-.20)
    _set_bar(streams['perpetual'], times[2], open_=99.2, high=99.4,
             low=99.1, close=99.3, delta=.05)
    for timestamp, premium in zip(times, (.0006, .00045, .0004)):
        _set_premium(streams, timestamp, premium)

    result = classify_event(streams, _event())

    assert result.regime is Regime.NO_TRADE
    assert result.classification_time == pd.Timestamp(
        '2026-01-01 00:15', tz='UTC')
    assert result.reason == 'no_state_qualified'


def test_fade_requires_structure_premium_and_two_soft_confirmations():
    streams, result = _qualifying_fade()

    assert result.side == -1
    assert result.breakout_level == pytest.approx(99.0)
    assert result.soft_count == 3
    assert result.soft_criteria == ('displacement', 'delta', 'price_move')
    assert result.aggregate_delta == pytest.approx(-.11666666666666667)

    # One missing confirmation source invalidates classification rather than
    # being filled from its neighbors.
    missing = {key: value.copy() for key, value in streams.items()}
    missing['mark'] = missing['mark'].drop(
        pd.Timestamp('2026-01-01 00:05', tz='UTC'))
    invalid = classify_event(missing, _event())
    assert invalid.regime is Regime.NO_TRADE
    assert invalid.reason == 'missing_observation_data'


def test_continuation_requires_breakout_persistent_premium_and_soft_quorum():
    streams = _streams()
    times = pd.date_range('2026-01-01 00:00', periods=3, freq='5min', tz='UTC')
    _set_bar(streams['perpetual'], times[0], open_=100.0, high=101.3,
             low=99.9, close=101.2, delta=.20)
    _set_bar(streams['perpetual'], times[1], open_=101.2, high=101.5,
             low=101.1, close=101.4, delta=.20)
    _set_bar(streams['perpetual'], times[2], open_=101.4, high=101.5,
             low=101.2, close=101.3, delta=-.05)
    for timestamp, premium in zip(times, (.0007, .0008, .0008)):
        _set_premium(streams, timestamp, premium)

    result = classify_event(streams, _event())

    assert result.regime is Regime.CONTINUATION
    assert result.side == 1
    assert result.breakout_level == pytest.approx(101.0)
    assert result.soft_count >= 2
    assert {'price_move', 'delta'}.issubset(result.soft_criteria)


def test_retest_uses_first_completed_bar_and_enters_only_next_open():
    streams, classification = _qualifying_fade()
    retest = pd.Timestamp('2026-01-01 00:15', tz='UTC')
    _set_bar(streams['perpetual'], retest, open_=99.05, high=99.08,
             low=98.7, close=98.85, delta=-.10)
    _set_premium(streams, retest, .0005)

    candidate = find_retest_candidate(streams, classification)

    entry = pd.Timestamp('2026-01-01 00:20', tz='UTC')
    assert candidate is not None
    assert candidate.retest_time == retest
    assert candidate.timestamp == entry
    assert candidate.feature_cutoff == entry
    assert candidate.timestamp > candidate.classification_time
    assert candidate.side == -1
    assert candidate.side_name == 'SHORT'
    assert candidate.regime == 'FADE'
    assert candidate.structural_extreme == pytest.approx(100.1)
    assert candidate.breakout_level == pytest.approx(99.0)
    assert candidate.minimum_prior_12_quote_volume == pytest.approx(1_000.0)
    assert candidate.liquidity_notional_cap_usd == pytest.approx(1.0)

    # Bars after the feature cutoff cannot alter the already-issued signal.
    later = pd.Timestamp('2026-01-01 00:25', tz='UTC')
    _set_bar(streams['perpetual'], later, open_=100.0, high=200.0,
             low=50.0, close=150.0, delta=.90)
    assert find_retest_candidate(streams, classification) == candidate


def test_retest_can_wait_but_expires_on_pre_retest_extension():
    streams, classification = _qualifying_fade()
    first = pd.Timestamp('2026-01-01 00:15', tz='UTC')
    second = first + pd.Timedelta(minutes=5)
    _set_bar(streams['perpetual'], first, open_=98.6, high=98.8,
             low=98.4, close=98.5, delta=-.10)
    _set_premium(streams, first, .0005)
    _set_bar(streams['perpetual'], second, open_=99.05, high=99.08,
             low=98.7, close=98.85, delta=-.10)
    _set_premium(streams, second, .0005)

    waited = find_retest_candidate(streams, classification)
    assert waited is not None
    assert waited.retest_time == second
    assert waited.timestamp == second + pd.Timedelta(minutes=5)

    expired_streams, expired_classification = _qualifying_fade()
    _set_bar(expired_streams['perpetual'], first, open_=97.4, high=97.5,
             low=96.9, close=97.0, delta=-.10)
    _set_premium(expired_streams, first, .0005)
    assert find_retest_candidate(expired_streams, expired_classification) is None


def _event_market():
    index = pd.date_range(
        '2025-12-20', '2026-01-01 01:00', freq='5min', tz='UTC')
    perpetual = pd.DataFrame({
        'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.0,
        'quote_volume': 100.0, 'taker_buy_quote_volume': 50.0,
    }, index=index)
    price = perpetual[['open', 'high', 'low', 'close']].copy()
    streams = {
        'perpetual': perpetual, 'mark': price.copy(), 'index': price.copy(),
    }
    funding_times = pd.DatetimeIndex([
        '2025-12-29', '2025-12-30', '2025-12-31', '2026-01-01',
    ], tz='UTC')
    streams['funding'] = pd.Series(
        [.00005, .00006, .00007, .00020], index=funding_times)
    for timestamp in funding_times[:-1]:
        _set_premium(streams, timestamp - pd.Timedelta(minutes=5), .00005)
    b0 = funding_times[-1] - pd.Timedelta(minutes=5)
    _set_premium(streams, b0, .001)
    _set_bar(perpetual, b0, open_=100.0, high=120.1,
             low=99.9, close=120.0, delta=.20, quote_volume=200.0)
    volume_times = pd.date_range(b0 - pd.Timedelta(minutes=55), b0, freq='5min')
    perpetual.loc[volume_times, 'quote_volume'] = 200.0
    perpetual.loc[volume_times, 'taker_buy_quote_volume'] = 100.0
    return {'DOGEUSDT': streams}


def test_event_quorum_is_causal_and_funding_threshold_excludes_current_event():
    market = _event_market()
    config = FundingRegimeConfig(
        history_events=3, atr_period=3, volume_history_bars=24)

    events = build_event_signals(market, config)

    assert len(events) == 1
    event = events[0]
    assert event.funding_time == pd.Timestamp('2026-01-01', tz='UTC')
    assert event.funding_threshold == pytest.approx(.0001)
    assert event.event_criteria_count >= 3
    assert {'premium', 'bollinger', 'volume'}.issubset(event.event_criteria)

    # Neither the current funding magnitude nor the first post-event bar can
    # contaminate the event's own threshold/features.
    market['DOGEUSDT']['funding'].iloc[-1] = .02
    after = event.funding_time
    _set_bar(market['DOGEUSDT']['perpetual'], after, open_=50.0,
             high=50.1, low=49.9, close=50.0, delta=-.90)
    changed = build_event_signals(market, config)[0]
    assert changed.funding_threshold == event.funding_threshold
    assert changed.b0_close == event.b0_close
    assert changed.event_criteria == event.event_criteria

