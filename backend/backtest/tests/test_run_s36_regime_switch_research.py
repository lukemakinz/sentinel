from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd
import pytest

import backtest.run_s36_regime_switch_research as runner


def _trades(count, start, pnl=.10, r_multiple=.20):
    start = pd.Timestamp(start, tz='UTC')
    output = []
    for number in range(count):
        output.append({
            'closed_at': str(start + pd.Timedelta(hours=number)),
            'symbol': runner.SYMBOLS[number % len(runner.SYMBOLS)],
            'regime': runner.REGIMES[number % len(runner.REGIMES)],
            'side': runner.DIRECTIONS[number % len(runner.DIRECTIONS)],
            'pnl': pnl,
            'r_multiple': r_multiple,
        })
    return output


def _window_result(trades):
    return {
        'summary': {
            'trades': len(trades),
            'net_pnl': sum(row['pnl'] for row in trades),
            'profit_factor': 'Infinity' if trades else None,
            'max_drawdown_pct': 0.0,
            'risk_fail': False,
            'daily_pnl': {},
            'diagnostics': {},
        },
        'trades': trades,
        'candidates': [],
        'invalidated_candidates': [],
    }


def _passing_results():
    return {'stress': {
        'development': _window_result(
            _trades(60, '2022-01-01')),
        'validation': _window_result(
            _trades(40, '2023-07-01')),
        'retrospective_evaluation': _window_result(
            _trades(60, '2024-07-01')),
    }}


def test_protocol_hash_mismatch_is_detected():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        output = Path(directory)
        (output / 'protocol.json').write_text('{"frozen": true}\n')
        (output / 'protocol.sha256').write_text('0' * 64 + '  protocol.json\n')
        with pytest.raises(ValueError, match='hash mismatch'):
            runner._verify_protocol_hash(output)


def test_bad_hash_aborts_main_before_any_data_load(tmp_path, monkeypatch):
    (tmp_path / 'protocol.json').write_text('{"frozen": true}\n')
    (tmp_path / 'protocol.sha256').write_text('0' * 64 + '  protocol.json\n')
    monkeypatch.setattr(
        sys, 'argv', ['runner', '--output', str(tmp_path)])
    with patch.object(runner, 'load_s36_universe') as load:
        with pytest.raises(ValueError, match='hash mismatch'):
            runner.main()
        load.assert_not_called()


def test_calendar_daily_keeps_zero_trade_days_and_months():
    result = {'summary': {'daily_pnl': {'2024-01-02': 9.0}}}
    daily = runner._calendar_daily(
        result, '2024-01-01', '2024-01-04')
    assert daily.tolist() == [0.0, 9.0, 0.0]

    diagnostics = runner._daily_diagnostics(
        result, '2024-01-01', '2024-01-04')
    assert diagnostics['calendar_days'] == 3
    assert diagnostics['mean_daily_pnl_usd'] == pytest.approx(3.0)
    assert diagnostics['median_daily_pnl_usd'] == 0.0
    assert diagnostics['share_days_at_least_25_pct'] == 0.0
    assert diagnostics['monthly_pnl_usd'] == {'2024-01': 9.0}


def test_week_block_bootstrap_preserves_constant_daily_mean():
    daily = pd.Series(
        25.0,
        index=pd.date_range('2024-01-01', periods=15, freq='D', tz='UTC'))
    lower = runner._daily_block_bootstrap_lower(
        daily, seed=1, samples=100)
    assert lower == pytest.approx(25.0)


def test_edge_gate_passes_only_when_every_frozen_clause_passes():
    decision = runner._edge_decision(_passing_results())
    assert decision['status'] == 'EDGE_PASS'
    assert decision['reasons'] == []
    assert decision['validation_evaluation_mean_net_r'] == pytest.approx(.20)
    assert (
        decision['validation_evaluation_trade_mean_pnl_bootstrap_lower_95']
        == pytest.approx(.10))
    assert all(
        row['trades'] == 20
        for row in decision['validation_evaluation_breakdown'][
            'per_symbol'].values())


def test_edge_gate_reports_sample_regime_symbol_and_direction_failures():
    empty = {'stress': {
        window: _window_result([]) for window in runner.WINDOWS
    }}
    decision = runner._edge_decision(empty)
    assert decision['status'] == 'EDGE_FAIL'
    assert 'development:trades<60' in decision['reasons']
    assert 'validation_evaluation:mean_net_R<0.05' in decision['reasons']
    assert 'FADE:trades<25' in decision['reasons']
    assert 'CONTINUATION:net<=0' in decision['reasons']
    assert 'fewer_than_3_positive_symbols_with_10_trades' in decision['reasons']
    assert 'LONG:trade_share<20pct' in decision['reasons']
    assert 'SHORT:trade_share<20pct' in decision['reasons']


def test_income_gate_is_independent_and_inclusive_at_25():
    daily = {'stress': {
        'validation': {
            'mean_daily_pnl_usd': 25.0,
            'lower_95_week_block_bootstrap_mean_daily_pnl_usd': 25.0,
        },
        'retrospective_evaluation': {
            'mean_daily_pnl_usd': 25.0,
            'lower_95_week_block_bootstrap_mean_daily_pnl_usd': 25.0,
        },
    }}
    assert runner._income_decision(daily)['status'] == 'INCOME_TARGET_PASS'
    daily['stress']['validation']['mean_daily_pnl_usd'] = 24.99
    decision = runner._income_decision(daily)
    assert decision['status'] == 'INCOME_TARGET_FAIL'
    assert decision['reasons'] == ['validation:mean_daily<25']


def test_main_builds_candidates_once_reuses_them_and_drops_equity(
        tmp_path, monkeypatch):
    protocol = b'{"frozen": true}\n'
    digest = sha256(protocol).hexdigest()
    (tmp_path / 'protocol.json').write_bytes(protocol)
    (tmp_path / 'protocol.sha256').write_text(
        f'{digest}  protocol.json\n')
    monkeypatch.setattr(sys, 'argv', [
        'runner', '--output', str(tmp_path), '--cache', '/unused'])

    candidates = [{'setup_id': 'immutable-candidate'}]
    replay = {
        'summary': {'trades': 0, 'net_pnl': 0.0},
        'trades': [], 'candidates': [], 'invalidated_candidates': [],
        'equity_curve': [{'timestamp': 'x', 'equity': 250.0}],
    }
    with (
        patch.object(runner, 'load_s36_universe',
                     return_value=({}, {'source': 'fixture'})) as load,
        patch.object(runner, 'build_funding_regime_candidates',
                     return_value=candidates) as build,
        patch.object(runner, 'simulate_funding_regime_switch_portfolio',
                     side_effect=lambda *_args, **_kwargs: {
                         key: (value.copy() if isinstance(value, list) else value.copy())
                         for key, value in replay.items()
                     }) as simulate,
        patch.object(runner, '_daily_diagnostics', return_value={}),
        patch.object(runner, '_edge_decision',
                     return_value={'status': 'EDGE_FAIL', 'reasons': []}),
        patch.object(runner, '_income_decision',
                     return_value={'status': 'INCOME_TARGET_FAIL', 'reasons': []}),
        patch.object(runner, '_result_diagnostics', return_value={}),
        patch.object(runner, '_report', return_value='# report\n')
    ):
        runner.main()

    load.assert_called_once()
    build.assert_called_once()
    assert simulate.call_count == 6
    assert all(call.args[1] is candidates for call in simulate.call_args_list)
    payload = json.loads((tmp_path / 'results.json').read_text())
    assert payload['protocol_sha256'] == digest
    assert all(
        'equity_curve' not in payload['results'][scenario][window]
        for scenario in ('base', 'stress') for window in runner.WINDOWS)
    assert json.loads((tmp_path / 'manifest.json').read_text()) == {
        'source': 'fixture'}

