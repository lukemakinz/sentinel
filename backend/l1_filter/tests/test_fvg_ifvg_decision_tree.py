from dataclasses import replace

import pandas as pd

from l1_filter.fvg_ifvg_decision_tree import (
    FVGIFVGConfig, detect_fvg_zones, generate_fvg_ifvg_signals_from_bars,
)


def _formation():
    index = pd.date_range('2026-01-01 01:00', periods=25, freq='1h', tz='UTC')
    rows = []
    for _ in index:
        rows.append({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 100.0, 'atr': 1.0,
        })
    # A clean bullish FVG: first.high=100, third.low=101, with a displaced
    # green middle candle.  The zone only becomes known at index[-1].
    rows[-3].update(open=99.8, high=100.0, low=99.6, close=99.9)
    rows[-2].update(
        open=99.9, high=102.2, low=99.8, close=102.0, volume=200.0)
    rows[-1].update(open=101.2, high=102.1, low=101.0, close=101.8)
    return pd.DataFrame(rows, index=index)


def _confirmation(rows):
    created = _formation().index[-1]
    index = pd.date_range(created + pd.Timedelta(minutes=15),
                          periods=len(rows), freq='15min')
    result = pd.DataFrame(rows, index=index)
    defaults = {
        'atr': 1.0, 'relative_volume': 1.2, 'taker_ratio': 0.60,
        'open_interest': 1000.0, 'oi_change_pct': 0.10,
        'taker_buy_sell_vol_ratio': 1.2, 'metrics_age_minutes': 0.0,
        'trend4h': 1.0,
    }
    for key, value in defaults.items():
        if key not in result:
            result[key] = value
    return result


def _regime(value):
    return pd.Series(
        [value], index=[pd.Timestamp('2026-01-01', tz='UTC')], name='regime')


def test_detects_displaced_bullish_fvg():
    zones = detect_fvg_zones(_formation(), 'ETHUSDT')
    assert len(zones) == 1
    assert zones[0].direction == 'bullish'
    assert zones[0].bottom == 100.0
    assert zones[0].top == 101.0


def test_defense_waits_for_later_break_candle_before_long():
    touch_reclaim = {
        'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
    }
    breakout = {
        'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
    }
    first, _ = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation([touch_reclaim]), _regime('UP'), 'ETHUSDT')
    assert first == []
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation([touch_reclaim, breakout]),
        _regime('UP'), 'ETHUSDT')
    assert len(signals) == 1
    assert signals[0]['side'] == 1
    assert signals[0]['setup'] == 'fvg_ifvg_defense'
    assert signals[0]['timestamp'] == _confirmation(
        [touch_reclaim, breakout]).index[-1]
    assert diagnostics['signals_defense'] == 1


def test_close_through_retest_and_break_creates_bearish_ifvg_short():
    close_through = {
        'open': 100.7, 'high': 101.1, 'low': 99.4, 'close': 99.5,
        'trend4h': -1.0, 'taker_ratio': 0.40,
        'taker_buy_sell_vol_ratio': 0.8,
    }
    retest_reject = {
        'open': 99.8, 'high': 100.5, 'low': 99.3, 'close': 99.5,
        'trend4h': -1.0, 'taker_ratio': 0.40,
        'taker_buy_sell_vol_ratio': 0.8,
    }
    break_low = {
        'open': 99.5, 'high': 99.6, 'low': 99.0, 'close': 99.1,
        'trend4h': -1.0, 'taker_ratio': 0.40,
        'taker_buy_sell_vol_ratio': 0.8,
    }
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation([close_through, retest_reject, break_low]),
        _regime('DOWN'), 'ETHUSDT')
    assert len(signals) == 1
    assert signals[0]['side'] == -1
    assert signals[0]['setup'] == 'fvg_ifvg_ifvg'
    assert diagnostics['invalidated_by_close'] == 1
    assert diagnostics['signals_ifvg'] == 1


def test_wick_through_far_edge_does_not_create_ifvg():
    wick_only = {
        'open': 100.8, 'high': 101.1, 'low': 99.3, 'close': 100.4,
        'trend4h': -1.0, 'taker_ratio': 0.40,
        'taker_buy_sell_vol_ratio': 0.8,
    }
    drift = {
        'open': 100.4, 'high': 100.8, 'low': 100.1, 'close': 100.3,
        'trend4h': -1.0, 'taker_ratio': 0.40,
        'taker_buy_sell_vol_ratio': 0.8,
    }
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation([wick_only, drift]),
        _regime('DOWN'), 'ETHUSDT')
    assert signals == []
    assert diagnostics.get('invalidated_by_close', 0) == 0
    assert diagnostics.get('ifvg_armed', 0) == 0


def test_global_regime_vetoes_otherwise_valid_long():
    rows = [
        {'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1},
        {'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4},
    ]
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('SIDEWAYS'), 'ETHUSDT')
    assert signals == []
    assert diagnostics['confluence_veto'] == 1


def test_micro_confluence_requires_two_of_oi_taker_and_volume():
    rows = [
        {'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1},
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'oi_change_pct': -0.1, 'taker_ratio': 0.50,
            'taker_buy_sell_vol_ratio': 1.0, 'relative_volume': 0.8,
        },
    ]
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT')
    assert signals == []
    assert diagnostics['confluence_veto'] == 1


def test_liquidity_sweep_mode_vetoes_plain_fvg_reclaim():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 99.0, 'prior_liquidity_high': 102.0,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.0, 'prior_liquidity_high': 102.0,
        },
    ]
    config = replace(FVGIFVGConfig(), require_liquidity_sweep=True)
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert signals == []
    assert diagnostics['defense_without_liquidity_sweep'] == 1


def test_liquidity_sweep_anchors_stop_beyond_sweep_extreme():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 100.0, 'prior_liquidity_high': 102.0,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.7, 'prior_liquidity_high': 102.0,
        },
    ]
    config = replace(FVGIFVGConfig(), require_liquidity_sweep=True)
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert len(signals) == 1
    assert signals[0]['stop'] == 99.55
    assert signals[0]['evidence']['liquidity_sweep_extreme'] == 99.7
    assert diagnostics['liquidity_sweep_seen'] == 1


def test_liquidity_reset_requires_oi_flush_then_directional_flow_flip():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 100.0, 'prior_liquidity_high': 108.0,
            'oi_change_15m_pct': -0.10, 'taker_ratio': 0.40,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.7, 'prior_liquidity_high': 108.0,
            'oi_change_15m_pct': 0.01, 'taker_ratio': 0.60,
        },
    ]
    config = replace(
        FVGIFVGConfig(), require_liquidity_sweep=True,
        require_liquidity_reset=True)
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert len(signals) == 1
    assert signals[0]['evidence']['oi_flush_ok'] is True
    assert signals[0]['evidence']['oi_stabilized'] is True
    assert diagnostics.get('liquidity_reset_veto', 0) == 0


def test_liquidity_reset_vetoes_sweep_with_rising_oi():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 100.0, 'prior_liquidity_high': 108.0,
            'oi_change_15m_pct': 0.10, 'taker_ratio': 0.40,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.7, 'prior_liquidity_high': 108.0,
            'oi_change_15m_pct': 0.20, 'taker_ratio': 0.60,
        },
    ]
    config = replace(
        FVGIFVGConfig(), require_liquidity_sweep=True,
        require_liquidity_reset=True)
    signals, diagnostics = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert signals == []
    assert diagnostics['liquidity_reset_veto'] == 1


def test_liquidity_target_requires_minimum_space_and_freezes_target():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 100.0, 'prior_liquidity_high': 108.0,
            'prior_target_liquidity_low': 98.0,
            'prior_target_liquidity_high': 108.0,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.7, 'prior_liquidity_high': 108.0,
            'prior_target_liquidity_low': 98.0,
            'prior_target_liquidity_high': 108.0,
        },
    ]
    config = replace(
        FVGIFVGConfig(), require_liquidity_sweep=True,
        require_liquidity_target=True)
    signals, _ = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert len(signals) == 1
    assert signals[0]['target_price'] == 107.34
    assert signals[0]['min_target_r'] == 2.5


def test_liquidity_target_can_cap_profit_before_external_pool():
    rows = [
        {
            'open': 99.8, 'high': 101.2, 'low': 99.7, 'close': 101.1,
            'prior_liquidity_low': 100.0, 'prior_liquidity_high': 108.0,
            'prior_target_liquidity_low': 98.0,
            'prior_target_liquidity_high': 108.0,
        },
        {
            'open': 101.1, 'high': 101.5, 'low': 101.0, 'close': 101.4,
            'prior_liquidity_low': 99.7, 'prior_liquidity_high': 108.0,
            'prior_target_liquidity_low': 98.0,
            'prior_target_liquidity_high': 108.0,
        },
    ]
    config = replace(
        FVGIFVGConfig(), require_liquidity_sweep=True,
        require_liquidity_target=True, minimum_liquidity_target_r=1.5,
        maximum_liquidity_target_r=2.5)
    signals, _ = generate_fvg_ifvg_signals_from_bars(
        _formation(), _confirmation(rows), _regime('UP'), 'ETHUSDT', config)
    assert len(signals) == 1
    assert signals[0]['evidence']['available_target_r'] > 2.5
    assert signals[0]['evidence']['decision_target_r'] == 2.5
    assert abs(signals[0]['target_price'] - 106.025) < 1e-10
