"""S69 historical research: spread z-score fade and 4h Bollinger mean reversion."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.bollinger_mean_revert import (
    BollingerMeanRevertConfig,
    bollinger_mean_revert_features,
    generate_bollinger_mean_revert_signals,
)
from l1_filter.spread_zscore_fade import (
    SpreadZscoreConfig,
    generate_spread_zscore_signals,
    spread_zscore_features,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s64_day_swing_research import evaluate_development_gate, evaluate_validation_gate
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-01-01', '2026-01-01'
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
        '# S69 — fade spreadu SOL/XRP i powrót 4h Bollingera, cel $5/dzień',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Z-score log-spreadu (beta 60, okno 20, próg 2) to odwrotność momentum S68. '
        'Bollinger 4h fade do środka wstęgi w ADX<25 to nie squeeze-breakout S13. '
        'Dwa sloty, $15/noga.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R | $5? |',
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
                    f'${summary["net_pnl"]:.2f} | '
                    f'${summary["mean_calendar_day_pnl"]:.2f} | '
                    f'{summary["max_drawdown_pct"]:.3f}% | '
                    f'{summary["mean_net_r"]:.3f} | {hit} |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{name}`: **{route["decision"]}**.',
            f'- Kandydaty surowe: {route["raw_candidates_by_window"]}.',
            '',
        ])
    lines.append('Nie jest to zgoda na live.\n')
    return '\n'.join(lines)


def _decide(route_result):
    dev = route_result['windows']['development']['base']
    if not evaluate_development_gate(dev):
        return 'REJECTED_AT_DEVELOPMENT_GATE'
    if evaluate_validation_gate(route_result['windows']['validation']):
        if dev.get('hits_5_usd_day') and route_result['windows']['validation']['base'].get('hits_5_usd_day'):
            return 'GOAL_5_USD_DAY_PAPER_ONLY_NOT_LIVE'
        return 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
    return 'REJECTED_AT_VALIDATION_GATE'


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s69_spread_and_bb'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S69_SPREAD_AND_BB',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': ['spread_zscore', 'bb_mean_revert'],
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

    window_bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    markets = {symbol: data[symbol] for symbol in TRADED}
    z_config = SpreadZscoreConfig()
    bb_config = BollingerMeanRevertConfig()
    z_bars = spread_zscore_features(data['SOLUSDT'][0], data['XRPUSDT'][0], z_config)
    raw_by_config = {
        z_config: generate_spread_zscore_signals(z_bars, z_config),
        bb_config: {
            symbol: generate_bollinger_mean_revert_signals(
                bollinger_mean_revert_features(data[symbol][0], bb_config), bb_config, symbol)
            for symbol in TRADED
        },
    }
    all_results = {}
    for config, raw in raw_by_config.items():
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
        route_result['decision'] = _decide(route_result)
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
