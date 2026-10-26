"""S57: 4h RSI extreme on BTC+SOL+XRP, two frozen payoff shapes.

S40's RSI(14) 20/80 4h extreme was the only historically green PF in this
repo (4.56 on 14 fills, rejected for sample size, 8-symbol 8R trail).
This is not a retune of that threshold. It tests whether that same
trigger makes money on the cached 2025 SOL/XRP/BTC cluster under:

  - rsi_2p5_time: 2.5R hard target, 36h, no trail (S55 payoff family)
  - rsi_patient_runner: S40's original 8R chandelier, 3-day hold

Disclosure: S40 already inspected historical PF on a wider universe and
later windows. This run is characterization on a different cluster/window,
not independent discovery and not live approval.
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.htf_extreme_reversion_scalp import (
    HTFExtremeReversionConfig,
    generate_htf_extreme_signals,
    htf_extreme_features,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('BTCUSDT', 'SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def central_variants():
    return [
        (HTFExtremeReversionConfig('S57_rsi_2p5_time', 'rsi_extreme'), 'time_2p5'),
        (HTFExtremeReversionConfig('S57_rsi_patient_runner', 'rsi_extreme'), 'patient_runner'),
    ]


def execution_for(config, scenario='base'):
    if config.name.endswith('2p5_time'):
        execution = replace(
            config.execution(),
            target_r=2.5,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            max_hold_minutes=2160,
            maker_fee_bps=5.0,
            fee_bps=5.0,
            slippage_bps=2.0,
        )
    else:
        execution = config.execution()
    if scenario == 'stress':
        return replace(execution, maker_fee_bps=8.0, fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(execution, maker_fee_bps=10.0, fee_bps=10.0, slippage_bps=10.0)
    return execution


def _numeric_pf(summary):
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def evaluate_development_gate(summary):
    return (
        summary['trades'] >= 15
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) > 1.05
    )


def evaluate_validation_gate(val):
    return (
        _numeric_pf(val['base']) > 1.10
        and _numeric_pf(val['stress']) >= 1.00
        and val['base']['trades'] >= 10
    )


def _run_window(markets, signals, config, scenario, start, end):
    result = execute_cluster(
        markets, signals, execution_for(config, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary']


def _report(results, protocol_hash):
    lines = [
        '# S57 — 4h RSI extreme, BTC+SOL+XRP',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Ten sam trigger S40 (RSI 20/80 na 4h), inny klaster i okno. '
        'Dwie wypłaty: 2.5R/36h oraz oryginalny 8R trail S40. '
        'Charakterystyka, nie zgoda na live.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, route in results.items():
        for window, scenarios in route['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {name} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                    f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                    f'{summary["max_drawdown_pct"]:.3f}% |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{route["decision"]}**.',
            f'- Kandydaty surowe: {route["raw_candidates_by_window"]}.',
            '',
        ])
    return '\n'.join(lines) + '\n'


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s57_htf_rsi'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S57_HTF_RSI',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': ['rsi_2p5_time', 'rsi_patient_runner'],
        'signal': 'S40 rsi_extreme 20/80 4h',
        'disclosure': (
            'S40-informed characterization on cached BTC/SOL/XRP; '
            'not independent discovery; not live approval'
        ),
    }
    protocol_path.write_text(json.dumps(protocol, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data = {}
    for symbol in TRADED:
        minutes, funding, manifest = load_archives(
            symbol, WARMUP, END, str(cache), repair_from_daily=True)
        data[symbol] = minutes, funding
        print(symbol, 'ready', len(minutes), flush=True)

    window_bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    markets = {symbol: data[symbol] for symbol in TRADED}
    all_results = {}
    for config, payoff in central_variants():
        features = {
            symbol: htf_extreme_features(data[symbol][0], config)
            for symbol in TRADED
        }
        raw = {
            symbol: generate_htf_extreme_signals(features[symbol], config, symbol)
            for symbol in TRADED
        }
        route_result = {
            'config': asdict(config),
            'payoff': payoff,
            'raw_candidates_by_window': {
                window: sum(
                    start <= signal['timestamp'] < end
                    for signals in raw.values() for signal in signals
                )
                for window, (start, end) in window_bounds.items()
            },
            'windows': {},
        }
        for window, bounds in WINDOWS.items():
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary = _run_window(markets, raw, config, scenario, *bounds)
                route_result['windows'][window][scenario] = summary
                print(config.name, window, scenario, summary['trades'],
                      summary['profit_factor'], f'${summary["net_pnl"]:.2f}',
                      flush=True)
        dev = route_result['windows']['development']['base']
        if not evaluate_development_gate(dev):
            route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
        elif evaluate_validation_gate(route_result['windows']['validation']):
            route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        else:
            route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        all_results[config.name] = route_result

    (output / 'summary.json').write_text(
        json.dumps({
            'protocol_sha256': protocol_hash,
            'disclosure': protocol['disclosure'],
            'results': all_results,
        }, indent=2, allow_nan=False, default=str) + '\n')
    (output / 'REPORT.md').write_text(_report(all_results, protocol_hash))
    print(json.dumps({
        name: row['decision'] for name, row in all_results.items()
    }, indent=2))


if __name__ == '__main__':
    main()
