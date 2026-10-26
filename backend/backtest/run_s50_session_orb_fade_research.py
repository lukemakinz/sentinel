"""S50 historical research: fade a failed session opening-range break.

Two frozen routes, no grid, not a retune of S49:
  - utc_failed_fade: 00:00-00:15 UTC range, fade reclaim in any regime
  - london_sideline_fade: 07:00-07:30 UTC range, fade only on SIDELINE days

S49 rejected with-trend ORB. This tests the complementary claim that those
breaks are false and should be faded after a reclaim. 1.0R, 90m, no trail.
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.session_orb_fade_scalp import (
    SessionORBFadeConfig,
    generate_session_orb_fade_signals,
    session_orb_fade_features,
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
    return [
        SessionORBFadeConfig('S50_utc_failed_fade', 'utc_failed_fade'),
        SessionORBFadeConfig('S50_london_sideline_fade', 'london_sideline_fade'),
    ]


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


def _run_window(markets, signals, config, scenario, start, end):
    result = execute_cluster(
        markets, signals, _scenario_execution(config, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary']


def evaluate_development_gate(summary):
    return (
        summary['trades'] >= 25
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) > 1.05
    )


def evaluate_validation_gate(val):
    return (
        _numeric_pf(val['base']) > 1.10
        and _numeric_pf(val['stress']) >= 1.00
        and val['base']['trades'] >= 15
    )


def _report(results, protocol_hash):
    lines = [
        '# S50 — fade failed session opening-range break',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Po S49 (z-trendem ORB odrzucony) testujemy hipotezę komplementarną: '
        'pierwsze wybicie zakresu sesji jest fałszywe; fade po reclaim. '
        'Jedno wejście dziennie. Target 1.0R, time-stop 90 min, bez trailing.',
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
            f'- Udział reżimów 5m: {route["regime_share"]}.',
            '',
        ])
    lines.extend([
        'Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, '
        'stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego. '
        'To nie jest strojenie S49 po wynikach.',
        '',
    ])
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s50_session_orb_fade'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S50_SESSION_ORB_FADE',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': ['utc_failed_fade', 'london_sideline_fade'],
        'target_r': 1.0,
        'max_hold_minutes': 90,
        'trailing': False,
        'one_attempt_per_day': True,
        'disclosure': 'cached-window historical characterization; not live approval',
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
    for config in central_variants():
        features = {
            symbol: session_orb_fade_features(data[symbol][0], config)
            for symbol in TRADED
        }
        raw = {
            symbol: generate_session_orb_fade_signals(features[symbol], config, symbol)
            for symbol in TRADED
        }
        counts = pd.concat(
            [features[symbol].regime.value_counts() for symbol in TRADED],
            axis=1,
        ).sum(axis=1)
        total = float(counts.sum()) or 1.0
        regime_share = {
            'UP': round(float(counts.get(1, 0)) / total, 3),
            'DOWN': round(float(counts.get(-1, 0)) / total, 3),
            'SIDELINE': round(float(counts.get(0, 0)) / total, 3),
        }
        route_result = {
            'config': asdict(config),
            'regime_share': regime_share,
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

    summary = {
        'protocol_sha256': protocol_hash,
        'disclosure': protocol['disclosure'],
        'results': all_results,
    }
    (output / 'summary.json').write_text(
        json.dumps(summary, indent=2, allow_nan=False, default=str) + '\n')
    (output / 'REPORT.md').write_text(_report(all_results, protocol_hash))
    print(json.dumps({
        name: row['decision'] for name, row in all_results.items()
    }, indent=2))


if __name__ == '__main__':
    main()
