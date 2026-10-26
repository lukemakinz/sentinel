from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.wyckoff_phase_c import (
    WyckoffPhaseCConfig,
    prepare_wyckoff_bars,
    wyckoff_signals_from_bars,
)


def _long_sequence(test_volume=70.0):
    index = pd.date_range('2026-01-01', periods=44, freq='1h', tz='UTC')
    rows = []
    for i in range(40):
        centre = 105.0 + np.sin(i * np.pi / 4) * 3.5
        rows.append({
            'open': centre - 0.1, 'high': centre + 0.8,
            'low': centre - 0.8, 'close': centre,
            'volume': 100.0, 'taker_buy_volume': 50.0,
        })
    # Phase-C spring, pause, lower-volume test, then minor SOS.
    rows.extend([
        {'open': 101.0, 'high': 102.0, 'low': 98.8, 'close': 101.0,
         'volume': 150.0, 'taker_buy_volume': 45.0},
        {'open': 101.0, 'high': 101.5, 'low': 100.5, 'close': 101.1,
         'volume': 80.0, 'taker_buy_volume': 40.0},
        {'open': 101.0, 'high': 101.2, 'low': 99.9, 'close': 100.8,
         'volume': test_volume, 'taker_buy_volume': test_volume * 0.45},
        {'open': 100.9, 'high': 101.8, 'low': 100.8, 'close': 101.7,
         'volume': 100.0, 'taker_buy_volume': 55.0},
    ])
    return pd.DataFrame(rows, index=index)


def _test_config():
    return replace(
        WyckoffPhaseCConfig(),
        range_hours=20,
        prior_trend_hours=40,
        min_prior_trend_fraction=0.0,
        min_range_atr=1.0,
        max_range_atr=20.0,
        max_efficiency_ratio=1.0,
        min_touch_clusters=1,
        touch_separation_hours=2,
        min_sweep_atr=0.01,
        max_sweep_atr=3.0,
        sweep_volume_multiple=1.0,
        min_test_delay_hours=2,
        minimum_reward_risk=1.5,
    )


def test_spring_test_confirmation_is_published_only_after_confirmation_close():
    bars = prepare_wyckoff_bars(_long_sequence())
    signals = wyckoff_signals_from_bars(bars, _test_config())
    assert len(signals) == 1
    assert signals[0]['side'] == 1
    assert signals[0]['timestamp'] == bars.index[-1]
    assert signals[0]['setup'] == 'WYCKOFF_SPRING_TEST'


def test_future_append_does_not_change_past_signal_prefix():
    bars = _long_sequence()
    first = wyckoff_signals_from_bars(prepare_wyckoff_bars(bars), _test_config())
    future_index = pd.date_range(bars.index[-1] + pd.Timedelta(hours=1), periods=8, freq='1h')
    future = pd.DataFrame({
        'open': 120.0, 'high': 121.0, 'low': 119.0, 'close': 120.0,
        'volume': 100.0, 'taker_buy_volume': 50.0,
    }, index=future_index)
    second = wyckoff_signals_from_bars(
        prepare_wyckoff_bars(pd.concat([bars, future])), _test_config())
    assert [s['setup_id'] for s in second if s['timestamp'] <= bars.index[-1]] == [
        s['setup_id'] for s in first]


def test_test_volume_must_contract_from_sweep():
    bars = prepare_wyckoff_bars(_long_sequence(test_volume=140.0))
    assert wyckoff_signals_from_bars(bars, _test_config()) == []
