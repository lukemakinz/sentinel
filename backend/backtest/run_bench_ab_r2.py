"""Rebuild the corrected, frozen Book A + exact S84 benchmark."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from .book_a_portfolio_sim import simulate_book_a
from .book_ab_portfolio_combo import daily_pnl_from_equity, merge_book_daily
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WARMUP, END = '2024-08-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}
COSTS = {
    'base': {'a': 7.0, 'fee': 7.0, 'slip': 2.0},
    'stress': {'a': 12.0, 'fee': 8.0, 'slip': 5.0},
    'severe': {'a': 20.0, 'fee': 10.0, 'slip': 10.0},
}


def _daily_summary(daily: pd.Series, initial=500.0) -> dict:
    daily = daily.sort_index()
    equity = initial + daily.cumsum()
    drawdown = (1 - equity / equity.cummax()) * 100
    tail_n = max(1, int(np.ceil(len(daily) * 0.05)))
    return {
        'net_pnl': float(daily.sum()),
        'return_pct': float(daily.sum() / initial * 100),
        'usd_per_calendar_day': float(daily.sum() / max(1, len(daily))),
        'max_drawdown_pct': float(drawdown.max()) if len(drawdown) else 0.0,
        'expected_shortfall_95_usd': float(daily.nsmallest(tail_n).mean()) if len(daily) else 0.0,
        'positive_month_share': float((daily.resample('ME').sum() > 0).mean()) if len(daily) else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/bench_ab_r2')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    minutes, funding, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes[symbol], funding[symbol], manifest[symbol] = load_archives(
            symbol, WARMUP, END, args.cache)
        print(symbol, len(minutes[symbol]), 'minutes', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    router = BookBQuietRouterConfig()
    signals_b = {'BTCUSDT': build_routed_quiet_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', router)}
    results = {'protocol_sha256': protocol_hash, 'windows': {}}

    for window, (start, end) in WINDOWS.items():
        results['windows'][window] = {}
        start_ts, end_ts = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
        for scenario, cost in COSTS.items():
            config_a = replace(BOOK_A_ALT_RM, taker_fee_bps=cost['a'])
            book_a = simulate_book_a(
                minutes, config_a, start_ts, end_ts, 250.0,
                risk=BOOK_A_RISK_DEFAULT)
            config_b = replace(
                BookBQuietBreakoutConfig().execution(),
                fee_bps=cost['fee'], maker_fee_bps=cost['fee'],
                slippage_bps=cost['slip'], fixed_risk_usd=6.0,
                drawdown_halt_fraction=0.28, daily_loss_fraction=0.05,
                consecutive_loss_halt=3,
            )
            book_b = execute_cluster(
                {'BTCUSDT': (minutes['BTCUSDT'], funding['BTCUSDT'])},
                signals_b, config_b, start_ts, end_ts, 250.0, ('BTCUSDT',))
            daily = merge_book_daily(
                book_a.daily_pnl,
                daily_pnl_from_equity(book_b['daily_equity'], 250.0))
            summary = _daily_summary(daily)
            summary.update({
                'book_a_net_pnl': book_a.summary['net_pnl'],
                'book_b_net_pnl': book_b['summary']['net_pnl'],
                'book_b_trades': book_b['summary']['trades'],
            })
            results['windows'][window][scenario] = summary
            print(window, scenario, summary, flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = [
        '# BENCH_AB_R2 — corrected Book A + exact S84', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | A PnL | B PnL | Total | Return | $/day | Max DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in results['windows'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {window} | {scenario} | ${row["book_a_net_pnl"]:.2f} | '
                f'${row["book_b_net_pnl"]:.2f} | ${row["net_pnl"]:.2f} | '
                f'{row["return_pct"]:.2f}% | ${row["usd_per_calendar_day"]:.3f} | '
                f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', 'Retrospective benchmark rebuild; not a live-performance claim.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
