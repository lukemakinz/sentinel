from unittest import TestCase

import numpy as np
import pandas as pd

from l1_filter.liquidity_delivery_scalp import (
    LiquidityDeliveryConfig,
    liquidity_delivery_features,
)


def minute_frame(start='2026-01-05 00:00', periods=900):
    index = pd.date_range(start, periods=periods, freq='min', tz='UTC')
    price = np.full(periods, 100.0)
    return pd.DataFrame({
        'open': price,
        'high': price + 0.1,
        'low': price - 0.1,
        'close': price,
        'volume': np.full(periods, 10.0),
        'taker_buy_volume': np.full(periods, 5.0),
    }, index=index)


class LiquidityDeliveryScalpTest(TestCase):
    def test_london_uses_range_frozen_at_two_am_new_york(self):
        minutes = minute_frame()
        # 02:00 ET is 07:00 UTC in January.  This spike belongs to the source
        # range, while the later spike belongs to the trading window.
        minutes.loc['2026-01-05 06:55':'2026-01-05 06:59', 'high'] = 110.0
        minutes.loc['2026-01-05 07:30':'2026-01-05 07:34', 'high'] = 150.0

        bars = liquidity_delivery_features(minutes, 5)
        decision_bar = bars.loc[pd.Timestamp('2026-01-05 08:00', tz='UTC')]

        self.assertEqual(decision_bar['session'], 'london')
        self.assertEqual(decision_bar['source_high'], 110.0)

    def test_future_prices_do_not_change_an_existing_frozen_range(self):
        minutes = minute_frame()
        prefix = minutes.loc[:'2026-01-05 08:00'].copy()
        future = minutes.copy()
        future.loc['2026-01-05 10:00':, 'high'] = 999.0

        prefix_value = liquidity_delivery_features(prefix, 5).loc[
            pd.Timestamp('2026-01-05 08:00', tz='UTC'), 'source_high']
        future_value = liquidity_delivery_features(future, 5).loc[
            pd.Timestamp('2026-01-05 08:00', tz='UTC'), 'source_high']

        self.assertEqual(prefix_value, future_value)

    def test_risk_is_small_and_leverage_is_only_a_cap(self):
        execution = LiquidityDeliveryConfig('test').execution()

        self.assertEqual(execution.leverage, 20)
        self.assertEqual(execution.risk_fraction, 0.003)
        self.assertLessEqual(execution.max_margin_fraction, 0.05)
        self.assertEqual(execution.partial_fraction, 0.0)
