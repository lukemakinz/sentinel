"""Frozen historical research runner for S47 OI State Transition."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from l1_filter.oi_state_transition_scalp import (
    OIStateTransitionConfig,
    build_oi_state_transition_features,
    generate_oi_state_transition_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import MetricsDataIntegrityError, load_metrics
from .scalp_data import MarketDataIntegrityError, load_archives


def load_frozen_protocol(path: str | Path) -> tuple[dict, str]:
    """Verify the registered digest before parsing any research settings."""
    path = Path(path)
    checksum_path = path.with_suffix('.sha256')
    if not path.exists() or not checksum_path.exists():
        raise FileNotFoundError('Frozen protocol and checksum are required')
    payload = path.read_bytes()
    actual = sha256(payload).hexdigest()
    expected = checksum_path.read_text().split()[0]
    if actual != expected:
        raise ValueError('Frozen protocol hash mismatch')
    return json.loads(payload), actual


def effective_fold_windows(protocol: dict) -> list[dict]:
    delta = pd.Timedelta(hours=float(protocol['purge_embargo_hours']))
    windows = []
    for fold in protocol['folds']:
        start = pd.Timestamp(fold['start'], tz='UTC') + delta
        end = pd.Timestamp(fold['end'], tz='UTC') - delta
        if start >= end:
            raise ValueError(f'Fold {fold["name"]} is consumed by purge/embargo')
        windows.append({'name': fold['name'], 'start': start, 'end': end})
    return windows


def required_warmup_days(protocol: dict) -> int:
    bars = int(protocol['signal']['oi_reset_lookback_15m_bars'])
    return math.ceil(bars / (24 * 4)) + 1


def week_block_bootstrap(
    trades: list[dict],
    samples: int,
    seed: int,
    confidence: float,
) -> dict:
    if not trades:
        return {'mean': 0.0, 'lower': 0.0, 'upper': 0.0, 'blocks': 0}
    grouped: dict[tuple[int, int], list[float]] = {}
    all_values = []
    for trade in trades:
        timestamp = pd.Timestamp(trade['opened_at'])
        iso = timestamp.isocalendar()
        value = float(trade['r_multiple'])
        grouped.setdefault((iso.year, iso.week), []).append(value)
        all_values.append(value)
    blocks = [np.asarray(values, dtype=float) for _, values in sorted(grouped.items())]
    rng = np.random.default_rng(seed)
    simulated = np.empty(samples, dtype=float)
    for i in range(samples):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        simulated[i] = np.concatenate([blocks[j] for j in selected]).mean()
    alpha = (1 - confidence) / 2
    return {
        'mean': float(np.mean(all_values)),
        'lower': float(np.quantile(simulated, alpha)),
        'upper': float(np.quantile(simulated, 1 - alpha)),
        'blocks': len(blocks),
    }


def deflated_sharpe_probability(values, trials: int) -> float:
    """Bailey/Lopez de Prado-style PSR against multiple-testing SR hurdle."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3 or trials < 1:
        return 0.0
    std = values.std(ddof=1)
    if std <= 0:
        return 1.0 if values.mean() > 0 else 0.0
    sharpe = values.mean() / std
    centered = values - values.mean()
    population_std = values.std(ddof=0)
    skew = float(np.mean(centered ** 3) / population_std ** 3)
    kurtosis = float(np.mean(centered ** 4) / population_std ** 4)
    normal = NormalDist()
    if trials == 1:
        expected_max_sr = 0.0
    else:
        gamma = 0.5772156649015329
        first = normal.inv_cdf(1 - 1 / trials)
        second = normal.inv_cdf(1 - 1 / (trials * math.e))
        expected_max_sr = ((1 - gamma) * first + gamma * second) / math.sqrt(len(values) - 1)
    denominator = math.sqrt(max(
        1e-12,
        1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2,
    ))
    statistic = (
        (sharpe - expected_max_sr) * math.sqrt(len(values) - 1) / denominator)
    return float(normal.cdf(statistic))


def evaluate_gate(metrics: dict, gate: dict) -> dict:
    checks = {
        'fills': metrics['fills'] >= gate['minimum_fills'],
        'stress_profit_factor': (
            metrics['stress_profit_factor']
            > gate['minimum_stress_profit_factor_exclusive']),
        'stress_mean_net_r': (
            metrics['stress_mean_net_r']
            > gate['minimum_stress_mean_net_r_exclusive']),
        'bootstrap_lower': (
            metrics['bootstrap_lower']
            > gate['minimum_bootstrap_lower_bound_exclusive']),
        'deflated_sharpe_probability': (
            metrics['deflated_sharpe_probability']
            >= gate['minimum_deflated_sharpe_probability']),
        'positive_fold_fraction': (
            metrics['positive_fold_fraction']
            >= gate['minimum_positive_fold_fraction']),
        'leave_one_symbol_out': (
            not gate['require_positive_leave_one_symbol_out']
            or all(value > 0 for value in metrics['leave_one_symbol_out'].values())),
        'symbol_gross_profit_share': (
            metrics['symbol_gross_profit_share']
            <= gate['maximum_symbol_gross_profit_share']),
        'month_gross_profit_share': (
            metrics['month_gross_profit_share']
            <= gate['maximum_month_gross_profit_share']),
        'break_even_cost_multiple': (
            metrics['break_even_cost_multiple']
            >= gate['minimum_break_even_cost_multiple_of_stress']),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        'decision': 'PASS_TO_FORWARD' if not failed else 'REJECTED',
        'failed_conditions': failed,
        'checks': checks,
    }


def apply_data_integrity_gate(gate_result: dict, invalid_folds: dict) -> dict:
    result = {
        **gate_result,
        'failed_conditions': list(gate_result['failed_conditions']),
        'checks': dict(gate_result['checks']),
        'invalid_folds': dict(invalid_folds),
    }
    result['checks']['data_integrity_folds'] = not invalid_folds
    if invalid_folds:
        result['decision'] = 'REJECTED'
        if 'data_integrity_folds' not in result['failed_conditions']:
            result['failed_conditions'].append('data_integrity_folds')
    return result


def _scenario_execution(config: OIStateTransitionConfig, scenario: str):
    execution = config.execution()
    if scenario == 'stress':
        return replace(
            execution, maker_fee_bps=8.0, fee_bps=8.0,
            slippage_bps=5.0, limit_penetration_bps=0.0)
    if scenario == 'severe':
        return replace(
            execution, maker_fee_bps=10.0, fee_bps=10.0,
            slippage_bps=10.0, limit_penetration_bps=0.0)
    if scenario != 'base':
        raise ValueError(f'Unknown scenario: {scenario}')
    return execution


def run_fold(
    markets: dict,
    signals: dict,
    config: OIStateTransitionConfig,
    scenario: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    symbol_priority: tuple[str, ...],
) -> dict:
    return execute_cluster(
        markets,
        signals,
        _scenario_execution(config, scenario),
        start,
        end,
        initial_capital=250.0,
        symbol_priority=symbol_priority,
    )


def _profit_factor(trades: list[dict]) -> float:
    pnls = np.asarray([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    if losses == 0:
        return float('inf') if gains > 0 else 0.0
    return gains / losses


def _largest_gross_profit_share(trades: list[dict], key) -> float:
    grouped: dict[str, float] = {}
    for trade in trades:
        if trade['pnl'] <= 0:
            continue
        group = str(key(trade))
        grouped[group] = grouped.get(group, 0.0) + float(trade['pnl'])
    total = sum(grouped.values())
    return max(grouped.values()) / total if total > 0 else 1.0


def _weekly_returns(trades: list[dict]) -> np.ndarray:
    grouped: dict[tuple[int, int], float] = {}
    for trade in trades:
        timestamp = pd.Timestamp(trade['opened_at'])
        iso = timestamp.isocalendar()
        key = (iso.year, iso.week)
        grouped[key] = grouped.get(key, 0.0) + float(trade['r_multiple'])
    return np.asarray([grouped[key] for key in sorted(grouped)], dtype=float)


def _break_even_round_trip_bps(trades: list[dict], slippage_per_side: float) -> float:
    gross_bps = []
    for trade in trades:
        notional = float(trade['quantity']) * float(trade['entry'])
        if notional <= 0:
            continue
        after_slip = (
            float(trade['gross_pnl']) + float(trade.get('funding_pnl', 0.0))
        ) / notional * 10000
        gross_bps.append(after_slip + 2 * slippage_per_side)
    return float(np.mean(gross_bps)) if gross_bps else 0.0


def _config_from_protocol(protocol: dict) -> OIStateTransitionConfig:
    signal = protocol['signal']
    return OIStateTransitionConfig(
        pivot_width=int(signal['four_hour_pivot_width']),
        sweep_penetration_atr_1h=float(signal['sweep_penetration_atr_1h']),
        stop_buffer_atr_1h=float(signal['stop_buffer_atr_1h']),
        oi_reset_floor_fraction=float(signal['oi_reset_floor_fraction']),
        oi_reset_quantile=float(signal['oi_reset_quantile']),
        oi_reset_lookback_bars=int(signal['oi_reset_lookback_15m_bars']),
        oi_rebuild_fraction=float(signal['oi_rebuild_fraction']),
        confirmation_expiry_bars=int(signal['confirmation_expiry_15m_bars']),
        displacement_body_atr_15m=float(signal['displacement_body_atr_15m']),
        confirmation_close_location=float(signal['confirmation_close_location']),
        metrics_max_age_minutes=float(protocol['data']['metrics_max_age_minutes']),
        target_r=float(signal['target_r']),
        minimum_target_r=float(signal['minimum_capped_target_r']),
    )


def _json_safe(value):
    if isinstance(value, float) and not np.isfinite(value):
        return 'Infinity' if value > 0 else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _render_report(summary: dict) -> str:
    gate = summary['gate']
    metrics = summary['historical_metrics']
    lines = [
        '# S47 — OI State Transition',
        '',
        f'Protocol SHA-256: `{summary["protocol_sha256"]}`.',
        '',
        '**Discovery-affected historical characterization; not approval for live trading.**',
        '',
        f'Decision: **{gate["decision"]}**.',
        f'Failed conditions: {", ".join(gate["failed_conditions"]) or "none"}.',
        f'Invalid folds: {gate.get("invalid_folds", {}) or "none"}.',
        '',
        '## Historical gate metrics',
        '',
        f'- Fills: {metrics["fills"]}',
        f'- Stress PF: {metrics["stress_profit_factor"]}',
        f'- Stress mean net R: {metrics["stress_mean_net_r"]:.6f}',
        f'- Weekly block-bootstrap 95% CI: '
        f'[{metrics["bootstrap_lower"]:.6f}, {metrics["bootstrap_upper"]:.6f}]',
        f'- Deflated Sharpe Probability: '
        f'{metrics["deflated_sharpe_probability"]:.6f}',
        f'- Positive fold fraction: {metrics["positive_fold_fraction"]:.3f}',
        f'- Largest symbol gross-profit share: '
        f'{metrics["symbol_gross_profit_share"]:.3f}',
        f'- Largest month gross-profit share: '
        f'{metrics["month_gross_profit_share"]:.3f}',
        f'- Break-even/stress cost multiple: '
        f'{metrics["break_even_cost_multiple"]:.3f}',
        '',
        'No thresholds were changed after observing these results.',
        '',
    ]
    return '\n'.join(lines)


def run_historical(
    protocol: dict,
    protocol_digest: str,
    cache: str | Path,
    output: str | Path,
) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    config = _config_from_protocol(protocol)
    priority = tuple(protocol['universe']['symbol_priority'])
    manifest: dict[str, dict] = {'folds': {}}
    fold_results = {}
    scenario_trades: dict[str, list[dict]] = {
        'base': [], 'stress': [], 'severe': []}
    leave_one_totals = {symbol: 0.0 for symbol in priority}
    invalid_folds: dict[str, str] = {}

    warmup_floor = pd.Timestamp(protocol['data']['warmup_start'], tz='UTC')
    for window in effective_fold_windows(protocol):
        load_start = max(
            warmup_floor,
            window['start'] - pd.Timedelta(days=required_warmup_days(protocol)),
        )
        markets = {}
        signals = {}
        fold_manifest = {}
        try:
            for symbol in priority:
                minutes, funding, price_manifest = load_archives(
                    symbol, str(load_start), str(window['end']), str(cache),
                    repair_from_daily=True)
                metrics, metrics_manifest = load_metrics(
                    symbol, str(load_start), str(window['end']), str(cache),
                    include_freshness=True,
                    required_columns=('open_interest',),
                )
                features = build_oi_state_transition_features(minutes, metrics, config)
                signals[symbol] = generate_oi_state_transition_signals(
                    features, config, symbol)
                markets[symbol] = (minutes, funding)
                fold_manifest[symbol] = {
                    'klines_funding': price_manifest,
                    'metrics': metrics_manifest,
                    'raw_signals': len(signals[symbol]),
                }
        except (MarketDataIntegrityError, MetricsDataIntegrityError) as error:
            invalid_folds[window['name']] = str(error)
            manifest['folds'][window['name']] = {
                'status': 'INVALID_DATA_INTEGRITY',
                'error': str(error),
                'loaded_before_failure': fold_manifest,
            }
            fold_results[window['name']] = {
                'status': 'INVALID_DATA_INTEGRITY'}
            continue
        manifest['folds'][window['name']] = fold_manifest
        fold_results[window['name']] = {}
        for scenario in ('base', 'stress', 'severe'):
            result = run_fold(
                markets, signals, config, scenario,
                window['start'], window['end'], priority)
            fold_results[window['name']][scenario] = result['summary']
            scenario_trades[scenario].extend(result['trades'])
            payload = json.dumps(result['trades'], allow_nan=False).encode()
            path = output / f'{window["name"]}_{scenario}_trades.json.gz'
            path.write_bytes(gzip.compress(payload, mtime=0))

        for omitted in priority:
            reduced_markets = {
                symbol: value for symbol, value in markets.items()
                if symbol != omitted}
            reduced_signals = {
                symbol: value for symbol, value in signals.items()
                if symbol != omitted}
            result = run_fold(
                reduced_markets, reduced_signals, config, 'stress',
                window['start'], window['end'],
                tuple(symbol for symbol in priority if symbol != omitted))
            leave_one_totals[omitted] += float(result['summary']['net_pnl'])

    stress_trades = scenario_trades['stress']
    bootstrap = week_block_bootstrap(
        stress_trades,
        samples=int(protocol['statistics']['bootstrap_samples']),
        seed=int(protocol['statistics']['bootstrap_seed']),
        confidence=float(protocol['statistics']['confidence']),
    )
    stress_cost = protocol['cost_scenarios_bps_per_side']['stress']
    stress_round_trip = 2 * (
        float(stress_cost['taker_fee']) + float(stress_cost['slippage']))
    break_even = _break_even_round_trip_bps(
        stress_trades, float(stress_cost['slippage']))
    stress_fold_pnls = [
        (0.0 if window['name'] in invalid_folds
         else float(fold_results[window['name']]['stress']['net_pnl']))
        for window in effective_fold_windows(protocol)
    ]
    metrics = {
        'fills': len(stress_trades),
        'stress_profit_factor': _profit_factor(stress_trades),
        'stress_mean_net_r': (
            float(np.mean([trade['r_multiple'] for trade in stress_trades]))
            if stress_trades else 0.0),
        'bootstrap_lower': bootstrap['lower'],
        'bootstrap_upper': bootstrap['upper'],
        'bootstrap_blocks': bootstrap['blocks'],
        'deflated_sharpe_probability': deflated_sharpe_probability(
            _weekly_returns(stress_trades),
            int(protocol['statistics']['deflated_sharpe_prior_trials']),
        ),
        'positive_fold_fraction': float(
            np.mean(np.asarray(stress_fold_pnls) > 0)),
        'leave_one_symbol_out': leave_one_totals,
        'symbol_gross_profit_share': _largest_gross_profit_share(
            stress_trades, lambda trade: trade['symbol']),
        'month_gross_profit_share': _largest_gross_profit_share(
            stress_trades,
            lambda trade: pd.Timestamp(trade['opened_at']).strftime('%Y-%m')),
        'break_even_round_trip_bps': break_even,
        'stress_round_trip_cost_bps': stress_round_trip,
        'break_even_cost_multiple': (
            break_even / stress_round_trip if stress_round_trip > 0 else 0.0),
    }
    gate = apply_data_integrity_gate(
        evaluate_gate(metrics, protocol['historical_gate']),
        invalid_folds,
    )
    summary = _json_safe({
        'protocol_sha256': protocol_digest,
        'disclosure': (
            'discovery-affected historical characterization; '
            'not approval for live trading'),
        'config': asdict(config),
        'folds': fold_results,
        'historical_metrics': metrics,
        'gate': gate,
    })
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    (output / 'summary.json').write_text(
        json.dumps(summary, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--protocol',
        default='docs/research/s47_oi_state_transition/protocol.json')
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument(
        '--output', default='docs/research/s47_oi_state_transition')
    args = parser.parse_args()

    # This verification intentionally precedes every data-loader call.
    protocol, digest = load_frozen_protocol(args.protocol)
    summary = run_historical(protocol, digest, args.cache, args.output)
    print(json.dumps({
        'decision': summary['gate']['decision'],
        'failed_conditions': summary['gate']['failed_conditions'],
        'fills': summary['historical_metrics']['fills'],
    }, indent=2))


if __name__ == '__main__':
    main()
