import unittest

import numpy as np
import pandas as pd

from backtest.metrics_data import (
    COLUMNS, _assemble_metrics, _parse_metrics_csv, prefetch_metrics_archives,
)


def _raw_csv(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


class ParseMetricsCsvTests(unittest.TestCase):
    def test_parses_and_filters_by_symbol(self):
        raw = _raw_csv([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            ['2025-05-01 00:00:00', 'SOLUSDT', 9.0, 9.0, 9.0, 9.0, 9.0, 9.0],
            ['2025-05-01 00:05:00', 'ETHUSDT', 1.1, 2.1, 3.1, 4.1, 5.1, 6.1],
        ])
        parsed = _parse_metrics_csv(raw, 'ETHUSDT')
        self.assertEqual(len(parsed), 2)
        self.assertEqual(list(parsed.columns), [
            'sum_open_interest', 'sum_open_interest_value',
            'count_toptrader_long_short_ratio', 'sum_toptrader_long_short_ratio',
            'count_long_short_ratio', 'sum_taker_long_short_vol_ratio'])
        self.assertTrue(parsed.index[0].tzinfo is not None)

    def test_rejects_unexpected_schema(self):
        bad = pd.DataFrame({'a': [1], 'b': [2]})
        with self.assertRaises(ValueError):
            _parse_metrics_csv(bad, 'ETHUSDT')


class AssembleMetricsTests(unittest.TestCase):
    def _parsed(self, rows):
        raw = _raw_csv(rows)
        return _parse_metrics_csv(raw, 'ETHUSDT')

    def test_forward_fills_a_small_gap(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            # 00:05 missing
            ['2025-05-01 00:10:00', 'ETHUSDT', 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:15', tz='UTC')
        assembled = _assemble_metrics(parsed, start, end)
        self.assertEqual(len(assembled), 3)
        self.assertEqual(assembled.open_interest.iloc[1], 1.0)  # ffilled from 00:00

    def test_raises_on_leading_gap_ffill_cannot_cover(self):
        parsed = self._parsed([
            ['2025-05-01 00:10:00', 'ETHUSDT', 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:15', tz='UTC')
        with self.assertRaises(ValueError):
            _assemble_metrics(parsed, start, end)

    def test_deduplicates_keeping_last(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            ['2025-05-01 00:00:00', 'ETHUSDT', 9.0, 9.0, 9.0, 9.0, 9.0, 9.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:05', tz='UTC')
        assembled = _assemble_metrics(parsed, start, end)
        self.assertEqual(len(assembled), 1)
        self.assertEqual(assembled.open_interest.iloc[0], 9.0)

    def test_output_columns_are_renamed_and_finite(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:05', tz='UTC')
        assembled = _assemble_metrics(parsed, start, end)
        self.assertEqual(list(assembled.columns), [
            'open_interest', 'open_interest_value', 'toptrader_account_ratio',
            'toptrader_position_ratio', 'retail_account_ratio', 'taker_buy_sell_vol_ratio'])
        self.assertTrue(np.isfinite(assembled.to_numpy()).all())

    def test_optional_freshness_reports_age_of_last_real_snapshot(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            ['2025-05-01 00:10:00', 'ETHUSDT', 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:15', tz='UTC')

        assembled = _assemble_metrics(parsed, start, end, include_freshness=True)

        self.assertEqual(assembled.metrics_age_minutes.tolist(), [0.0, 5.0, 0.0])
        self.assertEqual(assembled.metrics_observed.tolist(), [True, False, True])

    def test_optional_freshness_exposes_snapshot_older_than_ten_minutes(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT', 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            ['2025-05-01 00:20:00', 'ETHUSDT', 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:25', tz='UTC')

        assembled = _assemble_metrics(parsed, start, end, include_freshness=True)

        self.assertEqual(assembled.loc[pd.Timestamp('2025-05-01 00:15', tz='UTC'),
                                       'metrics_age_minutes'], 15.0)
        self.assertFalse(
            assembled.loc[pd.Timestamp('2025-05-01 00:15', tz='UTC'),
                          'metrics_age_minutes'] <= 10)

    def test_required_columns_allow_unused_positioning_fields_to_be_missing(self):
        parsed = self._parsed([
            ['2025-05-01 00:00:00', 'ETHUSDT',
             1.0, 2.0, np.nan, np.nan, 5.0, 6.0],
        ])
        start = pd.Timestamp('2025-05-01', tz='UTC')
        end = pd.Timestamp('2025-05-01 00:05', tz='UTC')

        with self.assertRaises(ValueError):
            _assemble_metrics(parsed, start, end)

        assembled = _assemble_metrics(
            parsed, start, end, required_columns=('open_interest',))
        self.assertEqual(assembled.open_interest.iloc[0], 1.0)
        self.assertTrue(np.isnan(assembled.toptrader_account_ratio.iloc[0]))


class PrefetchValidationTests(unittest.TestCase):
    def test_rejects_invalid_worker_count_before_network(self):
        with self.assertRaises(ValueError):
            prefetch_metrics_archives(
                ('BTCUSDT',), '2025-01-01', '2025-01-02', '/tmp/unused', workers=0)
