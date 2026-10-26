from dataclasses import replace

import pandas as pd

from l1_filter.liquidity_sweep_failed_auction import (
    FailedAuctionConfig,
    generate_failed_auction_signals_from_bars,
)


def _bars(side: int) -> pd.DataFrame:
    index = pd.date_range('2026-01-01', periods=4, freq='15min', tz='UTC')
    common = {
        'atr': [10.0] * 4,
        'relative_volume': [1.0, 1.2, 1.0, 1.0],
        'open_interest': [100.0] * 4,
        'oi_change_pct': [0.0, 0.10, 0.10, 0.10],
        'metrics_age_minutes': [0.0] * 4,
        'prior_liquidity_high': [130.0] * 4,
        'prior_liquidity_low': [70.0] * 4,
        'prior_high_touches': [3] * 4,
        'prior_low_touches': [3] * 4,
    }
    if side == 1:
        directional = {
            'open': [100.0, 72.0, 75.0, 80.0],
            'high': [102.0, 75.0, 78.0, 83.0],
            'low': [98.0, 69.0, 74.0, 79.0],
            'close': [100.0, 72.0, 77.5, 82.0],
            'taker_ratio': [0.5, 0.45, 0.55, 0.55],
            'taker_buy_sell_vol_ratio': [1.0, 0.9, 1.1, 1.1],
            'mean_funding': [-0.0001] * 4,
            'trend4h': [1] * 4,
        }
    else:
        directional = {
            'open': [100.0, 128.0, 125.0, 120.0],
            'high': [102.0, 131.0, 126.0, 121.0],
            'low': [98.0, 125.0, 122.0, 117.0],
            'close': [100.0, 128.0, 122.5, 118.0],
            'taker_ratio': [0.5, 0.55, 0.45, 0.45],
            'taker_buy_sell_vol_ratio': [1.0, 1.1, 0.9, 0.9],
            'mean_funding': [0.0001] * 4,
            'trend4h': [-1] * 4,
        }
    return pd.DataFrame({**common, **directional}, index=index)


def test_long_waits_for_later_break_and_anchors_stop_below_sweep():
    bars = _bars(1)
    regimes = pd.Series('UP', index=bars.index)

    signals, diagnostics = generate_failed_auction_signals_from_bars(
        bars, regimes, 'ETHUSDT')

    assert diagnostics['long_armed'] == 1
    assert diagnostics['long_signals'] == 1
    assert len(signals) == 1
    signal = signals[0]
    assert signal['timestamp'] == bars.index[2]
    assert signal['side'] == 1
    assert signal['stop'] < 69.0
    assert signal['target_price'] > 77.5
    assert signal['risk_scale'] == 0.5


def test_short_waits_for_later_break_and_anchors_stop_above_sweep():
    bars = _bars(-1)
    regimes = pd.Series('DOWN', index=bars.index)

    signals, diagnostics = generate_failed_auction_signals_from_bars(
        bars, regimes, 'ETHUSDT')

    assert diagnostics['short_armed'] == 1
    assert diagnostics['short_signals'] == 1
    assert len(signals) == 1
    signal = signals[0]
    assert signal['timestamp'] == bars.index[2]
    assert signal['side'] == -1
    assert signal['stop'] > 131.0
    assert signal['target_price'] < 122.5


def test_wrong_funding_side_prevents_arming():
    bars = _bars(-1)
    bars['mean_funding'] = -0.001
    regimes = pd.Series('DOWN', index=bars.index)

    signals, diagnostics = generate_failed_auction_signals_from_bars(
        bars, regimes, 'ETHUSDT')

    assert signals == []
    assert diagnostics.get('armed', 0) == 0


def test_config_rejects_risk_scale_above_one():
    try:
        replace(FailedAuctionConfig(), risk_scale=1.1).validate()
    except ValueError as error:
        assert 'risk scale' in str(error)
    else:
        raise AssertionError('Expected invalid risk scale')
