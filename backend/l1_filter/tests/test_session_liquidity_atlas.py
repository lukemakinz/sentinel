import numpy as np
import pandas as pd

from l1_filter.session_liquidity_atlas import (
    SessionLiquidityAtlasConfig,
    apply_session_liquidity_atlas,
)


def _bars():
    prior = pd.date_range(
        '2026-01-05 00:15', '2026-01-06 00:00', freq='15min', tz='UTC')
    current = pd.DatetimeIndex([
        pd.Timestamp('2026-01-06 08:00', tz='UTC'),
        pd.Timestamp('2026-01-06 08:15', tz='UTC'),
    ])
    index = prior.append(current)
    frame = pd.DataFrame({
        'high': 105.0,
        'low': 95.0,
        'close': 100.0,
        'atr': 2.0,
        'prior_target_liquidity_high': 110.0,
        'prior_target_liquidity_low': 90.0,
    }, index=index)
    frame.loc[prior[10], 'high'] = 110.0
    frame.loc[current[0], ['high', 'low', 'close']] = [109.0, 94.0, 100.0]
    frame.loc[current[1], ['high', 'low', 'close']] = [111.0, 99.0, 109.0]
    return frame


def test_previous_day_high_is_available_only_after_day_completes():
    result = apply_session_liquidity_atlas(_bars())
    sweep = result.loc[pd.Timestamp('2026-01-06 08:15', tz='UTC')]
    assert sweep.prior_liquidity_high == 110.0
    assert sweep.prior_high_touches >= 2
    assert np.isnan(result.loc[
        pd.Timestamp('2026-01-06 08:00', tz='UTC'), 'prior_liquidity_high'])


def test_atlas_preserves_independent_opposite_liquidity_target():
    result = apply_session_liquidity_atlas(_bars())
    sweep = result.loc[pd.Timestamp('2026-01-06 08:15', tz='UTC')]
    assert sweep.prior_target_liquidity_low == 90.0
