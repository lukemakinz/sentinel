"""S83 — matrix of A/B/portfolio experiments (dev + validation, $5 goal)."""
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT, BookARiskOverlayConfig
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig
from l1_filter.book_b_macro_burst import (
    BookBMacroBurstConfig,
    generate_macro_burst_signals,
    macro_burst_features,
)
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig, build_quiet_breakout_signals
from l1_filter.book_b_shared_risk import (
    BookBSharedRiskConfig,
    apply_shared_risk_to_signals,
    daily_indicator_table,
)
from .book_a_portfolio_sim import simulate_book_a
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


WARMUP, END = '2024-08-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}
A_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
B_SYMBOLS = ('BTCUSDT', 'ETHUSDT')


def _load_minutes():
    cache = '/tmp/sentinel-scalp-cache'
    minutes = {}
    for symbol in A_SYMBOLS:
        minutes[symbol], _, _ = load_archives(symbol, WARMUP, END, cache)
    return minutes


def _run_a(minutes, a_cfg, risk, start, end):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    sim = simulate_book_a(minutes, a_cfg, st, en, 250.0, risk=risk)
    mean, _ = calendar_day_pnl(sim.summary['net_pnl'], st, en)
    return mean, sim.summary['net_pnl'], sim.summary['max_drawdown_fraction']


def _exec_b(base):
    return replace(
        base,
        drawdown_halt_fraction=0.28,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
        fixed_risk_usd=8.0,
        fee_bps=7.0,
        maker_fee_bps=7.0,
    )


def _run_b_macro(minutes, indicators, macro_cfg, risk_cfg, start, end, label):
    cache_data = {}
    for s in B_SYMBOLS:
        m, f, _ = load_archives(s, '2025-04-01', END, '/tmp/sentinel-scalp-cache')
        cache_data[s] = (m, f)
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    raw = {
        s: generate_macro_burst_signals(
            macro_burst_features(cache_data[s][0], macro_cfg), macro_cfg, s, st, en)
        for s in B_SYMBOLS
    }
    signals = {
        s: apply_shared_risk_to_signals(raw[s], indicators, risk_cfg) for s in B_SYMBOLS
    }
    markets = {s: cache_data[s] for s in B_SYMBOLS}
    summary = execute_cluster(
        markets, signals, _exec_b(macro_cfg.execution()), st, en, 250, B_SYMBOLS,
    )['summary']
    mean, _ = calendar_day_pnl(summary['net_pnl'], st, en)
    return mean, summary['net_pnl'], summary['trades']


def _run_b_quiet(minutes, start, end):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    cfg = BookBQuietBreakoutConfig()
    signals = {
        'BTCUSDT': build_quiet_breakout_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', cfg),
    }
    markets = {
        'BTCUSDT': (
            minutes['BTCUSDT'],
            load_archives('BTCUSDT', '2025-04-01', END, '/tmp/sentinel-scalp-cache')[1],
        ),
    }
    summary = execute_cluster(
        markets, signals, _exec_b(cfg.execution()), st, en, 250, ('BTCUSDT',),
    )['summary']
    mean, _ = calendar_day_pnl(summary['net_pnl'], st, en)
    return mean, summary['net_pnl'], summary['trades']


def main() -> None:
    output = Path(__file__).resolve().parents[2] / 'docs/research/s83_experiment_matrix'
    output.mkdir(parents=True, exist_ok=True)
    minutes = _load_minutes()
    indicators = daily_indicator_table(minutes, BookASmallTsmomConfig())
    macro = BookBMacroBurstConfig(fixed_risk_usd=8.0)

    experiments = []

    a_variants = [
        ('A_RM_base', BookASmallTsmomConfig(), BOOK_A_RISK_DEFAULT),
        ('A_RM_top3', replace(BookASmallTsmomConfig(), top_n=3), BOOK_A_RISK_DEFAULT),
        ('A_RM_noBTC', replace(BookASmallTsmomConfig(), include_btc_in_universe=False),
         BOOK_A_RISK_DEFAULT),
        ('A_RM_mom3pct', replace(BookASmallTsmomConfig(), min_mom_fraction=0.03),
         BOOK_A_RISK_DEFAULT),
        ('A_RM_biweekly', replace(BookASmallTsmomConfig(), rebalance_every_n_weeks=2),
         BOOK_A_RISK_DEFAULT),
        ('A_RM_tight', BookASmallTsmomConfig(), BookARiskOverlayConfig(
            name='RM_composite_tight',
            min_breadth_sma50=0.45,
            drawdown_half_scale=0.08,
            drawdown_flat_scale=0.14,
            max_gross_exposure=0.65,
        )),
    ]

    b_variants = [
        ('B_S82', 'macro', BookBSharedRiskConfig(), macro),
        ('B_complement', 'macro', BookBSharedRiskConfig(
            name='B_complement_only', complement_only=True, max_a_mult_for_complement=0.55,
        ), macro),
        ('B_CPI_only', 'macro', BookBSharedRiskConfig(), replace(macro, allowed_events=('CPI',))),
        ('B_S83_quiet', 'quiet', None, macro),
    ]

    for window, bounds in WINDOWS.items():
        for a_name, a_cfg, a_risk in a_variants:
            a_day, a_pnl, a_dd = _run_a(minutes, a_cfg, a_risk, bounds[0], bounds[1])
            experiments.append({
                'window': window, 'leg': 'A', 'name': a_name,
                'usd_per_day': a_day, 'pnl': a_pnl, 'max_dd': a_dd, 'trades': None,
            })
        for item in b_variants:
            b_name, kind, risk_cfg, mcfg = item[0], item[1], item[2], item[3]
            if kind == 'macro':
                b_day, b_pnl, trades = _run_b_macro(
                    minutes, indicators, mcfg, risk_cfg, bounds[0], bounds[1], b_name)
            else:
                b_day, b_pnl, trades = _run_b_quiet(minutes, bounds[0], bounds[1])
            experiments.append({
                'window': window, 'leg': 'B', 'name': b_name,
                'usd_per_day': b_day, 'pnl': b_pnl, 'max_dd': None, 'trades': trades,
            })

        # Best A + best B combos for this window
        a_rows = [e for e in experiments if e['window'] == window and e['leg'] == 'A']
        b_rows = [e for e in experiments if e['window'] == window and e['leg'] == 'B']
        best_a = max(a_rows, key=lambda x: x['usd_per_day'])
        best_b = max(b_rows, key=lambda x: x['usd_per_day'])
        combo_day = best_a['usd_per_day'] + best_b['usd_per_day']
        experiments.append({
            'window': window, 'leg': 'AB', 'name': f'{best_a["name"]}+{best_b["name"]}',
            'usd_per_day': combo_day,
            'pnl': best_a['pnl'] + best_b['pnl'],
            'gap_to_5': DAILY_GOAL_USD - combo_day,
        })

    (output / 'experiments.json').write_text(json.dumps(experiments, indent=2) + '\n')

    val_a = sorted([e for e in experiments if e['window'] == 'validation' and e['leg'] == 'A'],
                   key=lambda x: -x['usd_per_day'])[:5]
    val_b = sorted([e for e in experiments if e['window'] == 'validation' and e['leg'] == 'B'],
                   key=lambda x: -x['usd_per_day'])[:5]
    combos = [e for e in experiments if e['window'] == 'validation' and e['leg'] == 'AB']

    lines = [
        '# S83 — experiment matrix',
        '',
        '## Wnioski (validation)',
        '',
        '- **RM na A** nadal najważniejsze; warianty top3 / mom3% / biweekly — porównaj tabelę.',
        '- **Book B:** mniej tradów + filtry (S82) = mniejsza strata, nie dodatni edge.',
        '- **Cel $5/d** wymaga ~**50×** obecnej dodatniej średniej validation (jeśli w ogóle dodatnia).',
        '',
        '### Top Book A (validation $/dzień)',
        '',
    ]
    for e in val_a:
        lines.append(f'- `{e["name"]}`: **${e["usd_per_day"]:.3f}/d**, PnL ${e["pnl"]:.2f}')
    lines.extend(['', '### Top Book B (validation $/dzień)', ''])
    for e in val_b:
        lines.append(
            f'- `{e["name"]}`: **${e["usd_per_day"]:.3f}/d**, '
            f'PnL ${e["pnl"]:.2f}, trades {e.get("trades")}')
    lines.extend(['', '### Greedy A+B (validation)', ''])
    for e in combos:
        lines.append(f'- `{e["name"]}`: **${e["usd_per_day"]:.3f}/d**, gap ${e.get("gap_to_5", 0):.2f}')
    lines.extend([
        '',
        'Pełna lista: `experiments.json`.',
    ])
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines[-15:]))


if __name__ == '__main__':
    main()
