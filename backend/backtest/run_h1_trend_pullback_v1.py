"""Frozen retrospective for H1_TREND_PULLBACK_V1.

Usage:
    PYTHONPATH=. ../env/bin/python -m backtest.run_h1_trend_pullback_v1
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.h1_trend_pullback import (
    H1TrendPullbackConfig,
    build_h1_features,
    generate_h1_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
ROOT = Path(__file__).resolve().parents[2]
WARMUP, END = '2025-04-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_diagnostic': ('2026-04-01', END),
}


def _pf(summary: dict) -> float:
    value = summary['profit_factor']
    return float('inf') if value == 'Infinity' else float(value or 0.0)


def _development_pass(summary: dict) -> bool:
    return (
        summary['trades'] >= 40
        and summary['net_pnl'] > 0
        and _pf(summary) > 1.10
        and summary['mean_net_r'] > 0
    )


def _validation_pass(summary: dict) -> bool:
    share = summary['largest_symbol_gross_profit_share_pct']
    return (
        summary['trades'] >= 20
        and summary['net_pnl'] >= 0
        and _pf(summary) >= 1.00
        and summary['positive_symbols'] >= 2
        and share is not None and share <= 60
    )


def _execution(config: H1TrendPullbackConfig, scenario: str):
    base = config.execution()
    if scenario == 'stress':
        return replace(
            base, maker_fee_bps=5.0, fee_bps=8.0,
            slippage_bps=5.0, limit_penetration_bps=5.0,
        )
    if scenario == 'severe':
        return replace(
            base, maker_fee_bps=10.0, fee_bps=10.0,
            slippage_bps=10.0, limit_penetration_bps=10.0,
        )
    return base


def _run(data, signals, config, scenario, window):
    result = execute_cluster(
        {symbol: data[symbol] for symbol in TRADED},
        signals,
        _execution(config, scenario),
        *WINDOWS[window],
        initial_capital=250,
        symbol_priority=TRADED,
    )
    return result['summary'], result['trades']


def _report(result: dict) -> str:
    lines = [
        '# H1 Trend Pullback v1', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Retrospective diagnostic only. Live remains disabled.**', '',
        '| Window | Costs | Raw candidates | Fills | WR | PF | Mean R | PnL | Max DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in result['windows'].items():
        for scenario, summary in scenarios.items():
            lines.append(
                f'| {window} | {scenario} | {result["raw_candidates_by_window"][window]} '
                f'| {summary["trades"]} | {summary["win_rate_pct"]:.1f}% '
                f'| {summary["profit_factor"]} | {summary["mean_net_r"]:.3f} '
                f'| ${summary["net_pnl"]:.2f} | {summary["max_drawdown_pct"]:.2f}% |'
            )
    lines.extend([
        '', f'**Decision: {result["decision"]}.**', '',
        'H1 is evaluated first with static P0. P1/P2 are not allowed to rescue '
        'an entry stream that has no positive edge under P0.', '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument(
        '--output', default=str(ROOT / 'docs' / 'research' / 'h1_trend_pullback_v1'),
    )
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Freeze protocol.json before loading market data')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data, manifest = {}, {}
    for symbol in TRADED:
        minutes, funding, manifest[symbol] = load_archives(
            symbol, WARMUP, END, args.cache,
        )
        data[symbol] = (minutes, funding)
        print(symbol, 'archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = H1TrendPullbackConfig()
    features = {
        symbol: build_h1_features(data[symbol][0], config)
        for symbol in TRADED
    }
    signals = {
        symbol: generate_h1_signals(features[symbol], config, symbol)
        for symbol in TRADED
    }
    bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    result = {
        'protocol_sha256': protocol_hash,
        'config': asdict(config),
        'raw_candidates_by_symbol': {
            symbol: len(rows) for symbol, rows in signals.items()
        },
        'raw_candidates_by_window': {
            name: sum(
                start <= row['timestamp'] < end
                for rows in signals.values() for row in rows
            )
            for name, (start, end) in bounds.items()
        },
        'windows': {},
    }

    result['windows']['development'] = {}
    for scenario in ('base', 'stress', 'severe'):
        summary, trades = _run(data, signals, config, scenario, 'development')
        result['windows']['development'][scenario] = summary
        (output / f'development_{scenario}_trades.json.gz').write_bytes(
            gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
        )
        print('development', scenario, summary['trades'], summary['profit_factor'],
              f'${summary["net_pnl"]:.2f}', flush=True)

    if not _development_pass(result['windows']['development']['stress']):
        result['decision'] = 'REJECTED_AT_DEVELOPMENT_STRESS_GATE'
    else:
        result['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run(data, signals, config, scenario, 'validation')
            result['windows']['validation'][scenario] = summary
            (output / f'validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
            )
        if not _validation_pass(result['windows']['validation']['stress']):
            result['decision'] = 'REJECTED_AT_VALIDATION_STRESS_GATE'
        else:
            result['windows']['retrospective_diagnostic'] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary, trades = _run(
                    data, signals, config, scenario, 'retrospective_diagnostic',
                )
                result['windows']['retrospective_diagnostic'][scenario] = summary
                (output / f'diagnostic_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
                )
            result['decision'] = 'HISTORICAL_PASS_PAPER_FORWARD_ONLY'

    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n',
    )
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
