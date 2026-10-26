"""S85 — combine A ALT+RM with B variants + portfolio fuse."""
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BOOK_B_QUIET_V2, BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from l1_filter.book_b_shared_risk import daily_indicator_table
from .book_a_portfolio_sim import simulate_book_a
from .book_ab_portfolio_combo import (
    daily_pnl_from_equity,
    merge_book_daily,
    summarize_pnl,
    trailing_pause_fuse,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD
from .scalp_data import load_archives


WARMUP = '2024-08-01'
DATA_END = '2026-01-01'
SYMS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WINDOWS = {
    'full_2025': ('2025-01-01', DATA_END),
    'validation': ('2025-10-01', DATA_END),
}


def _exec_b():
    return replace(
        BookBQuietBreakoutConfig().execution(),
        drawdown_halt_fraction=0.28,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
        fixed_risk_usd=6.0,
        fee_bps=7.0,
        maker_fee_bps=7.0,
    )


def _turbo_signals(signals, indicators, vol_cut=0.35, boost=1.35):
    out = []
    for signal in signals:
        day = pd.Timestamp(signal['timestamp']).normalize()
        if day not in indicators.index:
            out.append(signal)
            continue
        vol = float(indicators.loc[day].get('btc_vol_percentile', 1))
        tagged = dict(signal)
        scale = float(tagged.get('risk_scale', 1.0))
        if vol < vol_cut:
            scale = min(1.0, scale * boost)
        tagged['risk_scale'] = scale
        out.append(tagged)
    return out


def _run_b(minutes, mode, start, end):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    router = BookBQuietRouterConfig()
    indicators = daily_indicator_table(minutes, BOOK_A_ALT_RM)
    if mode == 'router':
        signals = build_routed_quiet_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', router)
    elif mode == 'router_turbo':
        raw = build_routed_quiet_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', router)
        signals = _turbo_signals(raw, indicators)
    elif mode == 'v2_only':
        from l1_filter.book_b_quiet_breakout import build_quiet_breakout_signals
        signals = build_quiet_breakout_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', BOOK_B_QUIET_V2)
    else:
        raise ValueError(mode)
    markets = {'BTCUSDT': (minutes['BTCUSDT'], load_archives(
        'BTCUSDT', '2025-04-01', DATA_END, '/tmp/sentinel-scalp-cache')[1])}
    return execute_cluster(
        markets, {'BTCUSDT': signals}, _exec_b(), st, en, 250, ('BTCUSDT',),
    )


def _combo_window(minutes, b_mode, start, end, fuse=False):
    st, en = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    a = simulate_book_a(minutes, BOOK_A_ALT_RM, st, en, 250.0, risk=BOOK_A_RISK_DEFAULT)
    b = _run_b(minutes, b_mode, start, end)
    a_pnl = a.daily_pnl
    b_pnl = daily_pnl_from_equity(b['daily_equity'], 250.0)
    combined = merge_book_daily(a_pnl, b_pnl)
    if fuse:
        combined = trailing_pause_fuse(combined)
    stats = summarize_pnl(combined, st, en)
    stats['gap_to_5'] = DAILY_GOAL_USD - stats['mean_calendar_day_pnl']
    stats['b_trades'] = b['summary']['trades']
    stats['a_pnl'] = a.summary['net_pnl']
    stats['b_pnl'] = b['summary']['net_pnl']
    return stats


def main() -> None:
    output = Path(__file__).resolve().parents[2] / 'docs/research/s85_portfolio_combo'
    output.mkdir(parents=True, exist_ok=True)
    minutes = {s: load_archives(s, WARMUP, DATA_END, '/tmp/sentinel-scalp-cache')[0] for s in SYMS}

    combos = [
        ('C0_router', 'router', False),
        ('C1_router_turbo', 'router_turbo', False),
        ('C2_v2_only', 'v2_only', False),
        ('C3_router_fuse', 'router', True),
    ]
    # S86 smart router re-run uses updated pick_quiet_config in build_routed_quiet_signals
    results = {}
    for window, bounds in WINDOWS.items():
        results[window] = {}
        for name, mode, fuse in combos:
            results[window][name] = _combo_window(minutes, mode, bounds[0], bounds[1], fuse)
            print(window, name, results[window][name], flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = [
        '# S85 — kombinacje A+B + fuse',
        '',
        'A: **BOOK_A_ALT_RM** + **RM_composite_v1**. Kapitał $250+$250.',
        '',
        '| Okno | Combo | $/dzień | Gap $5 | B tradów |',
        '|---|---|---:|---:|---:|',
    ]
    for window, rows in results.items():
        for name, row in rows.items():
            lines.append(
                f'| {window} | {name} | {row["mean_calendar_day_pnl"]:.3f} | '
                f'{row["gap_to_5"]:.2f} | {row["b_trades"]} |'
            )
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')

    best = max(
        ((w, n, r) for w, rows in results.items() for n, r in rows.items()),
        key=lambda x: x[2]['mean_calendar_day_pnl'],
    )
    lines.append(f'\nNajlepszy replay: **{best[0]} / {best[1]}** → ${best[2]["mean_calendar_day_pnl"]:.3f}/d.')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('BEST', best[0], best[1], best[2]['mean_calendar_day_pnl'])


if __name__ == '__main__':
    main()
