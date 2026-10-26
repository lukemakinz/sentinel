from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from backtest.funding_regime_switch import RetestCandidate
from backtest.funding_regime_switch_portfolio import (
    FRSCosts,
    FRSPortfolioConfig,
    simulate_funding_regime_switch_portfolio,
)


def _market(start, end, symbol='ETHUSDT'):
    index = pd.date_range(start, end, freq='5min', inclusive='left', tz='UTC')
    frame = pd.DataFrame({
        'open': 100.0,
        'high': 100.2,
        'low': 99.8,
        'close': 100.0,
        'quote_volume': 1_000_000.0,
    }, index=index)
    return {symbol: {
        'perpetual': frame.copy(),
        'mark': frame.copy(),
        'index': frame.copy(),
        'funding': pd.Series(
            dtype=float, index=pd.DatetimeIndex([], tz='UTC')),
    }}


def _candidate(timestamp, *, number=1, symbol='ETHUSDT', side=1,
               regime='CONTINUATION', atr=.5, structural_extreme=None):
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize('UTC')
    if structural_extreme is None:
        structural_extreme = 99.8 if side == 1 else 100.2
    return RetestCandidate(
        timestamp=timestamp,
        funding_time=timestamp - pd.Timedelta(minutes=30),
        classification_time=timestamp - pd.Timedelta(minutes=15),
        retest_time=timestamp - pd.Timedelta(minutes=5),
        feature_cutoff=timestamp,
        symbol=symbol,
        side=side,
        side_name='LONG' if side == 1 else 'SHORT',
        regime=regime,
        atr=atr,
        structural_extreme=structural_extreme,
        breakout_level=100.0,
        minimum_prior_12_quote_volume=1_000_000.0,
        liquidity_notional_cap_usd=1_000.0,
        soft_count=2,
        event_criteria_count=3,
        funding_ratio=1.1,
        score=6.1,
        funding_rate=.0002,
        funding_threshold=.0001,
        pre_premium=.0003,
        aggregate_delta=.2,
        retest_premium=.0002,
        event_criteria=('premium', '60m', 'bollinger'),
        soft_criteria=('move', 'delta'),
        setup_id=f'S36|{symbol}|{number}',
    )


def _zero_cost_config(**changes):
    config = FRSPortfolioConfig(
        costs=FRSCosts(
            taker_fee_bps_per_side=0,
            slippage_bps_per_side=0,
        )
    )
    return replace(config, **changes)


def _set_bar(frame, timestamp, *, open_=None, high=None, low=None, close=None):
    open_ = float(frame.at[timestamp, 'open'] if open_ is None else open_)
    close = float(frame.at[timestamp, 'close'] if close is None else close)
    high = max(open_, close) if high is None else float(high)
    low = min(open_, close) if low is None else float(low)
    frame.loc[timestamp, ['open', 'high', 'low', 'close']] = [
        open_, high, low, close,
    ]


def test_structural_stop_widens_to_frozen_minimum_and_size_rounds_down():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=10)
    markets = _market(start, end)
    config = FRSPortfolioConfig()
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end, config)
    trade = result['trades'][0]
    minimum = max(
        .60 * .5, .006 * trade['entry_fill'],
        3 * .01,
    )
    maximum = min(2.5 * .5, .03 * trade['entry_fill'])
    assert trade['price_r'] >= minimum - 1e-12
    assert trade['price_r'] <= maximum + .01 + 1e-12
    assert trade['quantity'] / .001 == pytest.approx(
        np.floor(trade['quantity'] / .001 + 1e-12))
    assert trade['initial_risk_usd'] <= .50 + 1e-12
    assert trade['notional_usd'] <= .50 * 250 + 1e-12
    assert trade['initial_margin_usd'] == pytest.approx(
        trade['notional_usd'] / 2)


@pytest.mark.parametrize(
    ('candidate', 'diagnostic'),
    [
        (_candidate('2026-01-01', structural_extreme=96.0),
         'blocked_structural_stop_too_wide'),
        (_candidate('2026-01-01', atr=.1), 'blocked_stop_band_empty'),
    ],
)
def test_invalid_structural_stop_geometry_is_vetoed(candidate, diagnostic):
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=10)
    result = simulate_funding_regime_switch_portfolio(
        _market(start, end), [candidate], start, end)
    assert result['trades'] == []
    assert result['summary']['diagnostics'][diagnostic] == 1


def test_stop_wins_when_stop_partial_and_hard_target_share_entry_bar():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=10)
    markets = _market(start, end)
    _set_bar(
        markets['ETHUSDT']['perpetual'], start,
        open_=100, high=103, low=99, close=100,
    )
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    assert trade['pnl'] < 0
    assert trade['partial_taken'] is False
    assert [exit_['reason'] for exit_ in trade['exits']] == ['STOP']


def test_partial_then_cost_breakeven_is_active_only_on_next_bar():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=15)
    markets = _market(start, end)
    first, second = start, start + pd.Timedelta(minutes=5)
    _set_bar(
        markets['ETHUSDT']['perpetual'], first,
        open_=100, high=100.85, low=99.8, close=100.75,
    )
    _set_bar(
        markets['ETHUSDT']['perpetual'], second,
        open_=100.6, high=100.65, low=100.2, close=100.3,
    )
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    assert trade['partial_enabled'] is True
    assert trade['partial_taken'] is True
    assert [exit_['reason'] for exit_ in trade['exits']] == [
        'PARTIAL_1R', 'STOP',
    ]
    assert trade['stop_updates'][0]['active_from'] == str(second)
    assert trade['final_stop'] > trade['entry_fill']
    assert trade['pnl'] > 0


def test_small_executable_entry_does_not_split_children_below_min_notional():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=15)
    markets = _market(start, end)
    first, second = start, start + pd.Timedelta(minutes=5)
    candidate = _candidate(start, atr=1.0, structural_extreme=98.4)
    _set_bar(
        markets['ETHUSDT']['perpetual'], first,
        open_=100, high=102.2, low=99.0, close=102.0,
    )
    _set_bar(
        markets['ETHUSDT']['perpetual'], second,
        open_=101.0, high=101.1, low=100.0, close=100.5,
    )
    result = simulate_funding_regime_switch_portfolio(
        markets, [candidate], start, end)
    trade = result['trades'][0]
    assert 20 <= trade['notional_usd'] < 40
    assert trade['partial_enabled'] is False
    assert trade['partial_taken'] is False
    assert result['summary']['diagnostics']['partial_not_executable'] == 1
    assert len(trade['exits']) == 1


def test_trailing_stop_ratchets_and_never_loosens():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=20)
    markets = _market(start, end)
    bars = [
        (start, 100, 101.2, 99.8, 101.1),
        (start + pd.Timedelta(minutes=5), 101.1, 101.25, 100.7, 100.9),
        (start + pd.Timedelta(minutes=10), 100.9, 101.3, 100.6, 100.8),
    ]
    for timestamp, open_, high, low, close in bars:
        _set_bar(
            markets['ETHUSDT']['perpetual'], timestamp,
            open_=open_, high=high, low=low, close=close,
        )
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    updates = trade['stop_updates']
    assert trade['reached_1_5r'] is True
    assert any(update['reason'] == 'TRAIL_1P5R' for update in updates)
    stops = [trade['initial_stop']] + [
        update['new_stop'] for update in updates]
    assert stops == sorted(stops)


def test_stagnation_exits_at_next_open_after_sixty_minutes():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=70)
    markets = _market(start, end)
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    assert trade['reason'] == 'STAGNATION_60M'
    assert trade['closed_at'] == str(start + pd.Timedelta(minutes=60))
    assert trade['reached_1r'] is False


def test_unreached_one_r_uses_120_minute_time_exit_not_stagnation():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=130)
    markets = _market(start, end)
    frame = markets['ETHUSDT']['perpetual']
    for timestamp in frame.index:
        if timestamp == start:
            _set_bar(
                frame, timestamp,
                open_=100, high=100.5, low=99.8, close=100.4,
            )
        else:
            _set_bar(
                frame, timestamp,
                open_=100.4, high=100.5, low=100.2, close=100.4,
            )
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    assert .5 <= trade['exits'][0]['raw_price'] / 100  # sanity on recorded fill
    assert trade['reason'] == 'TIME_120M'
    assert trade['closed_at'] == str(start + pd.Timedelta(minutes=120))


def test_reached_one_r_uses_180_minute_time_exit_and_books_later_funding():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=190)
    markets = _market(start, end)
    frame = markets['ETHUSDT']['perpetual']
    _set_bar(
        frame, start,
        open_=100, high=100.85, low=99.8, close=100.6,
    )
    for timestamp in frame.index[1:]:
        _set_bar(
            frame, timestamp,
            open_=100.6, high=100.8, low=100.5, close=100.6,
        )
    later_funding = start + pd.Timedelta(minutes=10)
    markets['ETHUSDT']['funding'].loc[later_funding] = .001
    result = simulate_funding_regime_switch_portfolio(
        markets, [_candidate(start)], start, end)
    trade = result['trades'][0]
    assert trade['reason'] == 'TIME_180M'
    assert trade['closed_at'] == str(start + pd.Timedelta(minutes=180))
    assert trade['partial_taken'] is True
    assert trade['funding_pnl'] < 0  # the remaining LONG pays positive funding


def test_daily_realised_loss_stop_blocks_later_same_day_candidate():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=30)
    markets = _market(start, end)
    config = _zero_cost_config(daily_loss_fraction=.001)
    second = start + pd.Timedelta(minutes=10)
    for timestamp in (start, second):
        _set_bar(
            markets['ETHUSDT']['perpetual'], timestamp,
            open_=100, high=100.1, low=99.0, close=99.5,
        )
    result = simulate_funding_regime_switch_portfolio(
        markets,
        [_candidate(start), _candidate(second, number=2)],
        start,
        end,
        config,
    )
    assert result['summary']['diagnostics']['entries'] == 1
    assert result['summary']['diagnostics']['daily_loss_stops'] == 1
    assert result['summary']['diagnostics']['blocked_risk_halt_or_capital'] == 1


def test_weekly_realised_loss_stop_survives_daily_reset():
    start = pd.Timestamp('2026-01-05', tz='UTC')  # Monday
    third = start + pd.Timedelta(days=2)
    end = third + pd.Timedelta(minutes=30)
    markets = _market(start, end)
    config = _zero_cost_config(
        daily_loss_fraction=.0015,
        weekly_loss_fraction=.0025,
    )
    times = [start + pd.Timedelta(days=offset) for offset in range(3)]
    for timestamp in times:
        _set_bar(
            markets['ETHUSDT']['perpetual'], timestamp,
            open_=100, high=100.1, low=99.0, close=99.5,
        )
    candidates = [
        _candidate(timestamp, number=number)
        for number, timestamp in enumerate(times, 1)
    ]
    result = simulate_funding_regime_switch_portfolio(
        markets, candidates, start, end, config)
    assert result['summary']['diagnostics']['entries'] == 2
    assert result['summary']['diagnostics']['weekly_loss_stops'] == 1
    assert result['summary']['diagnostics']['blocked_risk_halt_or_capital'] == 1


def test_gap_loss_triggers_permanent_mark_to_market_drawdown_kill():
    start = pd.Timestamp('2026-01-01', tz='UTC')
    end = start + pd.Timedelta(minutes=30)
    markets = _market(start, end)
    gap = start + pd.Timedelta(minutes=5)
    later = start + pd.Timedelta(minutes=10)
    _set_bar(
        markets['ETHUSDT']['perpetual'], start,
        open_=100, high=100.2, low=99.8, close=100,
    )
    _set_bar(
        markets['ETHUSDT']['perpetual'], gap,
        open_=80, high=80.2, low=79.8, close=80,
    )
    result = simulate_funding_regime_switch_portfolio(
        markets,
        [_candidate(start), _candidate(later, number=2)],
        start,
        end,
    )
    assert result['trades'][0]['reason'] == 'STOP_GAP'
    assert result['summary']['risk_fail'] is True
    assert result['summary']['diagnostics']['drawdown_kills'] == 1
    assert result['summary']['diagnostics']['blocked_risk_halt_or_capital'] == 1
