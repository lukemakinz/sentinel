import unittest

import pandas as pd

from l1_filter.ob_liquidity_reversal import (
    OBLiquidityReversalConfig,
    ob_liquidity_reversal_signals,
)
from l1_filter.scalp_strategy import resample_closed
from l1_filter.setup_search import (
    SetupSearchConfig,
    evaluate_symbol,
    klines_to_bars,
)
from l1_filter.tests.test_ob_liquidity_reversal import synthetic_minutes


def _bars(minutes):
    return {'15m': resample_closed(minutes, 15), '1h': resample_closed(minutes, 60),
            '4h': resample_closed(minutes, 240)}


class SetupSearchConsistencyTests(unittest.TestCase):
    """The live scanner must report exactly what the backtested detector saw."""

    strategy = OBLiquidityReversalConfig(target_mode='first_at_min_r')
    config = SetupSearchConfig(strategy=strategy)

    def test_at_mss_close_scanner_reports_backtest_geometry(self):
        minutes = synthetic_minutes()
        signals, _ = ob_liquidity_reversal_signals(minutes, self.strategy)
        checked = 0
        for signal in signals[:6]:
            now = signal['timestamp']
            rows = evaluate_symbol(_bars(minutes.loc[minutes.index < now]), self.config, now)
            row = rows[0 if signal['side'] == 1 else 1]
            self.assertIn(row['status'], {'WAIT_RETEST', 'RR_TOO_LOW'})
            # Display values carry 6 significant digits.
            self.assertAlmostEqual(row['entry_limit'], signal['limit_price'], delta=abs(signal['limit_price']) * 1e-5)
            self.assertAlmostEqual(row['stop_loss'], signal['stop'], delta=abs(signal['stop']) * 1e-5)
            self.assertAlmostEqual(row['first_bsl_min_3r'], signal['target_price'], delta=abs(signal['target_price']) * 1e-5)
            self.assertEqual(row['score'], 5 + int(row['checklist']['rr_tp1_min_1_3']))
            checked += 1
        self.assertGreater(checked, 0)

    def test_right_after_sweep_scanner_waits_for_mss(self):
        minutes = synthetic_minutes()
        signals, _ = ob_liquidity_reversal_signals(minutes, self.strategy)
        signal = signals[0]
        sweep_close = pd.Timestamp(signal['evidence']['sweep_time'])
        rows = evaluate_symbol(
            _bars(minutes.loc[minutes.index < sweep_close]), self.config, sweep_close)
        row = rows[0 if signal['side'] == 1 else 1]

        self.assertEqual(row['status'], 'WAIT_MSS')
        self.assertEqual(row['sweep_time'], str(sweep_close))
        self.assertEqual(row['score'], 3)


class KlinesToBarsTests(unittest.TestCase):
    def test_bars_are_close_labelled_and_unfinished_bar_dropped(self):
        open_ms = int(pd.Timestamp('2026-10-26 10:00', tz='UTC').value // 10**6)
        row = lambda t: [t, '1', '2', '0.5', '1.5', '10', t + 899999, '15', 3, '6', '9', '0']
        rows = [row(open_ms), row(open_ms + 900000)]
        bars = klines_to_bars(rows, 15, pd.Timestamp('2026-10-26 10:20', tz='UTC'))

        self.assertEqual(list(bars.index), [pd.Timestamp('2026-10-26 10:15', tz='UTC')])
        self.assertEqual(bars.iloc[0].taker_buy_volume, 6.0)
