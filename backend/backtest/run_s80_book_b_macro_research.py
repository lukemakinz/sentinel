"""Book B — S80 macro burst on FOMC/CPI/NFP ($250)."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_b_macro_burst import (
    BookBMacroBurstConfig,
    generate_macro_burst_signals,
    macro_burst_features,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s64_day_swing_research import evaluate_development_gate, evaluate_validation_gate
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('BTCUSDT', 'ETHUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def _scenario_execution(config: BookBMacroBurstConfig, scenario: str):
    execution = config.execution()
    if scenario == 'stress':
        return replace(execution, fee_bps=20.0, maker_fee_bps=20.0, slippage_bps=6.0)
    if scenario == 'severe':
        return replace(execution, fee_bps=30.0, maker_fee_bps=30.0, slippage_bps=10.0)
    return execution


def _run_window(data, config, scenario, start, end):
    start_ts = pd.Timestamp(start, tz='UTC')
    end_ts = pd.Timestamp(end, tz='UTC')
    signals = {}
    for symbol in TRADED:
        bars = macro_burst_features(data[symbol][0], config)
        signals[symbol] = generate_macro_burst_signals(
            bars, config, symbol, start_ts, end_ts,
        )
    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}
    result = execute_cluster(
        markets, signals, _scenario_execution(config, scenario),
        start_ts, end_ts, initial_capital=250, symbol_priority=TRADED,
    )
    summary = result['summary']
    mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start_ts, end_ts)
    summary['calendar_days'] = days
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
    summary['signal_count'] = sum(len(signals[s]) for s in TRADED)
    return summary


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/s80_book_b_macro'
    output.mkdir(parents=True, exist_ok=True)
    config = BookBMacroBurstConfig()
    protocol = {
        'strategy_id': config.name,
        'traded': list(TRADED),
        'windows': WINDOWS,
        'events': list(config.allowed_events),
        'capital_usd': 250,
        'fixed_risk_usd': config.fixed_risk_usd,
    }
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        data[symbol] = (minutes, funding)
        print(symbol, 'ready', flush=True)

    route_result = {'windows': {}}
    for window, bounds in WINDOWS.items():
        route_result['windows'][window] = {}
        for scenario in ('base', 'stress', 'severe'):
            route_result['windows'][window][scenario] = _run_window(
                data, config, scenario, bounds[0], bounds[1],
            )
            print(window, scenario, route_result['windows'][window][scenario], flush=True)

    dev = route_result['windows']['development']['base']
    if not evaluate_development_gate(dev):
        route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
    elif evaluate_validation_gate(route_result['windows']['validation']):
        route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
    else:
        route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'

    (output / 'summary.json').write_text(json.dumps(route_result, indent=2, default=str) + '\n')
    lines = [
        '# S80 — Book B macro burst',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        f'FOMC/CPI/NFP: breakout 2h range po publikacji. BTC+ETH, $10 risk. Cel **${DAILY_GOAL_USD}/dzień**.',
        '',
        '| Okno | Scenariusz | Sygnały | Tradów | PF | PnL | $/dzień | Gap $5 |',
        '|---|---|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in route_result['windows'].items():
        for scenario, summary in scenarios.items():
            lines.append(
                f'| {window} | {scenario} | {summary.get("signal_count", 0)} | '
                f'{summary.get("trades", 0)} | {summary.get("profit_factor")} | '
                f'${summary.get("net_pnl", 0):.2f} | '
                f'${summary.get("mean_calendar_day_pnl", 0):.3f} | '
                f'${summary.get("gap_to_5_usd_day", 0):.2f} |'
            )
    lines.append(f'\nDecyzja: **{route_result["decision"]}**.')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
