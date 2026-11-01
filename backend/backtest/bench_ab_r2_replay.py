"""One replay path for frozen BENCH_AB_R2 (OOS checks and daily paper-forward)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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


class ArchiveAvailabilityError(RuntimeError):
    """Archive publication could not be determined safely."""


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _published(url: str) -> bool:
    try:
        response = requests.head(url, timeout=20, allow_redirects=True)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return False
    except requests.RequestException as exc:
        raise ArchiveAvailabilityError(f'cannot probe Binance archive: {url}') from exc


def _cached_archive(cache: str | None, period: str, symbol: str, stamp: str) -> bool:
    if not cache:
        return False
    prefix = Path(cache)
    if period == 'monthly':
        archive = prefix / 'klines' / symbol / '1m' / f'{symbol}-1m-{stamp}.zip'
    else:
        archive = prefix / 'daily' / 'klines' / symbol / '1m' / f'{symbol}-1m-{stamp}.zip'
    return archive.is_file() and archive.with_suffix(archive.suffix + '.CHECKSUM').is_file()


def _all_cached(cache: str | None, period: str, stamp: str) -> bool:
    return all(_cached_archive(cache, period, symbol, stamp) for symbol in SYMBOLS)


def _all_published(period: str, stamp: str) -> bool:
    base = BASE_URL if period == 'monthly' else DAILY_BASE_URL
    return all(_published(f'{base}/klines/{symbol}/1m/{symbol}-1m-{stamp}.zip')
               for symbol in SYMBOLS)


def available_bounds(today: pd.Timestamp, cache: str | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(monthly_end, end): first month without a monthly archive, last published day + 1."""
    today = today.tz_convert('UTC').normalize()
    month_start = today.replace(day=1)
    previous = (month_start - pd.Timedelta(days=1)).replace(day=1)
    month_stamp = previous.strftime('%Y-%m')
    if _all_cached(cache, 'monthly', month_stamp):
        monthly_end = month_start
    else:
        monthly_end = month_start if _all_published('monthly', month_stamp) else previous

    probe_error = None
    end = today
    while end > monthly_end:
        day = end - pd.Timedelta(days=1)
        stamp = day.strftime('%Y-%m-%d')
        if _all_cached(cache, 'daily', stamp):
            break
        try:
            if _all_published('daily', stamp):
                break
        except ArchiveAvailabilityError as exc:
            # A transient network failure must not be mistaken for months of
            # missing data. Continue backwards and use the newest complete,
            # checksumed day already present in the local cache.
            probe_error = exc
        end = day
    if end == monthly_end and probe_error is not None:
        raise probe_error
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
