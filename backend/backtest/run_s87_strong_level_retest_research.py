"""Frozen retrospective evaluation for S87 Strong Level Retest.

There is one route and no parameter grid.  Later windows are opened only after
the predeclared gate on the earlier window passes.
"""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.strong_level_retest import (
    StrongLevelRetestConfig,
    strong_level_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
WARMUP, END = '2025-03-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-07-01', '2026-01-01'),
    'validation': ('2026-01-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _numeric_pf(summary: dict) -> float:
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _development_pass(scenarios: dict) -> bool:
    base, stress = scenarios['base'], scenarios['stress']
    return (
        base['trades'] >= 20
        and base['net_pnl'] > 0
        and _numeric_pf(base) >= 1.10
        and _numeric_pf(stress) >= 0.95
    )


def _validation_pass(scenarios: dict) -> bool:
    base, stress = scenarios['base'], scenarios['stress']
    contribution = base['largest_symbol_gross_profit_share_pct']
    return (
        base['trades'] >= 10
        and _numeric_pf(base) >= 1.15
        and _numeric_pf(stress) >= 1.00
        and base['positive_symbols'] >= 2
        and contribution is not None
        and contribution <= 65
    )


def _execution(config: StrongLevelRetestConfig, scenario: str):
    execution = config.execution()
    if scenario == 'stress':
        return replace(
            execution,
            maker_fee_bps=5.0,
            fee_bps=8.0,
            slippage_bps=5.0,
            limit_penetration_bps=5.0,
        )
    if scenario == 'severe':
        return replace(
            execution,
            maker_fee_bps=10.0,
            fee_bps=10.0,
            slippage_bps=10.0,
            limit_penetration_bps=10.0,
        )
    return execution


def _run_window(markets, signals, config, scenario, start, end):
    return execute_cluster(
        markets,
        signals,
        _execution(config, scenario),
        start,
        end,
        initial_capital=250.0,
        symbol_priority=TRADED,
    )


def _report(result: dict) -> str:
    lines = [
        '# S87 — Strong Level Retest',
        '',
        f'Hash zamrożonego protokołu: `{result["protocol_sha256"]}`.',
        '',
        'Jedna trasa: 4h order block + wielokrotnie potwierdzony S/R + jawna ',
        'ocena siły. Limit czeka przed pierwszym re-testem. Badanie jest ',
        'retrospektywne i nie dopuszcza strategii do live.',
        '',
        '| Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in result['windows'].items():
        for scenario, summary in scenarios.items():
            pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
            lines.append(
                f'| {window} | {scenario} | {summary["trades"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% |'
            )
    lines.extend([
        '',
        f'**Decyzja: {result["decision"]}.**',
        '',
        f'Surowe setupy w dostępnych oknach: {result["raw_candidates_by_window"]}.',
        '',
        'Kapitał $250; ryzyko 0,20% na trade; jeden globalny pending i jedna ',
        'pozycja; notional maks. 1x equity; lewar maks. 5x. Brak strojenia po ',
        'wynikach. Odrzucony kandydat pozostaje odrzucony.',
        '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s87_strong_level_retest')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before data are loaded')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = StrongLevelRetestConfig()
    markets, manifest, signals = {}, {}, {}
    for symbol in TRADED:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, str(cache))
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        _, signals[symbol] = strong_level_signals(minutes, config)
        print(symbol, len(signals[symbol]), 'strong levels', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    result = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective research; not paper-forward and not live-approved',
        'config': asdict(config),
        'raw_candidates_by_window': {
            name: sum(
                start <= signal['timestamp'] < end
                for symbol_signals in signals.values()
                for signal in symbol_signals
            )
            for name, (start, end) in bounds.items()
        },
        'windows': {},
    }

    def evaluate(window):
        result['windows'][window] = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = _run_window(
                markets, signals, config, scenario, *WINDOWS[window])
            result['windows'][window][scenario] = replay['summary']
            payload = json.dumps(replay['trades'], allow_nan=False).encode()
            path = output / f'{window}_{scenario}_trades.json.gz'
            path.write_bytes(gzip.compress(payload, mtime=0))
            summary = replay['summary']
            print(window, scenario, summary['trades'], summary['profit_factor'],
                  f'${summary["net_pnl"]:.2f}', flush=True)

    evaluate('development')
    if not _development_pass(result['windows']['development']):
        result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
    else:
        evaluate('validation')
        if not _validation_pass(result['windows']['validation']):
            result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        else:
            evaluate('retrospective_evaluation')
            result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'

    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))


if __name__ == '__main__':
    main()
