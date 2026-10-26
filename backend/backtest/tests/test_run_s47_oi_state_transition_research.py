from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import requests

from backtest.run_s47_oi_state_transition_research import (
    apply_data_integrity_gate,
    deflated_sharpe_probability,
    effective_fold_windows,
    evaluate_gate,
    load_frozen_protocol,
    run_fold,
    required_warmup_days,
    week_block_bootstrap,
)
from backtest.scalp_data import _get_with_read_retries, _repair_missing_minutes
from l1_filter.oi_state_transition_scalp import OIStateTransitionConfig


class S47RunnerModuleTests(unittest.TestCase):
    def test_runner_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec(
            'backtest.run_s47_oi_state_transition_research'))

    def test_protocol_hash_is_verified_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol_path = Path(directory) / 'protocol.json'
            payload = {'strategy_id': 'S47', 'folds': []}
            protocol_path.write_text(json.dumps(payload))
            digest = sha256(protocol_path.read_bytes()).hexdigest()
            protocol_path.with_suffix('.sha256').write_text(
                f'{digest}  protocol.json\n')

            loaded, loaded_digest = load_frozen_protocol(protocol_path)

            self.assertEqual(loaded, payload)
            self.assertEqual(loaded_digest, digest)
            protocol_path.write_text(json.dumps({'strategy_id': 'tampered'}))
            with self.assertRaises(ValueError):
                load_frozen_protocol(protocol_path)

    def test_fold_windows_apply_twenty_four_hour_purge_and_embargo(self):
        protocol = {
            'purge_embargo_hours': 24,
            'folds': [{
                'name': 'fold',
                'start': '2025-01-01',
                'end': '2025-02-01',
            }],
        }

        windows = effective_fold_windows(protocol)

        self.assertEqual(windows[0]['start'], pd.Timestamp('2025-01-02', tz='UTC'))
        self.assertEqual(windows[0]['end'], pd.Timestamp('2025-01-31', tz='UTC'))

    def test_warmup_is_derived_from_frozen_oi_lookback(self):
        protocol = {'signal': {'oi_reset_lookback_15m_bars': 2880}}
        self.assertEqual(required_warmup_days(protocol), 31)

    def test_week_block_bootstrap_is_deterministic(self):
        trades = [
            {'opened_at': '2025-01-01T00:00:00+00:00', 'r_multiple': 1.0},
            {'opened_at': '2025-01-02T00:00:00+00:00', 'r_multiple': -0.5},
            {'opened_at': '2025-01-08T00:00:00+00:00', 'r_multiple': 2.0},
            {'opened_at': '2025-01-09T00:00:00+00:00', 'r_multiple': -0.25},
        ]

        first = week_block_bootstrap(trades, samples=200, seed=47, confidence=0.95)
        second = week_block_bootstrap(trades, samples=200, seed=47, confidence=0.95)

        self.assertEqual(first, second)
        self.assertAlmostEqual(first['mean'], 0.5625)
        self.assertLessEqual(first['lower'], first['mean'])
        self.assertGreaterEqual(first['upper'], first['mean'])

    def test_deflated_sharpe_rewards_stable_positive_returns(self):
        stable = np.array([0.4, 0.5, 0.3, 0.6] * 20)
        noisy = np.array([1.0, -1.0] * 40)
        self.assertGreater(
            deflated_sharpe_probability(stable, trials=48),
            deflated_sharpe_probability(noisy, trials=48),
        )

    def test_gate_requires_every_frozen_condition(self):
        passing = {
            'fills': 120,
            'stress_profit_factor': 1.2,
            'stress_mean_net_r': 0.1,
            'bootstrap_lower': 0.01,
            'deflated_sharpe_probability': 0.97,
            'positive_fold_fraction': 5 / 6,
            'leave_one_symbol_out': {'SOLUSDT': 1.0, 'XRPUSDT': 0.5},
            'symbol_gross_profit_share': 0.35,
            'month_gross_profit_share': 0.30,
            'break_even_cost_multiple': 1.6,
        }
        gate = {
            'minimum_fills': 100,
            'minimum_stress_profit_factor_exclusive': 1.1,
            'minimum_stress_mean_net_r_exclusive': 0.0,
            'minimum_bootstrap_lower_bound_exclusive': 0.0,
            'minimum_deflated_sharpe_probability': 0.95,
            'minimum_positive_fold_fraction': 0.7,
            'require_positive_leave_one_symbol_out': True,
            'maximum_symbol_gross_profit_share': 0.4,
            'maximum_month_gross_profit_share': 0.4,
            'minimum_break_even_cost_multiple_of_stress': 1.5,
        }

        self.assertEqual(evaluate_gate(passing, gate)['decision'], 'PASS_TO_FORWARD')
        failing = dict(passing, stress_profit_factor=1.1)
        result = evaluate_gate(failing, gate)
        self.assertEqual(result['decision'], 'REJECTED')
        self.assertIn('stress_profit_factor', result['failed_conditions'])

    def test_invalid_fold_forces_rejection_without_hiding_other_metrics(self):
        result = apply_data_integrity_gate(
            {'decision': 'PASS_TO_FORWARD', 'failed_conditions': [], 'checks': {}},
            {'fold_2021': 'missing exact candles'},
        )
        self.assertEqual(result['decision'], 'REJECTED')
        self.assertIn('data_integrity_folds', result['failed_conditions'])
        self.assertEqual(result['invalid_folds']['fold_2021'], 'missing exact candles')

    def test_fold_execution_uses_one_position_and_symbol_priority(self):
        start = pd.Timestamp('2025-01-01', tz='UTC')
        end = start + pd.Timedelta(minutes=10)
        index = pd.date_range(start, end - pd.Timedelta(minutes=1), freq='1min')

        def market():
            return pd.DataFrame({
                'open': 100.0,
                'high': 100.2,
                'low': 99.8,
                'close': 100.0,
                'volume': 10.0,
                'taker_buy_volume': 5.0,
            }, index=index), pd.Series(dtype=float)

        signal = {
            'timestamp': start,
            'side': 1,
            'reference': 100.0,
            'stop': 98.0,
            'target_price': 110.0,
            'atr': 1.0,
            'min_stop_atr': 0.5,
            'max_stop_atr': 3.0,
            'score': 0,
            'setup': 'test',
            'setup_id': 'test',
        }
        markets = {'SOLUSDT': market(), 'XRPUSDT': market()}
        signals = {'SOLUSDT': [signal], 'XRPUSDT': [dict(signal)]}

        result = run_fold(
            markets, signals, OIStateTransitionConfig(), 'base',
            start, end, ('SOLUSDT', 'XRPUSDT'))

        self.assertEqual(result['summary']['trades'], 1)
        self.assertEqual(result['trades'][0]['symbol'], 'SOLUSDT')

    def test_missing_month_boundary_is_repaired_only_from_exact_daily_candle(self):
        start = pd.Timestamp('2021-01-01', tz='UTC')
        end = start + pd.Timedelta(minutes=3)
        index = pd.date_range(
            start + pd.Timedelta(minutes=1),
            end - pd.Timedelta(minutes=1),
            freq='1min',
        )

        def rows(row_index):
            return pd.DataFrame({
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.0,
                'volume': 10.0,
                'taker_buy_volume': 5.0,
            }, index=row_index)

        frame = rows(index)

        repaired, sources = _repair_missing_minutes(
            frame, start, end,
            lambda day: (rows(pd.DatetimeIndex([start])),
                         {'url': f'daily:{day}', 'sha256': 'abc', 'rows': 1}),
        )

        self.assertTrue(repaired.index.equals(
            pd.date_range(start, end - pd.Timedelta(minutes=1), freq='1min')))
        self.assertEqual(sources[0]['url'], 'daily:2021-01-01')

    def test_daily_source_that_lacks_gap_does_not_interpolate(self):
        start = pd.Timestamp('2021-01-01', tz='UTC')
        end = start + pd.Timedelta(minutes=2)
        frame = pd.DataFrame({
            'open': [100.0],
            'high': [101.0],
            'low': [99.0],
            'close': [100.0],
            'volume': [10.0],
            'taker_buy_volume': [5.0],
        }, index=pd.DatetimeIndex([start + pd.Timedelta(minutes=1)]))

        with self.assertRaises(ValueError):
            _repair_missing_minutes(
                frame, start, end,
                lambda day: (frame.iloc[0:0], {'url': str(day)}),
            )

    def test_download_retries_connection_error_while_reading_content(self):
        class Response:
            content = b'ok'

        class Session:
            def __init__(self):
                self.calls = 0

            def get(self, url, timeout):
                self.calls += 1
                if self.calls < 3:
                    raise requests.ConnectionError('read timed out')
                return Response()

        session = Session()
        response = _get_with_read_retries(
            session, 'https://example.test/file', timeout=1,
            attempts=3, sleeper=lambda seconds: None)

        self.assertEqual(response.content, b'ok')
        self.assertEqual(session.calls, 3)

    def test_download_raises_after_retry_budget_is_exhausted(self):
        class Session:
            def get(self, url, timeout):
                raise requests.Timeout('still unavailable')

        with self.assertRaises(requests.Timeout):
            _get_with_read_retries(
                Session(), 'https://example.test/file', timeout=1,
                attempts=2, sleeper=lambda seconds: None)
