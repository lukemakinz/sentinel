import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from l1_filter.s20_entry_lab import S20EntryLabConfig, build_s20_entry_variants


def _minutes(periods=90):
    index = pd.date_range('2026-01-05 09:00', periods=periods, freq='min', tz='UTC')
    close = np.full(periods, 100.0)
    frame = pd.DataFrame({
        'open': close, 'high': close + 0.1, 'low': close - 0.1, 'close': close,
        'volume': np.ones(periods), 'taker_buy_volume': np.full(periods, 0.5),
    }, index=index)
    # First closed 5m bar after the 09:30 parent candidate confirms above 101.
    frame.loc[(index >= pd.Timestamp('2026-01-05 09:30', tz='UTC'))
              & (index < pd.Timestamp('2026-01-05 09:35', tz='UTC')), 'close'] = 101.2
    frame.loc[(index >= pd.Timestamp('2026-01-05 09:30', tz='UTC'))
              & (index < pd.Timestamp('2026-01-05 09:35', tz='UTC')), 'high'] = 101.3
    frame.loc[(index >= pd.Timestamp('2026-01-05 09:30', tz='UTC'))
              & (index < pd.Timestamp('2026-01-05 09:35', tz='UTC')), 'low'] = 99.9
    return frame


def _bars():
    index = pd.date_range('2026-01-05 07:30', periods=9, freq='15min', tz='UTC')
    frame = pd.DataFrame({
        'open': np.full(9, 100.0), 'high': np.full(9, 100.8),
        'low': np.full(9, 99.5), 'close': np.full(9, 100.2),
    }, index=index)
    # Candidate bar at 09:30 sweeps the prior low and closes directionally above it.
    frame.loc[index[-1], ['open', 'high', 'low', 'close']] = [99.7, 101.0, 99.3, 100.4]
    return frame


def _signal():
    timestamp = pd.Timestamp('2026-01-05 09:30', tz='UTC')
    return {
        'timestamp': timestamp, 'side': 1, 'reference': 100.4, 'stop': 98.5,
        'atr': 1.0, 'min_stop_atr': 0.5, 'max_stop_atr': 3.0,
        'score': 6, 'setup': 'parent', 'setup_id': 'PARENT:1',
    }


class S20EntryLabTests(SimpleTestCase):
    def test_builds_all_four_entry_policies_causally(self):
        variants = build_s20_entry_variants(_minutes(), _bars(), [_signal()])
        self.assertEqual(len(variants['MARKET_TOUCH']), 1)
        self.assertEqual(len(variants['SWEEP_RECLAIM']), 1)
        self.assertEqual(len(variants['MSS_BREAK']), 1)
        self.assertEqual(len(variants['MSS_RETEST']), 1)
        self.assertEqual(
            variants['MSS_BREAK'][0]['timestamp'],
            pd.Timestamp('2026-01-05 09:35', tz='UTC'),
        )
        self.assertEqual(variants['MSS_RETEST'][0]['limit_price'], 101.0)

    def test_no_break_means_no_mss_or_retest(self):
        minutes = _minutes()
        minutes.loc[:, ['open', 'high', 'low', 'close']] = [100.0, 100.2, 99.8, 100.0]
        variants = build_s20_entry_variants(minutes, _bars(), [_signal()])
        self.assertEqual(variants['MSS_BREAK'], [])
        self.assertEqual(variants['MSS_RETEST'], [])

    def test_future_after_confirmation_window_cannot_change_signal(self):
        first = build_s20_entry_variants(_minutes(), _bars(), [_signal()])
        changed = _minutes()
        changed.loc[changed.index >= pd.Timestamp('2026-01-05 10:05', tz='UTC'),
                    ['open', 'high', 'low', 'close']] = [50, 55, 45, 52]
        second = build_s20_entry_variants(changed, _bars(), [_signal()])
        self.assertEqual(first['MSS_BREAK'][0]['setup_id'], second['MSS_BREAK'][0]['setup_id'])

    def test_invalid_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            S20EntryLabConfig(mss_window_minutes=7)
