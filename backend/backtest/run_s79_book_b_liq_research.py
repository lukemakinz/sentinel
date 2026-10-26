"""Book B — S79 liquidation cascade snapback ($250, $15 risk)."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_b_liq_snapback import (
    BookBLiqSnapbackConfig,
    central_variants,
    execution_for,
)
from l1_filter.liquidation_cascade_fade_scalp import (
    cascade_features,
    generate_cascade_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .run_s64_day_swing_research import evaluate_development_gate, evaluate_validation_gate
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def _scenario_execution(config: BookBLiqSnapbackConfig, scenario: str):
    execution = execution_for(config)
    if scenario == 'stress':
        return replace(execution, fee_bps=20.0, maker_fee_bps=20.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(execution, fee_bps=30.0, maker_fee_bps=30.0, slippage_bps=10.0)
    return execution


def _run_window(data, signals, config, scenario, start, end):
    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}
    result = execute_cluster(
        markets, signals, _scenario_execution(config, scenario),
        pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'),
        initial_capital=250, symbol_priority=TRADED,
    )
    summary = result['summary']
    mean_pnl, days = calendar_day_pnl(
        summary['net_pnl'],
        pd.Timestamp(start, tz='UTC'),
        pd.Timestamp(end, tz='UTC'),
    )
    summary['calendar_days'] = days
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
    return summary


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/s79_book_b_liq'
    output.mkdir(parents=True, exist_ok=True)
    protocol = {
        'strategy_id': 'S79_BOOK_B_LIQ',
        'traded': list(TRADED),
        'windows': WINDOWS,
        'capital_usd': 250,
        'fixed_risk_usd': 15,
        'disclosure': 'OI cascade fade; requires metrics archive',
    }
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        data[symbol] = (minutes, funding, metrics)
        print(symbol, 'ready', flush=True)

    all_results = {}
    for config in central_variants():
        cascade = config.cascade()
        features = {
            symbol: cascade_features(data[symbol][0], data[symbol][2], cascade)
            for symbol in TRADED
        }
        signals = {
            symbol: generate_cascade_signals(features[symbol], cascade, symbol)
            for symbol in TRADED
        }
        route_result = {'windows': {}}
        for window, bounds in WINDOWS.items():
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                route_result['windows'][window][scenario] = _run_window(
                    data, signals, config, scenario, bounds[0], bounds[1],
                )
        dev = route_result['windows']['development']['base']
        if not evaluate_development_gate(dev):
            route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
        elif evaluate_validation_gate(route_result['windows']['validation']):
            route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        else:
            route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        all_results[config.name] = route_result

    (output / 'summary.json').write_text(json.dumps(all_results, indent=2, default=str) + '\n')

    lines = [
        '# S79 — Book B liquidation snapback',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        f'Kapitał $250, ryzyko $15/trade, max 2 pozycje. Cel **${DAILY_GOAL_USD}/dzień**.',
        '',
        '| Trasa | Okno | Scenariusz | Tradów | PF | PnL | Opłaty | $/dzień | Gap $5 | $5? |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---|',
    ]
    for name, route in all_results.items():
        for window, scenarios in route['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary.get('profit_factor', 0)
                lines.append(
                    f'| {name} | {window} | {scenario} | {summary.get("trades", 0)} | '
                    f'{pf} | ${summary.get("net_pnl", 0):.2f} | '
                    f'${summary.get("fees_paid", 0):.2f} | '
                    f'${summary.get("mean_calendar_day_pnl", 0):.3f} | '
                    f'${summary.get("gap_to_5_usd_day", 0):.2f} | '
                    f'{"yes" if summary.get("hits_5_usd_day") else "no"} |'
                )
        lines.append(f'- Decyzja `{name}`: **{route["decision"]}**.')
        lines.append('')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
