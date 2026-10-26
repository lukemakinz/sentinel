"""Causal comparison of S1C and its higher-frequency S1CF clone.

The original S1C remains unchanged. S1CF keeps the same 1h liquidity sweep,
15m FVG/CHoCH confirmation and execution geometry, but scans every 15 minutes
and accepts both the London and New York windows. Results are produced from the
local candle database; this command neither downloads data nor places orders.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sentinel.settings')
os.environ.setdefault('MAX_LEVERAGE', '20')
os.environ.setdefault('MAX_HIGH_CONVICTION_LEVERAGE', '20')

import django

django.setup()

from django.db import close_old_connections

from .simulator import BacktestConfig, BacktestSimulator


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT')
STRATEGIES = ('S1C', 'S1CF')
WINDOWS = {
    'develop': (
        ('develop_05', datetime(2026, 5, 1, tzinfo=timezone.utc),
         datetime(2026, 6, 1, tzinfo=timezone.utc)),
        ('develop_06', datetime(2026, 6, 1, tzinfo=timezone.utc),
         datetime(2026, 7, 1, tzinfo=timezone.utc)),
        ('validation_07', datetime(2026, 7, 1, tzinfo=timezone.utc),
         datetime(2026, 8, 1, tzinfo=timezone.utc)),
    ),
    'holdout': (
        ('holdout_08', datetime(2026, 8, 1, tzinfo=timezone.utc),
         datetime(2026, 9, 1, tzinfo=timezone.utc)),
    ),
}


def _safe_number(value):
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _run_one(strategy, symbol, label, start, end, capital, risk):
    close_old_connections()
    simulator = BacktestSimulator(BacktestConfig(
        symbol=symbol,
        strategy=strategy,
        start_date=start,
        end_date=end,
        initial_capital=capital,
        risk_per_trade=risk,
        stop_profile='tight',
    ))
    metrics = simulator.run()
    trades = metrics.trades
    gains = sum(float(x['pnl']) for x in trades if x['pnl'] > 0)
    losses = -sum(float(x['pnl']) for x in trades if x['pnl'] < 0)
    result = {
        'strategy': strategy,
        'symbol': symbol,
        'phase': label,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'trades': len(trades),
        'wins': sum(x['pnl'] > 0 for x in trades),
        'win_rate_pct': 100 * sum(x['pnl'] > 0 for x in trades) / len(trades) if trades else 0,
        'profit_factor': _safe_number(gains / losses if losses else (math.inf if gains else None)),
        'net_pnl': sum(float(x['pnl']) for x in trades),
        'return_pct': 100 * sum(float(x['pnl']) for x in trades) / capital,
        'max_drawdown_pct': metrics.max_drawdown,
        'open_positions_at_end': len(simulator.open_positions),
        'pending_orders_at_end': len(simulator.pending_orders),
        'close_reasons': {},
        'trades_detail': trades,
    }
    for trade in trades:
        reason = trade['close_reason']
        result['close_reasons'][reason] = result['close_reasons'].get(reason, 0) + 1
    close_old_connections()
    return result


def _aggregate(rows, capital):
    summaries = []
    keys = sorted({(x['strategy'], x['phase']) for x in rows})
    for strategy, phase in keys:
        selected = [x for x in rows if x['strategy'] == strategy and x['phase'] == phase]
        trades = sum(x['trades'] for x in selected)
        wins = sum(x['wins'] for x in selected)
        gains = sum(sum(float(t['pnl']) for t in x['trades_detail'] if t['pnl'] > 0) for x in selected)
        losses = -sum(sum(float(t['pnl']) for t in x['trades_detail'] if t['pnl'] < 0) for x in selected)
        net = sum(x['net_pnl'] for x in selected)
        summaries.append({
            'strategy': strategy,
            'phase': phase,
            'trades': trades,
            'trades_per_day_all_pairs': trades / max(
                (datetime.fromisoformat(selected[0]['end']) - datetime.fromisoformat(selected[0]['start'])).days, 1),
            'wins': wins,
            'win_rate_pct': 100 * wins / trades if trades else 0,
            'profit_factor': _safe_number(gains / losses if losses else (math.inf if gains else None)),
            'net_pnl': net,
            'return_pct_on_4x_capital': 100 * net / (capital * len(selected)),
            'positive_pairs': sum(x['net_pnl'] > 0 for x in selected),
        })
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=tuple(WINDOWS), required=True)
    parser.add_argument('--output', default='docs/research/s1cf_frequency')
    parser.add_argument('--capital', type=float, default=1000.0)
    parser.add_argument('--risk', type=float, default=0.003)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    protocol = output / 'protocol.json'
    if not protocol.exists():
        protocol.write_text(json.dumps({
            'strategies': {
                'S1C': 'unchanged reference strategy; hourly scan, New York window',
                'S1CF': 'copy of S1C; 15-minute scan, London + New York windows; same 1h sweep, 15m FVG/CHoCH and exits',
            },
            'symbols': SYMBOLS,
            'capital_per_pair': args.capital,
            'risk_per_trade': args.risk,
            'leverage_cap': 20,
            'stop_profile': 'tight',
            'development_windows': ['2026-05', '2026-06'],
            'validation_window': '2026-07',
            'holdout_window': '2026-08',
            'costs': 'legacy engine: limit entry 2bps; market entry/exit 5bps fee and 10bps adverse slippage',
            'causality_fixes': [
                'time-kill age is evaluated at candle timestamp, not wall clock',
                'liquidity targets are built as-of the signal timestamp with an upper time bound',
                'the liquidity-sweep gate uses the scan timestamp rather than a wall-clock snapshot',
                'exit slippage is adverse and all positions are settled at end of test',
            ],
            'success_rule': 'On holdout S1CF must have more trades than S1C, positive net PnL, PF>1, and no fewer than 50% winning trades. Research only; passing does not authorize live trading.',
        }, indent=2) + '\n')

    jobs = [(strategy, symbol, label, start, end, args.capital, args.risk)
            for label, start, end in WINDOWS[args.stage]
            for strategy in STRATEGIES for symbol in SYMBOLS]
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(_run_one, *job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(f"{row['phase']} {row['strategy']} {row['symbol']}: "
                  f"n={row['trades']} WR={row['win_rate_pct']:.1f}% "
                  f"PnL={row['net_pnl']:.2f}", flush=True)
    rows.sort(key=lambda x: (x['phase'], x['strategy'], x['symbol']))
    summaries = _aggregate(rows, args.capital)
    (output / f'{args.stage}_results.json').write_text(
        json.dumps(rows, indent=2, default=str) + '\n')
    (output / f'{args.stage}_summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
    for row in summaries:
        print(f"PORTFOLIO {row['phase']} {row['strategy']}: n={row['trades']} "
              f"WR={row['win_rate_pct']:.1f}% PF={row['profit_factor']} "
              f"PnL={row['net_pnl']:.2f}", flush=True)


if __name__ == '__main__':
    main()
