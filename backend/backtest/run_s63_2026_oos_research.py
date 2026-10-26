"""S63: genuine 2026 OOS of the two frozen in-sample greens.

S55 Donchian-20 and S60 15m flow-reset are not retuned. Window is
2026-01-01–2026-09-01, never used in S48–S62. Selection-affected
(chosen because 2025 H1 looked least-bad); this is the first unseen
calendar stretch, not live approval.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.donchian_4h_scalp import (
    Donchian4hConfig,
    donchian_4h_features,
    generate_donchian_4h_signals,
)
from l1_filter.taker_flow_reset_scalp import (
    TakerFlowResetConfig,
    generate_taker_flow_reset_signals,
    taker_flow_reset_features,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-12-01', '2026-09-01'
OOS = ('2026-01-01', END)


def _numeric_pf(summary):
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _scenario_execution(config, scenario):
    execution = config.execution()
    if scenario == 'stress':
        return replace(execution, maker_fee_bps=8.0, fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(execution, maker_fee_bps=10.0, fee_bps=10.0, slippage_bps=10.0)
    return execution


def _run(markets, signals, config, scenario, start, end):
    return execute_cluster(
        markets, signals, _scenario_execution(config, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )['summary']


def _report(results, protocol_hash):
    lines = [
        '# S63 — 2026 OOS zamrożonych S55 i S60',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Bez strojenia. Okno 2026-01-01–2026-09-01 nie brało udziału w S48–S62. '
        'Selekcja strategii jest skażona 2025; to pierwszy niewidziany kalendarz.',
        '',
        '| Strategia | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD | mean R |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, row in results.items():
        for scenario, summary in row['oos_2026'].items():
            pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
            lines.append(
                f'| {name} | {scenario} | {summary["trades"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% | {summary["mean_net_r"]:.3f} |'
            )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{row["decision"]}**.',
            f'- Kandydaty surowe: {row["raw_candidates"]}.',
            '',
        ])
    lines.append(
        'Kapitał $250, SOL+XRP, base 5/2 bps. Nie jest to zgoda na live.\n'
    )
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s63_2026_oos'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S63_2026_OOS',
        'traded': list(TRADED),
        'warmup': WARMUP,
        'oos': OOS,
        'strategies': ['S55_donchian_20', 'S60_flow_reset_15m'],
        'retune': False,
        'disclosure': (
            'selection-affected 2026 OOS characterization of frozen S55/S60; '
            'not live approval'
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
    markets = {symbol: data[symbol] for symbol in TRADED}
    oos_start, oos_end = (pd.Timestamp(OOS[0], tz='UTC'), pd.Timestamp(OOS[1], tz='UTC'))

    jobs = [
        ('S55_donchian_20', Donchian4hConfig('S55_donchian_20', 'donchian_20'),
         donchian_4h_features, generate_donchian_4h_signals),
        ('S60_flow_reset_15m', TakerFlowResetConfig('S60_flow_reset_15m', 'flow_reset_15m'),
         taker_flow_reset_features, generate_taker_flow_reset_signals),
    ]
    all_results = {}
    for name, config, feature_fn, signal_fn in jobs:
        features = {symbol: feature_fn(data[symbol][0], config) for symbol in TRADED}
        raw = {symbol: signal_fn(features[symbol], config, symbol) for symbol in TRADED}
        route = {
            'raw_candidates': sum(
                oos_start <= signal['timestamp'] < oos_end
                for signals in raw.values() for signal in signals
            ),
            'oos_2026': {},
        }
        for scenario in ('base', 'stress', 'severe'):
            summary = _run(markets, raw, config, scenario, *OOS)
            route['oos_2026'][scenario] = summary
            print(name, scenario, summary['trades'], summary['profit_factor'],
                  f'${summary["net_pnl"]:.2f}', flush=True)
        base = route['oos_2026']['base']
        stress = route['oos_2026']['stress']
        if (base['trades'] >= 15 and base['net_pnl'] > 0
                and _numeric_pf(base) > 1.10 and _numeric_pf(stress) >= 1.00):
            route['decision'] = 'SURVIVES_2026_OOS_NOT_LIVE'
        else:
            route['decision'] = 'REJECTED_ON_2026_OOS'
        all_results[name] = route

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
