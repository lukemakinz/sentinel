"""S120: walk-forward entry-policy lab on the frozen S20 OB+OI stream.

Usage:
    PYTHONPATH=. ../env/bin/python -m backtest.run_s120_s20_entry_lab_v1
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
    oi_features,
)
from l1_filter.s20_entry_lab import (
    ENTRY_POLICIES,
    S20EntryLabConfig,
    build_s20_entry_variants,
)
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .scalp_data import load_archives


ROOT = Path(__file__).resolve().parents[2]
TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-09-01'
FOLDS = (
    {
        'name': 'fold_1',
        'train': ('2025-08-01', '2026-02-01'),
        'test': ('2026-02-01', '2026-04-01'),
    },
    {
        'name': 'fold_2',
        'train': ('2025-08-01', '2026-04-01'),
        'test': ('2026-04-01', '2026-09-01'),
    },
)


def parent_config() -> OrderBlockOIConfig:
    return OrderBlockOIConfig(
        'S120_S20_ENTRY_LAB_V1', 'oi',
        partial_r=1.5, trail_atr=2.5, target_r=8.0,
    )


def _execution(config: OrderBlockOIConfig, scenario: str):
    execution = config.execution()
    if scenario == 'stress':
        return replace(
            execution, maker_fee_bps=5.0, fee_bps=8.0,
            slippage_bps=5.0, limit_penetration_bps=5.0,
        )
    if scenario == 'severe':
        return replace(
            execution, maker_fee_bps=10.0, fee_bps=10.0,
            slippage_bps=10.0, limit_penetration_bps=10.0,
        )
    return execution


def _run(markets, signals, config, scenario, window):
    result = execute_cluster(
        markets, signals, _execution(config, scenario), *window,
        initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary'], result['trades']


def _pf(summary: dict) -> float:
    value = summary['profit_factor']
    return float('inf') if value == 'Infinity' else float(value or 0.0)


def _eligible(summary: dict) -> bool:
    return (
        summary['trades'] >= 40
        and summary['net_pnl'] > 0
        and _pf(summary) > 1.05
        and summary['mean_net_r'] > 0
    )


def _select(train: dict) -> str:
    candidates = [policy for policy in ENTRY_POLICIES if _eligible(train[policy])]
    if not candidates:
        return 'CASH'
    order = {policy: i for i, policy in enumerate(ENTRY_POLICIES)}
    return max(
        candidates,
        key=lambda policy: (
            train[policy]['mean_net_r'], _pf(train[policy]), -order[policy],
        ),
    )


def _bootstrap_day_lower(trades: list[dict], alpha: float = 0.0125) -> float | None:
    if not trades:
        return None
    by_day: dict[str, list[float]] = {}
    for trade in trades:
        day = str(pd.Timestamp(trade['opened_at']).date())
        by_day.setdefault(day, []).append(float(trade['r_multiple']))
    clusters = [np.asarray(values, dtype=float) for _, values in sorted(by_day.items())]
    rng = np.random.default_rng(120)
    means = np.empty(5000, dtype=float)
    for rep in range(len(means)):
        picks = rng.integers(0, len(clusters), len(clusters))
        sample = np.concatenate([clusters[i] for i in picks])
        means[rep] = sample.mean()
    return float(np.quantile(means, alpha))


def _combine(summaries: list[dict], trades: list[dict]) -> dict:
    pnl = np.asarray([float(trade['pnl']) for trade in trades], dtype=float)
    r_values = np.asarray([float(trade['r_multiple']) for trade in trades], dtype=float)
    gains = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    losses = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
    return {
        'trades': len(trades),
        'net_pnl': float(pnl.sum()) if len(pnl) else 0.0,
        'profit_factor': (
            gains / losses if losses else ('Infinity' if gains else None)
        ),
        'mean_net_r': float(r_values.mean()) if len(r_values) else 0.0,
        'win_rate_pct': float((pnl > 0).mean() * 100) if len(pnl) else 0.0,
        'test_fold_pnl': [float(summary['net_pnl']) for summary in summaries],
        'bootstrap_day_lower_98_75_pct': _bootstrap_day_lower(trades),
    }


def _passes_oos(summary: dict) -> bool:
    lower = summary['bootstrap_day_lower_98_75_pct']
    return (
        summary['trades'] >= 40
        and summary['net_pnl'] > 0
        and _pf(summary) > 1.0
        and summary['mean_net_r'] > 0
        and all(value > 0 for value in summary['test_fold_pnl'])
        and lower is not None and lower > 0
    )


def _write_trades(path: Path, trades: list[dict]) -> None:
    path.write_bytes(gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0))


def _report(result: dict) -> str:
    lines = [
        '# S120 — S20 Entry & Management Lab, Stage A', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Retrospective walk-forward diagnostic only. Live remains disabled.**', '',
        'Only entry timing changes. Candidate formation, structural stop, sizing, '
        'risk brakes and the S20 patient runner are frozen.', '',
    ]
    for fold_name, fold in result['folds'].items():
        lines.extend([
            f'## {fold_name}', '',
            '| Policy | Train stress fills | Train PF | Train mean R | Train PnL | '
            'Test stress fills | Test PF | Test mean R | Test PnL |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
        ])
        for policy in ENTRY_POLICIES:
            train = fold['train_stress'][policy]
            test = fold['test'][policy]['stress']
            lines.append(
                f'| {policy} | {train["trades"]} | {train["profit_factor"]} '
                f'| {train["mean_net_r"]:.3f} | ${train["net_pnl"]:.2f} '
                f'| {test["trades"]} | {test["profit_factor"]} '
                f'| {test["mean_net_r"]:.3f} | ${test["net_pnl"]:.2f} |'
            )
        lines.extend(['', f'Selected from train only: **{fold["selected"]}**.', ''])

    lines.extend([
        '## Combined disjoint OOS tests', '',
        '| Policy | Fills | PF | Mean R | PnL | Fold PnL | Bootstrap lower | Gate |',
        '|---|---:|---:|---:|---:|---|---:|---|',
    ])
    for policy in ENTRY_POLICIES:
        summary = result['combined_oos'][policy]
        lower = summary['bootstrap_day_lower_98_75_pct']
        lower_text = '—' if lower is None else f'{lower:.3f}'
        lines.append(
            f'| {policy} | {summary["trades"]} | {summary["profit_factor"]} '
            f'| {summary["mean_net_r"]:.3f} | ${summary["net_pnl"]:.2f} '
            f'| {summary["test_fold_pnl"]} | {lower_text} '
            f'| {"PASS" if summary["passes_gate"] else "FAIL"} |'
        )
    selected = result['selected_path_oos']
    lines.extend([
        '', '## Walk-forward selection path', '',
        f'Fold selections: `{result["fold_selections"]}`.', '',
        f'Fills {selected["trades"]}, PF {selected["profit_factor"]}, '
        f'mean R {selected["mean_net_r"]:.3f}, PnL ${selected["net_pnl"]:.2f}.', '',
        f'**Decision: {result["decision"]}.**', '',
        'A failed Stage A means stop/TP tuning is not allowed to rescue the entry '
        'stream. A passing fixed policy would authorize a new, separately frozen '
        'Stage B management study only.', '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument(
        '--output',
        default=str(ROOT / 'docs' / 'research' / 's120_s20_entry_lab_v1'),
    )
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Freeze protocol.json before loading market data')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data, manifest = {}, {'klines_funding': {}, 'metrics': {}}
    for symbol in TRADED:
        minutes, funding, k_manifest = load_archives(symbol, WARMUP, END, args.cache)
        metrics, m_manifest = load_metrics(symbol, WARMUP, END, args.cache)
        data[symbol] = minutes, funding, metrics
        manifest['klines_funding'][symbol] = k_manifest
        manifest['metrics'][symbol] = m_manifest
        print(symbol, 'archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = parent_config()
    entry_config = S20EntryLabConfig()
    features = {
        symbol: oi_features(data[symbol][0], data[symbol][2], config)
        for symbol in TRADED
    }
    parent = {
        symbol: generate_order_block_oi_signals(features[symbol], config, symbol)
        for symbol in TRADED
    }
    variants_by_policy = {policy: {} for policy in ENTRY_POLICIES}
    for symbol in TRADED:
        transformed = build_s20_entry_variants(
            data[symbol][0], features[symbol], parent[symbol], entry_config,
        )
        for policy in ENTRY_POLICIES:
            variants_by_policy[policy][symbol] = transformed[policy]

    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}
    result = {
        'protocol_sha256': protocol_hash,
        'parent_config': asdict(config),
        'entry_config': asdict(entry_config),
        'raw_parent_candidates': {symbol: len(rows) for symbol, rows in parent.items()},
        'raw_variants': {
            policy: {symbol: len(rows) for symbol, rows in signals.items()}
            for policy, signals in variants_by_policy.items()
        },
        'folds': {},
    }

    combined_summaries = {policy: [] for policy in ENTRY_POLICIES}
    combined_trades = {policy: [] for policy in ENTRY_POLICIES}
    selected_summaries, selected_trades, selections = [], [], []

    for fold in FOLDS:
        fold_result = {'train_stress': {}, 'test': {}}
        train_trades_by_policy = {}
        for policy in ENTRY_POLICIES:
            summary, trades = _run(
                markets, variants_by_policy[policy], config, 'stress', fold['train'],
            )
            fold_result['train_stress'][policy] = summary
            train_trades_by_policy[policy] = trades
            _write_trades(output / f'{fold["name"]}_{policy}_train_stress.json.gz', trades)
        selected = _select(fold_result['train_stress'])
        fold_result['selected'] = selected
        selections.append(selected)
        print(fold['name'], 'selected', selected, flush=True)

        for policy in ENTRY_POLICIES:
            fold_result['test'][policy] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary, trades = _run(
                    markets, variants_by_policy[policy], config, scenario, fold['test'],
                )
                fold_result['test'][policy][scenario] = summary
                _write_trades(
                    output / f'{fold["name"]}_{policy}_test_{scenario}.json.gz', trades,
                )
                if scenario == 'stress':
                    combined_summaries[policy].append(summary)
                    combined_trades[policy].extend(trades)
                    if policy == selected:
                        selected_summaries.append(summary)
                        selected_trades.extend(trades)
        if selected == 'CASH':
            selected_summaries.append({'net_pnl': 0.0})
        result['folds'][fold['name']] = fold_result

    result['combined_oos'] = {}
    for policy in ENTRY_POLICIES:
        summary = _combine(combined_summaries[policy], combined_trades[policy])
        summary['passes_gate'] = _passes_oos(summary)
        result['combined_oos'][policy] = summary
    result['fold_selections'] = selections
    result['selected_path_oos'] = _combine(selected_summaries, selected_trades)
    passing = [policy for policy in ENTRY_POLICIES if result['combined_oos'][policy]['passes_gate']]
    result['decision'] = (
        f'STAGE_A_PASS_TO_MANAGEMENT_LAB:{passing}'
        if passing else 'REJECTED_NO_ENTRY_POLICY_PASSES_OOS_GATE'
    )

    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n',
    )
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
