"""Book B — bear-regime RSI2 on BTC ($250)."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_b_bear_rsi import BookBBearRsiConfig, generate_bear_rsi_signals
from .cluster_scalp_simulator import execute_cluster
from .run_s64_day_swing_research import evaluate_development_gate, evaluate_validation_gate
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('BTCUSDT',)
WARMUP, END = '2024-08-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def _scenario_execution(config: BookBBearRsiConfig, scenario: str):
    execution = config.execution()
    if scenario == 'stress':
        return replace(execution, fee_bps=20.0, maker_fee_bps=20.0, slippage_bps=5.0)
    return execution


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/s81_book_b_bear_rsi'
    output.mkdir(parents=True, exist_ok=True)
    config = BookBBearRsiConfig()
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps({
        'strategy_id': config.name,
        'traded': list(TRADED),
        'windows': WINDOWS,
        'rule': 'RSI2 only when BTC < SMA200',
    }, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()

    btc_minutes, funding, _ = load_archives('BTCUSDT', WARMUP, END, cache)
    signals = {
        'BTCUSDT': generate_bear_rsi_signals(
            btc_minutes, btc_minutes, config, 'BTCUSDT'),
    }
    markets = {'BTCUSDT': (btc_minutes, funding)}
    route_result = {'windows': {}}
    for window, bounds in WINDOWS.items():
        route_result['windows'][window] = {}
        for scenario in ('base', 'stress'):
            start_ts = pd.Timestamp(bounds[0], tz='UTC')
            end_ts = pd.Timestamp(bounds[1], tz='UTC')
            result = execute_cluster(
                markets, signals, _scenario_execution(config, scenario),
                start_ts, end_ts, initial_capital=250, symbol_priority=TRADED,
            )
            summary = result['summary']
            mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start_ts, end_ts)
            summary['mean_calendar_day_pnl'] = mean_pnl
            summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
            summary['signal_count'] = len(signals['BTCUSDT'])
            route_result['windows'][window][scenario] = summary
            print(window, scenario, summary['net_pnl'], mean_pnl, flush=True)

    dev = route_result['windows']['development']['base']
    if evaluate_development_gate(dev):
        route_result['decision'] = (
            'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
            if evaluate_validation_gate(route_result['windows']['validation'])
            else 'REJECTED_AT_VALIDATION_GATE'
        )
    else:
        route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'

    (output / 'summary.json').write_text(json.dumps(route_result, indent=2, default=str) + '\n')
    (output / 'REPORT.md').write_text(
        f'# S81 Bear RSI\n\nHash: `{protocol_hash}`.\n\n'
        f'Dev $/dzień: ${dev["mean_calendar_day_pnl"]:.3f}, '
        f'val: ${route_result["windows"]["validation"]["base"]["mean_calendar_day_pnl"]:.3f}, '
        f'decision: **{route_result["decision"]}**.\n'
    )


if __name__ == '__main__':
    main()
