"""Forward-style eval: 2026-01-01 → yesterday on extended cache."""
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from .book_a_portfolio_sim import simulate_book_a
from .book_ab_portfolio_combo import daily_pnl_from_equity, merge_book_daily, summarize_pnl
from .cluster_scalp_simulator import execute_cluster
from .extend_scalp_cache import data_end_exclusive, load_range_resilient
import pandas as pd
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD


SYMS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
CACHE = '/tmp/sentinel-scalp-cache'
WARMUP = '2024-08-01'
FORWARD_START = '2026-01-01'


def _load_minutes(end: pd.Timestamp):
    minutes = {}
    for s in SYMS:
        if end > pd.Timestamp('2026-01-01', tz='UTC'):
            try:
                m, _, _ = load_range_resilient(
                    s, pd.Timestamp(WARMUP, tz='UTC'), end, CACHE)
            except Exception:
                from .scalp_data import load_archives
                m, _, _ = load_archives(s, WARMUP, str(end.date()), CACHE, repair_from_daily=True)
        else:
            from .scalp_data import load_archives
            m, _, _ = load_archives(s, WARMUP, str(end.date()), CACHE)
        minutes[s] = m
    return minutes


def main() -> None:
    end = data_end_exclusive() - pd.Timedelta(days=1) - pd.Timedelta(days=1) - pd.Timedelta(days=1) - pd.Timedelta(days=1)
    start = pd.Timestamp(FORWARD_START, tz='UTC')
    output = Path(__file__).resolve().parents[2] / 'docs/research/paper_forward'
    output.mkdir(parents=True, exist_ok=True)

    minutes = _load_minutes(end)
    a = simulate_book_a(minutes, BOOK_A_ALT_RM, start, end, 250.0, risk=BOOK_A_RISK_DEFAULT)
    router = BookBQuietRouterConfig()
    exec_b = replace(
        BookBQuietBreakoutConfig().execution(),
        fixed_risk_usd=6.0,
        drawdown_halt_fraction=0.28,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
    )
    signals = {'BTCUSDT': build_routed_quiet_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', router)}
    _, btc_funding, _ = load_range_resilient(
        'BTCUSDT', pd.Timestamp(WARMUP, tz='UTC'), end, CACHE)
    b = execute_cluster(
        {'BTCUSDT': (minutes['BTCUSDT'], btc_funding)},
        signals, exec_b, start, end, 250, ('BTCUSDT',),
    )
    combined = merge_book_daily(a.daily_pnl, daily_pnl_from_equity(b['daily_equity'], 250.0))
    stats = summarize_pnl(combined, start, end)
    stats['gap_to_5'] = DAILY_GOAL_USD - stats['mean_calendar_day_pnl']
    stats['a_net'] = a.summary['net_pnl']
    stats['b_net'] = b['summary']['net_pnl']
    stats['b_trades'] = b['summary']['trades']
    stats['window'] = [str(start.date()), str(end.date())]

    log_path = output / 'eval_log.jsonl'
    with log_path.open('a') as handle:
        handle.write(json.dumps(stats, default=str) + '\n')

    report = f"""# Forward eval (paper window)

Okno: {start.date()} → {end.date()} (exclusive).

| Leg | PnL | $/dzień |
|-----|----:|--------:|
| A ALT+RM | ${stats['a_net']:.2f} | ${stats['a_net'] / stats['days']:.3f} |
| B router | ${stats['b_net']:.2f} | ${stats['b_net'] / stats['days']:.3f} |
| **Razem** | **${stats['net_pnl']:.2f}** | **${stats['mean_calendar_day_pnl']:.3f}** |

Gap do $5: **${stats['gap_to_5']:.2f}/d**. B tradów: {stats['b_trades']}.
"""
    (output / 'LATEST_REPORT.md').write_text(report)
    print(report)


if __name__ == '__main__':
    main()
