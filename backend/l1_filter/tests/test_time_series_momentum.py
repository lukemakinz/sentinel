import numpy as np
import pandas as pd

from l1_filter.time_series_momentum import (
    TSM4HConfig,
    build_tsm_features,
    generate_tsm_events,
)


def _features(regime=1):
    index = pd.date_range('2026-01-01 04:00', periods=6, freq='4h', tz='UTC')
    bars = pd.DataFrame({
        'high': [101, 102, 102, 104, 105, 104],
        'low': [99, 100, 100, 101, 103, 101],
        'close': [100, 101, 101, 103, 104, 102],
        'atr': [1.0] * 6,
        'entry_high': [None, None, 102, 102, 103, 105],
        'entry_low': [None, None, 99, 99, 100, 100],
        'exit_high': [None, None, 102, 102, 104, 105],
        'exit_low': [None, None, 99, 99, 100, 101],
    }, index=index).astype(float)
    daily = pd.DataFrame({'regime': [regime]}, index=[index[0]])
    return {'four_hour': bars, 'daily': daily}


def test_first_prior_channel_cross_creates_one_entry_not_persistent_duplicates():
    alt = _features(1)
    btc = _features(1)['daily']
    entries, _ = generate_tsm_events(
        alt, btc, 'ETHUSDT', TSM4HConfig(entry_channel=3, exit_channel=2))
    assert len(entries) == 1
    assert entries[0]['timestamp'] == alt['four_hour'].index[3]
    assert entries[0]['side'] == 1
    assert entries[0]['stop'] == 101.0


def test_btc_daily_regime_vetoes_otherwise_valid_breakout():
    entries, _ = generate_tsm_events(
        _features(1), _features(-1)['daily'], 'ETHUSDT',
        TSM4HConfig(entry_channel=3, exit_channel=2))
    assert entries == []


def test_future_rows_do_not_change_an_already_published_event():
    alt = _features(1)
    btc = _features(1)['daily']
    config = TSM4HConfig(entry_channel=3, exit_channel=2)
    earlier = generate_tsm_events(
        {'four_hour': alt['four_hour'].iloc[:4], 'daily': alt['daily']},
        btc, 'ETHUSDT', config)[0]
    full = generate_tsm_events(alt, btc, 'ETHUSDT', config)[0]
    assert earlier == full[:len(earlier)]


def test_mtm_only_synthetic_rows_do_not_form_complete_signal_bars():
    index = pd.date_range('2026-01-01', periods=576, freq='5min', tz='UTC')
    values = np.linspace(100.0, 110.0, len(index))
    five = pd.DataFrame({
        'open': values, 'high': values + .1, 'low': values - .1,
        'close': values, 'volume': 1.0, 'taker_buy_volume': .5,
        'synthetic': False,
    }, index=index)
    five.loc[index[100], 'synthetic'] = True
    features = build_tsm_features(
        five, TSM4HConfig(entry_channel=3, exit_channel=2, ema_days=2))
    affected_4h_close = index[100].floor('4h') + pd.Timedelta(hours=4)
    affected_daily_close = index[100].normalize() + pd.Timedelta(days=1)
    assert affected_4h_close not in features['four_hour'].index
    assert affected_daily_close not in features['daily'].index
