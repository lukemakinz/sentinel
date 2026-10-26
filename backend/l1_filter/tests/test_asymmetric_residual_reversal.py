from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.asymmetric_residual_reversal import (
    AsymmetricResidualConfig,
    asymmetric_residual_signals,
    residual_features,
)


def _minutes(hours=80):
    index = pd.date_range('2026-01-01', periods=hours * 60, freq='1min', tz='UTC')
    x = np.arange(len(index), dtype=float)
    btc = 100.0 * np.exp(0.00001 * x + 0.001 * np.sin(x / 120))
    alt = 50.0 * np.exp(0.000012 * x + 0.0012 * np.sin(x / 120))
    alt[-60:] *= 0.94
    def frame(close):
        return pd.DataFrame({
            'open': close, 'high': close * 1.0002, 'low': close * 0.9998,
            'close': close, 'volume': 1.0, 'taker_buy_volume': 0.5,
        }, index=index)
    alt_frame, btc_frame = frame(alt), frame(btc)
    alt_frame.loc[index[-60:], 'volume'] = 3.0
    alt_frame.loc[index[-60:], 'taker_buy_volume'] = 0.9
    return alt_frame, btc_frame


def test_estimators_are_prefix_invariant():
    alt, btc = _minutes()
    cfg = replace(AsymmetricResidualConfig(), beta_hours=24, z_hours=24,
                  volume_lookback_hours=12)
    first = residual_features(alt, btc, cfg)
    future_index = pd.date_range(alt.index[-1] + pd.Timedelta(minutes=1), periods=60, freq='1min')
    future = pd.DataFrame({'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0,
                           'volume': 1.0, 'taker_buy_volume': 0.5}, index=future_index)
    second = residual_features(pd.concat([alt, future]), pd.concat([btc, future]), cfg)
    pd.testing.assert_frame_equal(first, second.loc[first.index])


def test_only_negative_abnormal_sell_shock_can_enter():
    index = pd.date_range('2026-01-01', periods=2, freq='1h', tz='UTC')
    features = pd.DataFrame({
        'beta': [1.0, 1.0], 'residual': [-0.02, 0.02],
        'z': [-3.5, 3.5], 'volume_multiple': [2.0, 2.0],
        'taker_buy_fraction': [0.3, 0.7], 'residual_mean': [0.0, 0.0],
        'residual_std': [0.01, 0.01],
    }, index=index)
    signals = asymmetric_residual_signals(features, 'ETHUSDT')
    assert len(signals) == 1
    assert signals[0]['timestamp'] == index[0]
