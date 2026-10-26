"""S65 historical research: mean reversion day/swing at $10 risk."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.rsi2_mean_reversion import (
    Rsi2Config,
    generate_rsi2_signals,
    rsi2_features,
)
from l1_filter.vwap_trend_dip import (
    VwapTrendDipConfig,
    generate_vwap_trend_dip_signals,
    vwap_trend_dip_features,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s64_day_swing_research import (
    DAILY_GOAL_USD,
    calendar_day_pnl,
    evaluate_development_gate,
    evaluate_validation_gate,
)
from .scalp_data import load_archives


TRADED = ('SOLUSDT', 'XRPUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def central_variants():
    return [VwapTrendDipConfig(), Rsi2Config()]


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
    summary['hits_10_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    return summary


def _signals_for(config, minutes_by_symbol):
    if isinstance(config, VwapTrendDipConfig):
        return {
            symbol: generate_vwap_trend_dip_signals(
                vwap_trend_dip_features(minutes, config), config, symbol)
            for symbol, minutes in minutes_by_symbol.items()
        }
    return {
        symbol: generate_rsi2_signals(
            rsi2_features(minutes, config), config, symbol)
        for symbol, minutes in minutes_by_symbol.items()
    }


def _report(results, protocol_hash):
    lines = [
        '# S65 — mean reversion day/swing, $10 risk, cel $10/dzień',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'VWAP dip-reclaim w 4h trendzie (hold sesyjny) i RSI(2) Connors na dziennym. '
        'To nie jest wybicie S64 ani 1R scalp S49/S50. Ryzyko $10, SOL+XRP, $250.',
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
    lines.append('Cel $10/dzień jest diagnostyką. Nie jest to zgoda na live.\n')
    return '\n'.join(lines)


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s65_mean_reversion'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S65_MEAN_REVERSION',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'routes': ['vwap_trend_dip', 'rsi2'],
        'fixed_risk_usd': 10.0,
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
