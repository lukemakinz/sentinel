"""One replay path for frozen BENCH_AB_R2 (OOS checks and daily paper-forward)."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import requests

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig, build_routed_quiet_signals
from .book_a_portfolio_sim import simulate_book_a
from .book_ab_portfolio_combo import daily_pnl_from_equity, merge_book_daily
from .cluster_scalp_simulator import execute_cluster
from .oos_data import load_through
from .run_bench_ab_r2 import COSTS, SYMBOLS, WARMUP
from .scalp_data import BASE_URL, DAILY_BASE_URL

BOOK_CAPITAL = 250.0


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _published(url: str) -> bool:
    try:
        return requests.head(url, timeout=20, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def available_bounds(today: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(monthly_end, end): first month without a monthly archive, last published day + 1."""
    today = today.tz_convert('UTC').normalize()
    month_start = today.replace(day=1)
    previous = (month_start - pd.Timedelta(days=1)).replace(day=1)
    probe = f"{BASE_URL}/klines/BTCUSDT/1m/BTCUSDT-1m-{previous:%Y-%m}.zip"
    monthly_end = month_start if _published(probe) else previous
    end = today
    while end > monthly_end:
        day = end - pd.Timedelta(days=1)
        if all(_published(f"{DAILY_BASE_URL}/klines/{s}/1m/{s}-1m-{day:%Y-%m-%d}.zip")
               for s in SYMBOLS):
            break
        end = day
    return monthly_end, end


def load_market(cache: str, monthly_end, end) -> tuple[dict, dict, dict]:
    minutes, funding, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes[symbol], funding[symbol], manifest[symbol] = load_through(
            symbol, WARMUP, end, cache, monthly_end)
    return minutes, funding, manifest


def book_b_signals(minutes: dict) -> dict:
    return {'BTCUSDT': build_routed_quiet_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', BookBQuietRouterConfig())}


def replay(minutes, funding, signals_b, start, end, scenario: str) -> dict:
    """Daily PnL of Book A, Book B and the $500 total for one cost scenario."""
    cost = COSTS[scenario]
    start_ts, end_ts = _utc(start), _utc(end)
    book_a = simulate_book_a(
        minutes, replace(BOOK_A_ALT_RM, taker_fee_bps=cost['a']),
        start_ts, end_ts, BOOK_CAPITAL, risk=BOOK_A_RISK_DEFAULT)
    config_b = replace(
        BookBQuietBreakoutConfig().execution(),
        fee_bps=cost['fee'], maker_fee_bps=cost['fee'], slippage_bps=cost['slip'],
        fixed_risk_usd=6.0, drawdown_halt_fraction=0.28, daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
    )
    book_b = execute_cluster(
        {'BTCUSDT': (minutes['BTCUSDT'], funding['BTCUSDT'])},
        signals_b, config_b, start_ts, end_ts, BOOK_CAPITAL, ('BTCUSDT',))
    daily_b = daily_pnl_from_equity(book_b['daily_equity'], BOOK_CAPITAL)
    return {
        'daily': merge_book_daily(book_a.daily_pnl, daily_b),
        'daily_a': book_a.daily_pnl,
        'daily_b': daily_b,
        'trades_b': book_b['summary']['trades'],
    }
