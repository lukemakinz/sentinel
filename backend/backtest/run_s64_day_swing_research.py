"""S64 historical research: day/swing at $10 risk toward $10/day.

Two frozen routes, no grid:
  daily turtle-20 — uncapped R, 15-day hold
  prior-day breakout — hold toward UTC close
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.daily_turtle_swing import (
    DailyTurtleConfig,
    daily_turtle_features,
    generate_daily_turtle_signals,
)
from l1_filter.prior_day_breakout import (
    PriorDayBreakoutConfig,
    generate_prior_day_breakout_signals,
    prior_day_breakout_features,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}
DAILY_GOAL_USD = 10.0


def central_variants():
    return [DailyTurtleConfig(), PriorDayBreakoutConfig()]


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


def calendar_day_pnl(net_pnl, start, end):
    days = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days)
    return float(net_pnl) / days, days


def _run_window(markets, signals, config, scenario, start, end):
    result = execute_cluster(
        markets, signals, _scenario_execution(config, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    summary = result['summary']
    mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start, end)
    summary['calendar_days'] = days
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['hits_10_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    return summary


def _signals_for(config, minutes_by_symbol):
    if isinstance(config, DailyTurtleConfig):
        return {
            symbol: generate_daily_turtle_signals(
                daily_turtle_features(minutes, config), config, symbol)
            for symbol, minutes in minutes_by_symbol.items()
        }
    return {
        symbol: generate_prior_day_breakout_signals(
            prior_day_breakout_features(minutes, config), config, symbol)
        for symbol, minutes in minutes_by_symbol.items()
    }


def _report(results, protocol_hash):
    lines = [
        '# S64 — day/swing, $10 risk, cel $10/dzień',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Dwie zamrożone trasy, bez grida. Turtle-20 bez capu 2.5R (to nie S55/S58). '
        'Wybicie poprzedniego dnia z hold do sesji (to nie S49 1R/90m). '
        'Ryzyko $10, halt DD 25%, daily 10%, weekly 15%. Kapitał $250, SOL+XRP.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, route in results.items():
        for window, scenarios in route['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {name} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                    f'${summary["net_pnl"]:.2f} | '
                    f'${summary["mean_calendar_day_pnl"]:.2f} | '
                    f'{summary["max_drawdown_pct"]:.3f}% | '
                    f'{summary["mean_net_r"]:.3f} |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{route["decision"]}**.',
            f'- Kandydaty surowe: {route["raw_candidates_by_window"]}.',
            '',
        ])
    lines.append(
        'Cel $10/dzień jest diagnostyką, nie bramką krawędzi. '
        'Nie jest to zgoda na live.\n'
    )
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s64_day_swing'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S64_DAY_SWING',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': ['daily_turtle_20', 'prior_day_htc'],
        'fixed_risk_usd': 10.0,
        'daily_goal_usd': DAILY_GOAL_USD,
        'drawdown_halt_fraction': 0.25,
        'trailing': False,
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
    minutes_by_symbol = {symbol: data[symbol][0] for symbol in TRADED}
    all_results = {}
    for config in central_variants():
        raw = _signals_for(config, minutes_by_symbol)
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
                    flush=True,
                )
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
