"""S61: dollar-ratchet trail + consecutive-loss day halt.

Win rate is not the bottleneck (S60 15m was 44% WR / PF 1.18 in-sample).
Winners were clipped by a hard 2.5R/time-stop; losing streaks ground the
day. This overlay does not retune S60's flush/rebuild trigger.

Two frozen risk books, same 15m flow-reset signal:
  - ratchet_all: lock 50% of peak open $, sit out after 2 consecutive losses
  - ratchet_short: same $, sit out shorts after 2 consecutive short losses

S60-informed characterization; not independent discovery; not live approval.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.taker_flow_reset_scalp import (
    TakerFlowResetConfig,
    generate_taker_flow_reset_signals,
    taker_flow_reset_features,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def central_variants():
    signal = TakerFlowResetConfig('S61_flow_reset_15m', 'flow_reset_15m')
    return [
        (signal, 'ratchet_all', 'all'),
        (signal, 'ratchet_short', 'short'),
    ]


def overlay_execution(config, halt_side, scenario='base'):
    execution = replace(
        config.execution(),
        name=f'S61_{halt_side}',
        target_r=8.0,
        partial_r=1.0,
        partial_fraction=0.0,
        trailing=True,
        trail_atr=1.0,
        max_hold_minutes=240,
        dollar_ratchet=True,
        dollar_ratchet_lock_fraction=0.5,
        consecutive_loss_halt=2,
        consecutive_loss_halt_side=halt_side,
    )
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
        summary['trades'] >= 20
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) > 1.05
    )


def evaluate_validation_gate(val):
    return (
        _numeric_pf(val['base']) > 1.10
        and _numeric_pf(val['stress']) >= 1.00
        and val['base']['trades'] >= 12
    )


def _run_window(markets, signals, config, halt_side, scenario, start, end):
    result = execute_cluster(
        markets, signals, overlay_execution(config, halt_side, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary']


def _report(results, protocol_hash):
    lines = [
        '# S61 — dollar-ratchet trail + day halt po serii strat',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Ten sam sygnał S60 15m. Wypłata: po 1R stop jedzie za dolarem '
        '(blokada 50% szczytowego open $), cap 8R. Po 2 stratach z rzędu '
        'koniec dnia (`all`) albo koniec shortów (`short`). '
        'Charakterystyka S60-informed, nie zgoda na live.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD | mean R |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, route in results.items():
        for window, scenarios in route['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {name} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                    f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                    f'{summary["max_drawdown_pct"]:.3f}% | '
                    f'{summary["mean_net_r"]:.3f} |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{route["decision"]}**.',
            f'- Kandydaty surowe: {route["raw_candidates_by_window"]}.',
            f'- Halt diagnostics: {route.get("halt_diagnostics", {})}.',
            '',
        ])
    return '\n'.join(lines) + '\n'


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s61_dollar_ratchet_day_halt'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S61_DOLLAR_RATCHET_DAY_HALT',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'signal': 'S60 flow_reset_15m frozen',
        'routes': ['ratchet_all', 'ratchet_short'],
        'dollar_ratchet_lock_fraction': 0.5,
        'consecutive_loss_halt': 2,
        'target_cap_r': 8.0,
        'disclosure': (
            'S60-informed risk-overlay characterization; '
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
    signal_config = TakerFlowResetConfig('S61_flow_reset_15m', 'flow_reset_15m')
    features = {
        symbol: taker_flow_reset_features(data[symbol][0], signal_config)
        for symbol in TRADED
    }
    raw = {
        symbol: generate_taker_flow_reset_signals(
            features[symbol], signal_config, symbol)
        for symbol in TRADED
    }
    all_results = {}
    for _config, route_name, halt_side in central_variants():
        route_result = {
            'config': {'route': route_name, 'halt_side': halt_side},
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
                summary = _run_window(
                    markets, raw, signal_config, halt_side, scenario, *bounds)
                route_result['windows'][window][scenario] = summary
                print(route_name, window, scenario, summary['trades'],
                      summary['profit_factor'], f'${summary["net_pnl"]:.2f}',
                      'R', f'{summary["mean_net_r"]:.3f}',
                      'halt', summary['diagnostics'].get(
                          'blocked_consecutive_loss_halt', 0),
                      flush=True)
        route_result['halt_diagnostics'] = {
            window: route_result['windows'][window]['base']['diagnostics'].get(
                'blocked_consecutive_loss_halt', 0)
            for window in WINDOWS
        }
        dev = route_result['windows']['development']['base']
        if not evaluate_development_gate(dev):
            route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
        elif evaluate_validation_gate(route_result['windows']['validation']):
            route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        else:
            route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        all_results[route_name] = route_result

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
