"""S68 historical research: SOL vs XRP cross-sectional momentum, dual slot, $5/day goal."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.cross_section_mom import (
    CrossSectionMomConfig,
    cross_section_features,
    generate_cross_section_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s64_day_swing_research import evaluate_development_gate, evaluate_validation_gate
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


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
    summary = result['summary']
    mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start, end)
    summary['calendar_days'] = days
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    return summary


def _report(results, protocol_hash):
    lines = [
        '# S68 — cross-section SOL vs XRP, cel $5/dzień',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Long silniejszy 20-dniowy return, short słabszy. Para raz dziennie, dwa sloty, '
        '$15/noga. To nie jest directional turtle ani NY ORB.',
        '',
        '| Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R | $5? |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    route = results['S68_xs_mom_20']
    for window, scenarios in route['windows'].items():
        for scenario, summary in scenarios.items():
            pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
            hit = 'tak' if summary['hits_5_usd_day'] else 'nie'
            lines.append(
                f'| {window} | {scenario} | {summary["trades"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                f'${summary["net_pnl"]:.2f} | '
                f'${summary["mean_calendar_day_pnl"]:.2f} | '
                f'{summary["max_drawdown_pct"]:.3f}% | '
                f'{summary["mean_net_r"]:.3f} | {hit} |'
            )
    lines.extend([
        '',
        f'- Decyzja: **{route["decision"]}**.',
        f'- Kandydaty surowe: {route["raw_candidates_by_window"]}.',
        '',
        'Nie jest to zgoda na live.',
        '',
    ])
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s68_cross_section'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S68_CROSS_SECTION_MOM',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'lookback': 20,
        'min_spread': 0.03,
        'fixed_risk_usd': 15.0,
        'max_positions': 2,
        'daily_goal_usd': DAILY_GOAL_USD,
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

    config = CrossSectionMomConfig()
    features = {
        symbol: cross_section_features(data[symbol][0], config) for symbol in TRADED
    }
    raw = generate_cross_section_signals(features, config)
    window_bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    markets = {symbol: data[symbol] for symbol in TRADED}
    route_result = {
        'config': asdict(config),
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
            print(
                config.name, window, scenario, summary['trades'],
                summary['profit_factor'], f'${summary["net_pnl"]:.2f}',
                f'${summary["mean_calendar_day_pnl"]:.2f}/d',
                'HIT5' if summary['hits_5_usd_day'] else 'miss',
                flush=True,
            )
    dev = route_result['windows']['development']['base']
    if not evaluate_development_gate(dev):
        route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
    elif evaluate_validation_gate(route_result['windows']['validation']):
        if dev.get('hits_5_usd_day') and route_result['windows']['validation']['base'].get('hits_5_usd_day'):
            route_result['decision'] = 'GOAL_5_USD_DAY_PAPER_ONLY_NOT_LIVE'
        else:
            route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
    else:
        route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
    all_results = {config.name: route_result}
    (output / 'summary.json').write_text(
        json.dumps({
            'protocol_sha256': protocol_hash,
            'disclosure': protocol['disclosure'],
            'results': all_results,
        }, indent=2, allow_nan=False, default=str) + '\n')
    (output / 'REPORT.md').write_text(_report(all_results, protocol_hash))
    print(route_result['decision'])


if __name__ == '__main__':
    main()
