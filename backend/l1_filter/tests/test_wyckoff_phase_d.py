from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.wyckoff_phase_c import prepare_wyckoff_bars
from l1_filter.wyckoff_phase_d import (
    WyckoffPhaseDConfig,
    wyckoff_phase_d_signals_from_bars,
)


def _sequence(test_volume=65.0):
    index = pd.date_range('2026-02-01', periods=44, freq='1h', tz='UTC')
    rows = []
    for i in range(40):
        centre = 105.0 + np.sin(i * np.pi / 4) * 3.5
        rows.append({'open': centre - 0.1, 'high': centre + 0.8,
                     'low': centre - 0.8, 'close': centre, 'volume': 100.0,
                     'taker_buy_volume': 50.0})
    rows.extend([
        {'open': 109.0, 'high': 112.2, 'low': 108.9, 'close': 112.0,
         'volume': 160.0, 'taker_buy_volume': 100.0},
        {'open': 112.0, 'high': 112.3, 'low': 111.5, 'close': 111.8,
         'volume': 80.0, 'taker_buy_volume': 40.0},
        {'open': 111.5, 'high': 111.8, 'low': 110.0, 'close': 110.7,
         'volume': test_volume, 'taker_buy_volume': test_volume * 0.45},
        {'open': 110.7, 'high': 112.4, 'low': 110.6, 'close': 112.2,
         'volume': 100.0, 'taker_buy_volume': 60.0},
    ])
    return pd.DataFrame(rows, index=index)


def _config():
    return replace(
        WyckoffPhaseDConfig(), range_hours=20, min_range_atr=1.0,
        max_range_atr=20.0, max_efficiency_ratio=1.0,
        min_touch_clusters=1, touch_separation_hours=2,
        breakout_close_atr=0.01, max_breakout_close_atr=5.0,
        breakout_spread_atr=0.5, breakout_volume_multiple=1.0,
        min_test_delay_hours=2, test_distance_atr=1.0,
        max_test_failure_atr=1.0, max_test_spread_atr=2.0,
        maximum_chase_atr=3.0, minimum_reward_risk=0.5,
    )


def test_sos_lps_signal_waits_for_confirmation():
    bars = prepare_wyckoff_bars(_sequence())
    signals = wyckoff_phase_d_signals_from_bars(bars, _config())
    assert len(signals) == 1
    assert signals[0]['timestamp'] == bars.index[-1]
    assert signals[0]['setup'] == 'WYCKOFF_SOS_LPS'


def test_no_lps_when_volume_does_not_contract():
    bars = prepare_wyckoff_bars(_sequence(test_volume=150.0))
    assert wyckoff_phase_d_signals_from_bars(bars, _config()) == []
