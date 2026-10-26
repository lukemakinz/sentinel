"""Combine Book A + Book B $/day vs $5 goal (validation window)."""
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from .book_a_portfolio_sim import simulate_book_a
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD
from .scalp_data import load_archives


START, END = '2025-10-01', '2026-01-01'
BOOK_A_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
BOOK_B_SYMBOLS = ('BTCUSDT', 'ETHUSDT')
WARMUP = '2025-04-01'


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/portfolio_two_books'
    output.mkdir(parents=True, exist_ok=True)

    minutes_a = {}
    for symbol in BOOK_A_SYMBOLS:
        minutes_a[symbol], _, _ = load_archives(symbol, '2024-08-01', END, cache)

    start_ts = pd.Timestamp(START, tz='UTC')
    end_ts = pd.Timestamp(END, tz='UTC')
    book_a = simulate_book_a(
        minutes_a,
        BOOK_A_ALT_RM,
        start_ts,
        end_ts,
        250.0,
        risk=BOOK_A_RISK_DEFAULT,
    )

    router = BookBQuietRouterConfig()
    exec_b = replace(
        BookBQuietBreakoutConfig().execution(),
        drawdown_halt_fraction=0.28,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
        fixed_risk_usd=6.0,
    )
    signals = {
        'BTCUSDT': build_routed_quiet_signals(
            minutes_a['BTCUSDT'], minutes_a, 'BTCUSDT', router),
    }
    markets = {
        'BTCUSDT': (
            minutes_a['BTCUSDT'],
            load_archives('BTCUSDT', WARMUP, END, cache)[1],
        ),
    }
    book_b = execute_cluster(
        markets, signals, exec_b,
        start_ts, end_ts, initial_capital=250, symbol_priority=('BTCUSDT',),
    )

    days = max(1, (pd.Timestamp(END) - pd.Timestamp(START)).days)
    a_day = book_a.summary['net_pnl'] / days
    b_day = book_b['summary']['net_pnl'] / days
    total = a_day + b_day
    gap = DAILY_GOAL_USD - total

    payload = {
        'window': [START, END],
        'book_a_usd_per_day': a_day,
        'book_b_usd_per_day': b_day,
        'combined_usd_per_day': total,
        'gap_to_5_usd_day': gap,
        'book_a_net': book_a.summary['net_pnl'],
        'book_b_net': book_b['summary']['net_pnl'],
    }
    (output / 'summary.json').write_text(json.dumps(payload, indent=2) + '\n')
    report = f"""# Portfolio A+B — validation window

Okno: {START} → {END} ({days} dni kalendarzowych).

| Księga | Kapitał | PnL okna | **$/dzień** |
|--------|--------:|---------:|------------:|
| A ALT+RM (no BTC leg) | $250 | ${book_a.summary['net_pnl']:.2f} | **${a_day:.3f}** |
| B S84 quiet router | $250 | ${book_b['summary']['net_pnl']:.2f} | **${b_day:.3f}** |
| **Razem** | **$500** | **${book_a.summary['net_pnl'] + book_b['summary']['net_pnl']:.2f}** | **${total:.3f}** |

Cel: **${DAILY_GOAL_USD}/dzień**. **Brakuje: ${gap:.2f}/dzień**.
"""
    (output / 'REPORT.md').write_text(report)
    print(report)


if __name__ == '__main__':
    main()
