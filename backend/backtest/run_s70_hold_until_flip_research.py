"""S70: keep the S68 SOL/XRP pair, stop paying to re-enter the same side.

S68 development made about $59 before fees and $21 after, because the pair
was closed and reopened every day. Two frozen turnover rules, same signal:
  hold_until_flip — stay in the leg until the ranking reverses, 20-day cap
  monday_hold    — enter Monday only, hold seven days
"""
from dataclasses import replace
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


def _execution(route, scenario):
    config = CrossSectionMomConfig().execution()
    if route == 'hold_until_flip':
        config = replace(
            config, name='S70_hold_until_flip',
            max_hold_minutes=20 * 1440, flip_on_opposite_signal=True,
        )
    elif route == 'monday_hold':
        config = replace(
            config, name='S70_monday_hold',
            max_hold_minutes=7 * 1440, flip_on_opposite_signal=False,
        )
    else:
        raise ValueError(route)
    if scenario == 'stress':
        return replace(config, maker_fee_bps=8.0, fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(config, maker_fee_bps=10.0, fee_bps=10.0, slippage_bps=10.0)
    return config


def _signals(raw, route):
    if route == 'monday_hold':
        return {
            symbol: [item for item in signals if item['timestamp'].weekday() == 0]
            for symbol, signals in raw.items()
        }
    return raw


def _run_window(markets, signals, route, scenario, start, end):
    result = execute_cluster(
        markets, signals, _execution(route, scenario),
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    summary = result['summary']
    mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start, end)
    summary['calendar_days'] = days
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    return summary


def _decide(route_result):
    dev = route_result['windows']['development']['base']
    if not evaluate_development_gate(dev):
        return 'REJECTED_AT_DEVELOPMENT_GATE'
    if evaluate_validation_gate(route_result['windows']['validation']):
        if dev.get('hits_5_usd_day') and route_result['windows']['validation']['base'].get('hits_5_usd_day'):
            return 'GOAL_5_USD_DAY_PAPER_ONLY_NOT_LIVE'
        return 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
    return 'REJECTED_AT_VALIDATION_GATE'


def _report(results, protocol_hash):
    lines = [
        '# S70 — ta sama para SOL/XRP, bez codziennego obrotu',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Sygnał bez zmian względem S68 (20 dni, spread 3%). Zmienia się tylko to, '
        'kiedy para jest zamykana. S68 development: około $59 brutto, $38 opłat, $21 netto.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Opłaty | $/dzień | Max DD | $5? |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    for name, route in results.items():
        for window, scenarios in route['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                hit = 'tak' if summary['hits_5_usd_day'] else 'nie'
                lines.append(
                    f'| {name} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                    f'${summary["net_pnl"]:.2f} | ${summary["fees"]:.2f} | '
                    f'${summary["mean_calendar_day_pnl"]:.2f} | '
                    f'{summary["max_drawdown_pct"]:.3f}% | {hit} |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{route["decision"]}**.',
            '',
        ])
    lines.append('Nie jest to zgoda na live.\n')
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s70_hold_until_flip'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S70_HOLD_UNTIL_FLIP',
        'parent_signal': 'S68_xs_mom_20',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': {
            'hold_until_flip': {'max_hold_days': 20, 'flip_on_opposite_signal': True},
            'monday_hold': {'max_hold_days': 7, 'weekday': 'Monday'},
        },
        'unchanged_from_s68': {'lookback': 20, 'min_spread': 0.03, 'fixed_risk_usd': 15.0},
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

    signal_config = CrossSectionMomConfig()
    features = {
        symbol: cross_section_features(data[symbol][0], signal_config) for symbol in TRADED
    }
    raw = generate_cross_section_signals(features, signal_config)
    markets = {symbol: data[symbol] for symbol in TRADED}
    all_results = {}
    for route in ('hold_until_flip', 'monday_hold'):
        signals = _signals(raw, route)
        route_result = {'windows': {}}
        for window, bounds in WINDOWS.items():
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary = _run_window(markets, signals, route, scenario, *bounds)
                route_result['windows'][window][scenario] = summary
                print(
                    route, window, scenario, summary['trades'],
                    summary['profit_factor'],
                    f'${summary["net_pnl"]:.2f}',
                    f'fees ${summary["fees"]:.2f}',
                    f'${summary["mean_calendar_day_pnl"]:.2f}/d',
                    flush=True,
                )
        route_result['decision'] = _decide(route_result)
        all_results[route] = route_result

    (output / 'summary.json').write_text(
        json.dumps({
            'protocol_sha256': protocol_hash,
            'disclosure': protocol['disclosure'],
            'results': all_results,
        }, indent=2, allow_nan=False, default=str) + '\n')
    (output / 'REPORT.md').write_text(_report(all_results, protocol_hash))
    print(json.dumps({name: row['decision'] for name, row in all_results.items()}, indent=2))


if __name__ == '__main__':
    main()
