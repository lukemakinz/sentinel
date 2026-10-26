from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import backtest.post_funding_exhaustion as pfe
from backtest.post_funding_exhaustion import (
    PFECosts,
    PFEConfig,
    build_post_funding_candidates,
    simulate_post_funding_exhaustion,
)


def _set_bar(frame, timestamp, *, open_=None, high=None, low=None, close=None):
    open_ = float(frame.at[timestamp, 'open'] if open_ is None else open_)
    close = float(frame.at[timestamp, 'close'] if close is None else close)
    high = max(open_, close) * 1.0001 if high is None else float(high)
    low = min(open_, close) * .9999 if low is None else float(low)
    frame.loc[timestamp, ['open', 'high', 'low', 'close']] = [
        open_, high, low, close,
    ]


def _qualifying_market(symbol='DOGEUSDT', sign=1, price=.37):
    index = pd.date_range(
        '2025-12-31 13:00', '2026-01-01 04:00', freq='5min', tz='UTC')
    base = pd.DataFrame({
        'open': price, 'high': price * 1.0001,
        'low': price * .9999, 'close': price, 'quote_volume': 1_000_000.0,
    }, index=index)
    perpetual, mark, index_price = base.copy(), base.copy(), base.copy()
    events = pd.DatetimeIndex([
        '2025-12-31 15:00', '2025-12-31 18:00',
        '2025-12-31 21:00', '2026-01-01 00:00',
    ], tz='UTC')
    returns = [.001, .002, .003, .020]
    for event, event_return in zip(events, returns):
        older, newer = event - pd.Timedelta(minutes=65), event - pd.Timedelta(minutes=5)
        _set_bar(perpetual, older, close=price)
        _set_bar(perpetual, newer, close=price * (1 + sign * event_return))
    before, after = events[-1] - pd.Timedelta(minutes=5), events[-1]
    pre_close = float(perpetual.at[before, 'close'])
    _set_bar(perpetual, after, close=pre_close * (1 - sign * .005))
    _set_bar(mark, before, close=price * (1 + sign * .001))
    _set_bar(index_price, before, close=price)
    _set_bar(mark, after, close=price * (1 + sign * .0004))
    _set_bar(index_price, after, close=price)
    funding = pd.Series(
        sign * np.asarray([.0001, .0002, .0003, .001]), index=events)
    return {
        symbol: {
            'perpetual': perpetual, 'mark': mark,
            'index': index_price, 'funding': funding,
        }
    }


def _small_config(**changes):
    config = PFEConfig(
        history_events=3, atr_period=14,
        costs=PFECosts(taker_fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    return replace(config, **changes)


def test_rolling_thresholds_exclude_current_event_and_entry_is_delayed():
    market = _qualifying_market()
    config = _small_config()
    start = pd.Timestamp('2026-01-01 00:05', tz='UTC')
    candidates = build_post_funding_candidates(
        market, start, start + pd.Timedelta(hours=1), config)
    assert len(candidates) == 1
    first = candidates[0]
    assert first['funding_time'] == pd.Timestamp('2026-01-01 00:00', tz='UTC')
    assert first['confirmation_time'] == start
    assert first['timestamp'] == start
    assert first['feature_cutoff'] == start
    assert first['funding_threshold'] == pytest.approx(.0005)

    # Changing the classified event cannot move its own trailing threshold.
    market['DOGEUSDT']['funding'].iloc[-1] = .02
    changed = build_post_funding_candidates(
        market, start, start + pd.Timedelta(hours=1), config)[0]
    assert changed['funding_threshold'] == first['funding_threshold']


def test_adverse_same_bar_order_and_fractional_sub_dollar_sizing():
    market = _qualifying_market('XRPUSDT')
    config = _small_config()
    entry = pd.Timestamp('2026-01-01 00:05', tz='UTC')
    candidate = build_post_funding_candidates(
        market, entry, entry + pd.Timedelta(hours=1), config)[0]
    fill = float(market['XRPUSDT']['perpetual'].at[entry, 'open'])
    risk = max(config.atr_multiple * candidate['atr'],
               config.minimum_r_fraction * fill)
    # The positive funding event produces a short.  Both its adverse stop and
    # favorable target occur in this candle, so the frozen adverse rule wins.
    _set_bar(
        market['XRPUSDT']['perpetual'], entry, open_=fill,
        high=fill + 1.1 * risk, low=fill - 2.1 * risk, close=fill)
    result = simulate_post_funding_exhaustion(
        market, entry, entry + pd.Timedelta(minutes=10), config)
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    assert trade['side'] == 'SHORT'
    assert trade['quantity'] > 0
    assert trade['quantity'] / .1 == pytest.approx(
        np.floor(trade['quantity'] / .1 + 1e-12))
    assert not float(trade['quantity']).is_integer()
    assert trade['initial_risk_usd'] <= .50 + 1e-12
    assert trade['notional_usd'] <= 125 + 1e-12
    assert result['summary']['direction_cohorts']['SHORT']['trades'] == 1
    assert result['summary']['per_symbol']['XRPUSDT']['trades'] == 1
    assert str(entry.date()) in result['summary']['daily_pnl']


def test_cost_breakeven_activates_only_after_trigger_bar():
    market = _qualifying_market(sign=-1)
    config = replace(_small_config(), costs=PFECosts())
    entry = pd.Timestamp('2026-01-01 00:05', tz='UTC')
    candidate = build_post_funding_candidates(
        market, entry, entry + pd.Timedelta(hours=1), config)[0]
    reference = float(market['DOGEUSDT']['perpetual'].at[entry, 'open'])
    entry_fill = reference * 1.001
    risk = max(config.atr_multiple * candidate['atr'],
               config.minimum_r_fraction * entry_fill)
    be_stop = pfe._cost_breakeven_stop(entry_fill, 1, config)
    _set_bar(
        market['DOGEUSDT']['perpetual'], entry, open_=reference,
        high=entry_fill + 1.1 * risk,
        low=reference, close=entry_fill + .5 * risk)
    second = entry + pd.Timedelta(minutes=5)
    _set_bar(
        market['DOGEUSDT']['perpetual'], second,
        open_=be_stop + .1 * risk, high=be_stop + .2 * risk,
        low=be_stop - .1 * risk, close=be_stop)
    result = simulate_post_funding_exhaustion(
        market, entry, entry + pd.Timedelta(minutes=15), config)
    trade = result['trades'][0]
    assert trade['reason'] == 'STOP'
    assert trade['closed_at'] == str(second + pd.Timedelta(minutes=5))
    assert trade['stop_updates'][0]['active_from'] == str(second)
    # Adverse tick rounding can give up a fraction of the intended +2 bps.
    assert 0 < trade['pnl'] / trade['notional_usd'] <= .0002 + 1e-12


def test_triggering_funding_is_excluded_but_later_settlement_is_booked():
    market = _qualifying_market()
    config = _small_config()
    entry = pd.Timestamp('2026-01-01 00:05', tz='UTC')
    later = entry + pd.Timedelta(minutes=5)
    rates = market['DOGEUSDT']['funding']
    rates.loc[later] = .001
    rates.sort_index(inplace=True)
    result = simulate_post_funding_exhaustion(
        market, entry, entry + pd.Timedelta(minutes=190), config)
    trade = result['trades'][0]
    expected = trade['quantity'] * float(
        market['DOGEUSDT']['mark'].at[entry, 'close']) * .001
    assert trade['reason'] == 'TIME_180M'
    assert trade['funding_pnl'] == pytest.approx(expected)
    assert trade['funding_pnl'] != pytest.approx(expected * 2)


def _flat_market(start, end, symbol='XRPUSDT'):
    index = pd.date_range(start, end, freq='5min', inclusive='left', tz='UTC')
    frame = pd.DataFrame({
        'open': 100.0, 'high': 100.1, 'low': 97.9, 'close': 100.0,
        'quote_volume': 1_000_000.0,
    }, index=index)
    return {symbol: {
        'perpetual': frame.copy(), 'mark': frame.copy(),
        'index': frame.copy(), 'funding': pd.Series(dtype=float,
                                                    index=pd.DatetimeIndex([], tz='UTC')),
    }}


def _fake_candidate(timestamp, number, symbol='XRPUSDT'):
    return {
        'timestamp': timestamp, 'funding_time': timestamp - pd.Timedelta(minutes=5),
        'confirmation_time': timestamp, 'feature_cutoff': timestamp,
        'symbol': symbol, 'side': 1, 'score': 1.0,
        'funding_rate': -.001, 'funding_threshold': .0005,
        'return_60m': -.01, 'return_threshold': .005,
        'pre_premium': -.001, 'post_premium': -.0004,
        'reversal_return': .001, 'atr': 1.0,
        'minimum_prior_12_quote_volume': 1_000_000.0,
        'liquidity_notional_cap_usd': 1_000.0,
        'setup': 'POST_FUNDING_EXHAUSTION', 'setup_id': f'test-{number}',
    }


def test_daily_then_weekly_realised_loss_stops_block_new_entries(monkeypatch):
    start = pd.Timestamp('2026-01-05', tz='UTC')
    end = start + pd.Timedelta(days=3)
    market = _flat_market(start, end)
    candidates = []
    number = 0
    for day in range(3):
        for minute in (0, 10, 20, 30, 40):
            timestamp = start + pd.Timedelta(days=day, minutes=minute)
            candidates.append(_fake_candidate(timestamp, number))
            number += 1
    monkeypatch.setattr(pfe, 'build_post_funding_candidates',
                        lambda *args, **kwargs: candidates)
    result = simulate_post_funding_exhaustion(
        market, start, end, _small_config())
    # Four scaled 0.2%-risk losses trip the daily stop.  The second day's
    # fourth loss also crosses the frozen 1.5% start-of-week threshold.
    assert result['summary']['trades'] == 10
    assert result['summary']['diagnostics']['blocked_risk_halt_or_capital'] == 5
    assert result['summary']['diagnostics']['daily_loss_stops'] == 2
    assert result['summary']['diagnostics']['weekly_loss_stops'] == 1
    assert len(result['summary']['daily_pnl']) == 3


def test_drawdown_kill_is_permanent_after_gap_loss(monkeypatch):
    start = pd.Timestamp('2026-01-05', tz='UTC')
    end = start + pd.Timedelta(minutes=30)
    market = _flat_market(start, end)
    # Enter long, then gap far through the stop on the next candle.
    market['XRPUSDT']['perpetual'].loc[
        start, ['open', 'high', 'low', 'close']
    ] = [100.0, 100.1, 99.9, 100.0]
    market['XRPUSDT']['perpetual'].loc[
        start + pd.Timedelta(minutes=5), ['open', 'high', 'low', 'close']
    ] = [50.0, 50.1, 49.9, 50.0]
    candidates = [_fake_candidate(start, 1),
                  _fake_candidate(start + pd.Timedelta(minutes=10), 2)]
    monkeypatch.setattr(pfe, 'build_post_funding_candidates',
                        lambda *args, **kwargs: candidates)
    result = simulate_post_funding_exhaustion(
        market, start, end, _small_config())
    assert result['trades'][0]['reason'] == 'STOP_GAP'
    assert result['summary']['risk_fail'] is True
    assert result['summary']['diagnostics']['drawdown_kills'] == 1
    assert result['summary']['trades'] == 1
    assert result['summary']['diagnostics']['blocked_risk_halt_or_capital'] == 1


def test_minimum_notional_never_raises_quantity_or_risk(monkeypatch):
    start = pd.Timestamp('2026-01-05', tz='UTC')
    end = start + pd.Timedelta(minutes=15)
    market = _flat_market(start, end)
    candidate = _fake_candidate(start, 1)
    candidate['liquidity_notional_cap_usd'] = 19.99
    monkeypatch.setattr(pfe, 'build_post_funding_candidates',
                        lambda *args, **kwargs: [candidate])
    result = simulate_post_funding_exhaustion(
        market, start, end, _small_config())
    assert result['trades'] == []
    assert result['summary']['diagnostics']['blocked_minimum_notional'] == 1


def test_equal_scores_use_frozen_universe_priority():
    doge = _qualifying_market('DOGEUSDT')
    eth = _qualifying_market('ETHUSDT')
    market = {**doge, **eth}
    config = _small_config()
    start = pd.Timestamp('2026-01-01 00:05', tz='UTC')
    result = simulate_post_funding_exhaustion(
        market, start, start + pd.Timedelta(minutes=10), config)
    assert result['trades'][0]['symbol'] == 'DOGEUSDT'
