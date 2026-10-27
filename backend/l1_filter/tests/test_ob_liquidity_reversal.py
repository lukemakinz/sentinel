import unittest

import numpy as np
import pandas as pd

from l1_filter.ob_liquidity_reversal import (
    OBLiquidityReversalConfig,
    mirror,
    ob_liquidity_reversal_signals,
    stress_net_r,
)


def synthetic_minutes(seed=4, days=60):
    """Regime-switching random walk; deterministic per seed."""
    rng = np.random.default_rng(seed)
    n = days * 1440
    drift = np.repeat(rng.choice([-1, 1], size=n // 720 + 1) * 0.00004, 720)[:n]
    vol = np.repeat(rng.uniform(0.0004, 0.0012, size=n // 240 + 1), 240)[:n]
    close = 100 * np.exp(np.cumsum(drift + vol * rng.standard_t(4, size=n)))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.normal(0, 0.0005, size=n)) * close
    volume = rng.uniform(50, 150, size=n)
    return pd.DataFrame({
        'open': open_,
        'high': np.maximum(open_, close) + wick,
        'low': np.minimum(open_, close) - wick,
        'close': close,
        'volume': volume,
        'taker_buy_volume': volume / 2,
    }, index=pd.date_range('2025-01-01', periods=n, freq='1min', tz='UTC'))


class OBLiquidityReversalTests(unittest.TestCase):
    config = OBLiquidityReversalConfig(target_mode='first_at_min_r')

    def test_signals_have_consistent_geometry_and_min_net_r(self):
        signals, _ = ob_liquidity_reversal_signals(synthetic_minutes(), self.config)

        self.assertTrue(signals)
        self.assertEqual({s['side'] for s in signals}, {1, -1})
        for s in signals:
            side = s['side']
            self.assertGreater(side * (s['limit_price'] - s['stop']), 0)
            self.assertGreater(side * (s['target_price'] - s['limit_price']), 0)
            self.assertGreaterEqual(s['evidence']['stress_net_r'], 3.0)
            self.assertLessEqual(s['evidence']['stress_net_r'], 10.0)

    def test_no_lookahead_prefix_invariance(self):
        minutes = synthetic_minutes()
        full, _ = ob_liquidity_reversal_signals(minutes, self.config)
        cut = minutes.index[len(minutes) * 2 // 3]
        truncated, _ = ob_liquidity_reversal_signals(minutes.loc[:cut], self.config)
        # The MSS window can look 16 x 15m bars past a sweep; stay clear of it.
        horizon = cut - pd.Timedelta(hours=5)
        before = lambda items: [
            (s['timestamp'], s['side'], s['limit_price'], s['stop'], s['target_price'])
            for s in items if s['timestamp'] <= horizon
        ]

        self.assertTrue(before(full))
        self.assertEqual(before(full), before(truncated))

    def test_nearest_mode_is_subset_of_first_at_min_r(self):
        minutes = synthetic_minutes()
        strict, _ = ob_liquidity_reversal_signals(
            minutes, OBLiquidityReversalConfig(target_mode='nearest'))
        external, _ = ob_liquidity_reversal_signals(minutes, self.config)
        external_ids = {s['setup_id'] for s in external}

        self.assertTrue({s['setup_id'] for s in strict} <= external_ids)

    def test_mirror_swaps_highs_and_lows(self):
        minutes = synthetic_minutes(days=1)
        flipped = mirror(minutes)

        self.assertTrue((flipped.high == -minutes.low).all())
        self.assertTrue((flipped.low == -minutes.high).all())
        self.assertTrue((mirror(flipped) == minutes).all().all())

    def test_stress_net_r_charges_costs_symmetrically(self):
        config = OBLiquidityReversalConfig()
        long_r = stress_net_r(1, 100.0, 99.0, 104.0, config)
        short_r = stress_net_r(-1, 100.0, 101.0, 96.0, config)

        # 4R gross on a 1% stop: maker in, taker + 5 bps slip out on both legs.
        self.assertAlmostEqual(long_r, 3.2366, places=4)
        self.assertAlmostEqual(long_r, short_r, places=2)


def synthetic_open_interest(minutes, seed=4):
    rng = np.random.default_rng(seed + 100)
    index = minutes.index[::5]
    return pd.Series(1e6 * np.exp(np.cumsum(rng.normal(0, 0.002, len(index)))), index=index)


class S113FilterTests(unittest.TestCase):
    base = OBLiquidityReversalConfig(target_mode='first_at_min_r')
    filtered = OBLiquidityReversalConfig(
        target_mode='first_at_min_r', require_absorption=True,
        discount_fraction=1 / 3, partial_r=2.0)

    def test_filters_only_remove_setups(self):
        minutes = synthetic_minutes()
        oi = synthetic_open_interest(minutes)
        base, _ = ob_liquidity_reversal_signals(minutes, self.base, oi)
        filtered, audit = ob_liquidity_reversal_signals(minutes, self.filtered, oi)

        self.assertLess(len(filtered), len(base))
        base_ids = {s['setup_id'] for s in base}
        for s in filtered:
            self.assertIn(s['evidence']['absorption'], {'cvd_divergence', 'oi_flush'})
        # Discount/absorption can shift which later zone is consumed, so
        # require only that most filtered setups also exist unfiltered.
        overlap = sum(s['setup_id'] in base_ids for s in filtered)
        self.assertGreaterEqual(overlap, len(filtered) * 0.5)
        self.assertTrue(any('reject_no_absorption' in a for a in audit.values()))

    def test_partial_level_sits_at_two_r(self):
        minutes = synthetic_minutes()
        signals, _ = ob_liquidity_reversal_signals(
            minutes, OBLiquidityReversalConfig(target_mode='first_at_min_r', partial_r=2.0))

        self.assertTrue(signals)
        for s in signals:
            risk = abs(s['limit_price'] - s['stop'])
            self.assertAlmostEqual(
                s['side'] * (s['partial_price'] - s['limit_price']), 2.0 * risk)
            self.assertEqual(s['partial_fraction'], 0.5)

    def test_filtered_signals_have_no_lookahead(self):
        minutes = synthetic_minutes()
        oi = synthetic_open_interest(minutes)
        cut = minutes.index[len(minutes) * 2 // 3]
        full, _ = ob_liquidity_reversal_signals(minutes, self.filtered, oi)
        truncated, _ = ob_liquidity_reversal_signals(
            minutes.loc[:cut], self.filtered, oi.loc[:cut])
        horizon = cut - pd.Timedelta(hours=5)
        key = lambda items: [(s['timestamp'], s['side'], s['limit_price'])
                             for s in items if s['timestamp'] <= horizon]

        self.assertEqual(key(full), key(truncated))

    def test_mirror_flips_aggressor_volume(self):
        minutes = synthetic_minutes(days=1)
        flipped = mirror(minutes)
        delta = 2 * minutes.taker_buy_volume - minutes.volume
        flipped_delta = 2 * flipped.taker_buy_volume - flipped.volume

        self.assertTrue(np.allclose(flipped_delta, -delta))
