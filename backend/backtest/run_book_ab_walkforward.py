"""Rolling 3-month OOS windows for Book A ALT+RM + Book B quiet variants."""
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import (
    BOOK_B_QUIET_V2,
    BookBQuietBreakoutConfig,
    build_quiet_breakout_signals,
)
from .book_a_portfolio_sim import simulate_book_a
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


WARMUP = '2024-08-01'
FOLD_END = '2026-01-01'
A_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')

FOLDS = [
    ('WF1', '2025-05-01', '2025-08-01'),
    ('WF2', '2025-08-01', '2025-11-01'),
    ('WF3', '2025-11-01', '2026-01-01'),
]


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


def _run_b(minutes, cfg, start, end, cache):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    signals = {'BTCUSDT': build_quiet_breakout_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', cfg)}
    markets = {'BTCUSDT': (minutes['BTCUSDT'], load_archives(
        'BTCUSDT', '2025-04-01', FOLD_END, cache)[1])}
    summary = execute_cluster(
        markets, signals, _exec_b(cfg.execution()), st, en, 250, ('BTCUSDT',),
    )['summary']
    mean, days = calendar_day_pnl(summary['net_pnl'], st, en)
    return mean, summary


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/book_ab_walkforward'
    output.mkdir(parents=True, exist_ok=True)
    minutes = {}
    for s in A_SYMBOLS:
        minutes[s], _, _ = load_archives(s, WARMUP, FOLD_END, cache)

    b_configs = [
        BookBQuietBreakoutConfig(),
        BOOK_B_QUIET_V2,
    ]
    rows = []
    for fold_id, start, end in FOLDS:
        st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
        a_sim = simulate_book_a(minutes, BOOK_A_ALT_RM, st, en, 250.0, risk=BOOK_A_RISK_DEFAULT)
        a_day, _ = calendar_day_pnl(a_sim.summary['net_pnl'], st, en)
        rows.append({
            'fold': fold_id, 'leg': 'A_ALT_RM', 'b_variant': '-',
            'usd_per_day': a_day, 'pnl': a_sim.summary['net_pnl'],
            'trades': None, 'max_dd': a_sim.summary['max_drawdown_fraction'],
        })
        for cfg in b_configs:
            b_day, summary = _run_b(minutes, cfg, start, end, cache)
            combo = a_day + b_day
            rows.append({
                'fold': fold_id, 'leg': 'B', 'b_variant': cfg.name,
                'usd_per_day': b_day, 'pnl': summary['net_pnl'],
                'trades': summary['trades'], 'max_dd': None,
            })
            rows.append({
                'fold': fold_id, 'leg': 'AB', 'b_variant': cfg.name,
                'usd_per_day': combo, 'pnl': a_sim.summary['net_pnl'] + summary['net_pnl'],
                'trades': summary['trades'],
                'gap_to_5': DAILY_GOAL_USD - combo,
            })

    (output / 'walkforward.json').write_text(json.dumps(rows, indent=2) + '\n')

    active_folds = {f[0] for f in FOLDS if f[0] != 'WF3'}  # WF3: Book A flat (PnL tylko w paź)
    def agg(variant):
        ab = [r for r in rows if r['leg'] == 'AB' and r['b_variant'] == variant
              and r['fold'] in active_folds]
        if not ab:
            return 0.0, 0
        return sum(r['usd_per_day'] for r in ab) / len(ab), sum(1 for r in ab if r['usd_per_day'] > 0)

    v1_mean, v1_pos = agg(BookBQuietBreakoutConfig().name)
    v2_mean, v2_pos = agg(BOOK_B_QUIET_V2.name)

    lines = [
        '# Book A+B walk-forward (3× ~3 mies.)',
        '',
        f'Book A: **{BOOK_A_ALT_RM.name}** + **{BOOK_A_RISK_DEFAULT.name}**.',
        '',
        '| Fold | Okno | A $/d | B v1 $/d | B v2 $/d | AB v1 | AB v2 |',
        '|---|---|---:|---:|---:|---:|---:|',
    ]
    for fold_id, start, end in FOLDS:
        a = next(r for r in rows if r['fold'] == fold_id and r['leg'] == 'A_ALT_RM')
        b1 = next(r for r in rows if r['fold'] == fold_id and r['b_variant'] == BookBQuietBreakoutConfig().name and r['leg'] == 'B')
        b2 = next(r for r in rows if r['fold'] == fold_id and r['b_variant'] == BOOK_B_QUIET_V2.name and r['leg'] == 'B')
        ab1 = next(r for r in rows if r['fold'] == fold_id and r['b_variant'] == BookBQuietBreakoutConfig().name and r['leg'] == 'AB')
        ab2 = next(r for r in rows if r['fold'] == fold_id and r['b_variant'] == BOOK_B_QUIET_V2.name and r['leg'] == 'AB')
        lines.append(
            f'| {fold_id} | {start}→{end} | {a["usd_per_day"]:.3f} | '
            f'{b1["usd_per_day"]:.3f} | {b2["usd_per_day"]:.3f} | '
            f'{ab1["usd_per_day"]:.3f} | {ab2["usd_per_day"]:.3f} |'
        )
    lines.extend([
        '',
        'WF3: Book A **$0** (cały zysk A w validation przypada na **październik**).',
        f'Średnia AB v1 (WF1–2): **${v1_mean:.3f}/d** ({v1_pos}/2 dodatnie).',
        f'Średnia AB v2 (WF1–2): **${v2_mean:.3f}/d** ({v2_pos}/2 dodatnie).',
        '',
        'Pełne dane: `walkforward.json`.',
    ])
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines[-6:]))


if __name__ == '__main__':
    main()
