"""S84 — breadth router between quiet Donchian v1 (chop) and v2 (bull)."""
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import (
    BOOK_B_QUIET_V2,
    BookBQuietBreakoutConfig,
    build_quiet_breakout_signals,
)
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from .book_a_portfolio_sim import simulate_book_a
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


WARMUP = '2024-08-01'
DATA_END = '2026-01-01'
A_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WINDOWS = {
    'full_2025': ('2025-01-01', '2026-01-01'),
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', DATA_END),
}


def _exec_b(base):
    return replace(
        base,
        drawdown_halt_fraction=0.28,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
        fixed_risk_usd=6.0,
        fee_bps=7.0,
        maker_fee_bps=7.0,
    )


def _run_b(minutes, cfg, builder, start, end):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    if builder == 'router':
        signals = {'BTCUSDT': build_routed_quiet_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', cfg)}
    else:
        signals = {'BTCUSDT': build_quiet_breakout_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', cfg)}
    markets = {'BTCUSDT': (minutes['BTCUSDT'], load_archives(
        'BTCUSDT', '2025-04-01', DATA_END, '/tmp/sentinel-scalp-cache')[1])}
    exec_cfg = (
        cfg.v1.execution() if isinstance(cfg, BookBQuietRouterConfig) else cfg.execution()
    )
    summary = execute_cluster(
        markets, signals, _exec_b(exec_cfg), st, en, 250, ('BTCUSDT',),
    )['summary']
    mean, _ = calendar_day_pnl(summary['net_pnl'], st, en)
    return mean, summary


def main() -> None:
    output = Path(__file__).resolve().parents[2] / 'docs/research/s84_quiet_router'
    output.mkdir(parents=True, exist_ok=True)
    router = BookBQuietRouterConfig()
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps({
        'strategy_id': router.name,
        'breadth_v2_threshold': router.breadth_v2_threshold,
        'windows': WINDOWS,
    }, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()

    minutes = {s: load_archives(s, WARMUP, DATA_END, '/tmp/sentinel-scalp-cache')[0] for s in A_SYMBOLS}

    results = {}
    for window, bounds in WINDOWS.items():
        st, en = pd.Timestamp(bounds[0], tz='UTC'), pd.Timestamp(bounds[1], tz='UTC')
        a_sim = simulate_book_a(minutes, BOOK_A_ALT_RM, st, en, 250.0, risk=BOOK_A_RISK_DEFAULT)
        a_day, _ = calendar_day_pnl(a_sim.summary['net_pnl'], st, en)
        variants = {
            'B_v1': (BookBQuietBreakoutConfig(), 'plain'),
            'B_v2': (BOOK_B_QUIET_V2, 'plain'),
            'B_router': (router, 'router'),
        }
        row = {'A_usd_per_day': a_day, 'A_pnl': a_sim.summary['net_pnl']}
        for key, (cfg, mode) in variants.items():
            b_day, b_sum = _run_b(minutes, cfg, mode, bounds[0], bounds[1])
            row[key] = b_day
            row[f'{key}_pnl'] = b_sum['net_pnl']
            row[f'{key}_trades'] = b_sum['trades']
            row[f'AB_{key}'] = a_day + b_day
            row[f'gap_{key}'] = DAILY_GOAL_USD - (a_day + b_day)
        results[window] = row
        print(window, row, flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = [
        '# S84 — quiet Donchian router (breadth)',
        '',
        f'Hash: `{protocol_hash}`.',
        f'Jeśli breadth ≥ {router.breadth_v2_threshold} → v2, inaczej v1.',
        '',
        '| Okno | A $/d | B v1 | B v2 | B router | AB router | Gap $5 |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for window, row in results.items():
        lines.append(
            f'| {window} | {row["A_usd_per_day"]:.3f} | {row["B_v1"]:.3f} | '
            f'{row["B_v2"]:.3f} | {row["B_router"]:.3f} | {row["AB_B_router"]:.3f} | '
            f'{row["gap_B_router"]:.2f} |'
        )
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
