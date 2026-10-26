from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from backtest.cross_sectional_momentum import (
    XSMConfig,
    XSMCosts,
    simulate_xsm_pairs,
    weekly_xsm_targets,
)


UTC = 'UTC'


def _daily_from_returns(returns, start='2025-01-01'):
    index = pd.date_range(start, periods=len(returns) + 1, freq='D', tz=UTC)
    close = 100 * np.exp(np.r_[0.0, np.cumsum(returns)])
    return pd.DataFrame({
        'close': close,
        'close_time': index + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
    }, index=index)


def _ranking_fixture():
    x = np.arange(90)
    btc_returns = .003 * np.sin(x / 3) + .001 * np.cos(x / 7)
    btc = _daily_from_returns(btc_returns)
    daily = {
        'ETH': _daily_from_returns(1.2 * btc_returns + .004),
        'SOL': _daily_from_returns(1.0 * btc_returns - .004),
        'BNB': _daily_from_returns(.8 * btc_returns),
    }
    return daily, btc


def _bars(periods=5):
    index = pd.date_range('2025-03-17', periods=periods, freq='5min', tz=UTC)
    return pd.DataFrame({
        'open': np.full(periods, 100.0),
        'high': np.full(periods, 101.0),
        'low': np.full(periods, 99.0),
        'close': np.full(periods, 100.0),
    }, index=index)


def _target(timestamp):
    return {
        'timestamp': timestamp,
        'long_symbol': 'ETH',
        'short_symbol': 'SOL',
        'long_weight': .5,
        'short_weight': .5,
        'long_beta': 1.0,
        'short_beta': 1.0,
        'net_beta': 0.0,
        'pair_volatility_28d': .02,
        'stop_gross_fraction': .05,
        'scores': {},
    }


class XSMTargetTests(unittest.TestCase):
    def test_ranking_is_sign_filtered_and_exactly_beta_neutral(self):
        daily, btc = _ranking_fixture()
        decision = pd.Timestamp('2025-03-17', tz=UTC)
        targets = weekly_xsm_targets(
            daily, btc, decision, decision + pd.Timedelta(days=7),
            symbol_order=('ETH', 'SOL', 'BNB'),
        )
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual((target['long_symbol'], target['short_symbol']), ('ETH', 'SOL'))
        self.assertGreater(target['scores']['ETH']['return_28d'], 0)
        self.assertLess(target['scores']['SOL']['return_28d'], 0)
        self.assertAlmostEqual(target['net_beta'], 0.0, places=12)

    def test_daily_candle_not_closed_before_decision_cannot_leak(self):
        daily, btc = _ranking_fixture()
        decision = pd.Timestamp('2025-03-17', tz=UTC)
        baseline = weekly_xsm_targets(
            daily, btc, decision, decision + pd.Timedelta(days=7),
            symbol_order=('ETH', 'SOL', 'BNB'),
        )
        # The row opened at decision closes the next day.  Even an absurd
        # value there must not alter Monday's selection.
        for frame in daily.values():
            frame.loc[decision, 'close'] *= 1_000
        repeated = weekly_xsm_targets(
            daily, btc, decision, decision + pd.Timedelta(days=7),
            symbol_order=('ETH', 'SOL', 'BNB'),
        )
        self.assertEqual(baseline, repeated)

    def test_no_pair_when_cross_section_does_not_straddle_zero(self):
        daily, btc = _ranking_fixture()
        positive = {}
        btc_returns = np.log(btc.close).diff().dropna().to_numpy()
        for rank, symbol in enumerate(('ETH', 'SOL', 'BNB')):
            positive[symbol] = _daily_from_returns(
                (1.2 - rank * .1) * btc_returns + (.004 - rank * .0005))
        decision = pd.Timestamp('2025-03-17', tz=UTC)
        self.assertEqual(weekly_xsm_targets(
            positive, btc, decision, decision + pd.Timedelta(days=7),
            symbol_order=('ETH', 'SOL', 'BNB')),
            [])


class XSMSimulatorTests(unittest.TestCase):
    def _markets(self, bars, funding=None):
        empty = pd.Series(dtype=float)
        funding = funding or {}
        return {
            symbol: (frame, funding.get(symbol, empty))
            for symbol, frame in bars.items()
        }

    def test_both_legs_share_one_ledger_and_book_all_costs_and_funding(self):
        frames = {symbol: _bars() for symbol in ('ETH', 'SOL', 'BNB')}
        start, end = frames['ETH'].index[0], frames['ETH'].index[-1] + pd.Timedelta(minutes=5)
        funding_time = frames['ETH'].index[1]
        rates = {
            'ETH': pd.Series([.001], index=pd.DatetimeIndex([funding_time])),
            'SOL': pd.Series([.002], index=pd.DatetimeIndex([funding_time])),
        }
        config = replace(XSMConfig(), costs=XSMCosts(5.0, 0.0))
        result = simulate_xsm_pairs(
            self._markets(frames, rates), [_target(start)], start, end, config)
        self.assertEqual(result['summary']['episodes'], 1)
        episode = result['episodes'][0]
        # Gross is $25: $12.50 long pays 1bp-of-price rate and $12.50 short
        # receives twice that.  Entry+exit taker fees cost 10 bps of gross.
        self.assertAlmostEqual(episode['funding_pnl'], .0125, places=8)
        self.assertAlmostEqual(episode['total_fees'], .025, places=8)
        self.assertAlmostEqual(episode['pnl'], -.0125, places=8)
        self.assertEqual(len(result['episodes']), 1)

    def test_intrabar_wicks_do_not_trigger_pair_stop(self):
        frames = {symbol: _bars() for symbol in ('ETH', 'SOL', 'BNB')}
        frames['ETH'].iloc[1, frames['ETH'].columns.get_loc('low')] = 10.0
        frames['SOL'].iloc[1, frames['SOL'].columns.get_loc('high')] = 1_000.0
        start, end = frames['ETH'].index[0], frames['ETH'].index[-1] + pd.Timedelta(minutes=5)
        result = simulate_xsm_pairs(
            self._markets(frames), [_target(start)], start, end,
            replace(XSMConfig(), costs=XSMCosts(0, 0)))
        self.assertEqual(result['episodes'][0]['reason'], 'END_OF_TEST')

    def test_close_confirmed_stop_executes_at_next_bar_open(self):
        frames = {symbol: _bars() for symbol in ('ETH', 'SOL', 'BNB')}
        start = frames['ETH'].index[0]
        # At bar 1 close, the long loses $2.50 on a $12.50 leg; this exceeds
        # the $1.25 account risk.  The fill must be bar 2 open, not bar 1 close.
        frames['ETH'].iloc[1, frames['ETH'].columns.get_loc('close')] = 80.0
        frames['ETH'].iloc[1, frames['ETH'].columns.get_loc('low')] = 80.0
        frames['ETH'].iloc[2, frames['ETH'].columns.get_loc('open')] = 79.0
        frames['ETH'].iloc[2, frames['ETH'].columns.get_loc('low')] = 79.0
        end = frames['ETH'].index[-1] + pd.Timedelta(minutes=5)
        result = simulate_xsm_pairs(
            self._markets(frames), [_target(start)], start, end,
            replace(XSMConfig(), costs=XSMCosts(0, 0)))
        episode = result['episodes'][0]
        self.assertEqual(episode['reason'], 'STOP')
        self.assertEqual(episode['closed_at'], frames['ETH'].index[2])
        self.assertEqual(episode['long_exit'], 79.0)

    def test_simulator_refuses_to_silently_clip_non_neutral_weights(self):
        frames = {symbol: _bars() for symbol in ('ETH', 'SOL', 'BNB')}
        start = frames['ETH'].index[0]
        target = _target(start)
        target.update(long_weight=.7, short_weight=.3, net_beta=.4)
        with self.assertRaisesRegex(ValueError, 'not beta-neutral'):
            simulate_xsm_pairs(
                self._markets(frames), [target], start,
                frames['ETH'].index[-1] + pd.Timedelta(minutes=5),
                replace(XSMConfig(), costs=XSMCosts(0, 0)))


if __name__ == '__main__':
    unittest.main()
