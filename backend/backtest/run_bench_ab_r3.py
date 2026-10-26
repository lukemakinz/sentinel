"""Run BENCH_AB_R3 as one continuous replay and slice the resulting ledger."""
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
WARMUP, START, END = '2024-08-01', '2025-05-01', '2026-09-01'
SLICES = {
    'development': ('2025-05-01', '2025-10-01'),
    'former_validation_now_diagnostic': ('2025-10-01', '2026-04-01'),
    'former_evaluation_now_diagnostic': ('2026-04-01', END),
}
COSTS = {
    'base': {'a': 7.0, 'fee': 7.0, 'slip': 2.0},
    'stress': {'a': 12.0, 'fee': 8.0, 'slip': 5.0},
    'severe': {'a': 20.0, 'fee': 10.0, 'slip': 10.0},
}


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _slice_summary(full_daily: pd.Series, start, end, initial=500.0) -> dict:
    full_daily = full_daily.sort_index()
    start, end = _utc(start), _utc(end)
    before = full_daily.loc[full_daily.index < start]
    selected = full_daily.loc[(full_daily.index >= start) & (full_daily.index < end)]
    start_nav = initial + float(before.sum())
    full_equity = initial + full_daily.cumsum()
    running_peak = pd.concat([
        pd.Series([initial], index=[full_daily.index.min() - pd.Timedelta(days=1)]),
        full_equity,
    ]).cummax().iloc[1:]
    selected_equity = full_equity.reindex(selected.index)
    selected_peak = running_peak.reindex(selected.index)
    drawdown = 1.0 - selected_equity / selected_peak
    daily_return = selected / (initial + full_daily.cumsum().shift(1).fillna(initial)).reindex(selected.index)
    tail_n = max(1, int(np.ceil(len(daily_return) * 0.05)))
    net = float(selected.sum())
    return {
        'start_nav': float(start_nav),
        'end_nav': float(start_nav + net),
        'net_pnl': net,
        'return_on_slice_start_pct': net / start_nav * 100 if start_nav else 0.0,
        'usd_per_calendar_day': net / max(1, (end - start).days),
        'max_continuous_drawdown_pct': float(drawdown.max() * 100) if len(drawdown) else 0.0,
        'expected_shortfall_95_daily_return_pct': (
            float(daily_return.nsmallest(tail_n).mean() * 100) if len(daily_return) else 0.0
        ),
        'positive_month_share': float((selected.resample('ME').sum() > 0).mean()) if len(selected) else 0.0,
    }


def _trade_count(trades: list[dict], start, end) -> int:
    start, end = _utc(start), _utc(end)
    count = 0
    for trade in trades:
        ts = _utc(trade['closed_at'])
        count += int(start <= ts < end)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/bench_ab_r3')
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
    start_ts, end_ts = _utc(START), _utc(END)
    results = {'protocol_sha256': protocol_hash, 'continuous_execution': {}, 'slices': {}}

    for scenario, cost in COSTS.items():
        config_a = replace(BOOK_A_ALT_RM, taker_fee_bps=cost['a'])
        book_a = simulate_book_a(
            minutes, config_a, start_ts, end_ts, 250.0, risk=BOOK_A_RISK_DEFAULT)
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
        b_daily = daily_pnl_from_equity(book_b['daily_equity'], 250.0)
        daily = merge_book_daily(book_a.daily_pnl, b_daily)
        results['continuous_execution'][scenario] = {
            'book_a_net_pnl': book_a.summary['net_pnl'],
            'book_a_fees': book_a.summary['fees_paid'],
            'book_a_rebalances': book_a.summary['rebalances'],
            'book_b_net_pnl': book_b['summary']['net_pnl'],
            'book_b_trades': book_b['summary']['trades'],
            **_slice_summary(daily, START, END),
        }
        for name, (slice_start, slice_end) in SLICES.items():
            row = _slice_summary(daily, slice_start, slice_end)
            row.update({
                'book_a_net_pnl': float(book_a.daily_pnl.loc[
                    (book_a.daily_pnl.index >= _utc(slice_start))
                    & (book_a.daily_pnl.index < _utc(slice_end))].sum()),
                'book_b_net_pnl': float(b_daily.loc[
                    (b_daily.index >= _utc(slice_start))
                    & (b_daily.index < _utc(slice_end))].sum()),
                'book_b_trades_closed': _trade_count(book_b['trades'], slice_start, slice_end),
            })
            results['slices'].setdefault(name, {})[scenario] = row
            print(name, scenario, row, flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = [
        '# BENCH_AB_R3 — continuous quantity-ledger benchmark', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        'All slices below are contaminated development diagnostics, not OOS.', '',
        '| Slice | Costs | A PnL | B PnL | B trades | Total | Return | $/day | Continuous DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in results['slices'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {name} | {scenario} | ${row["book_a_net_pnl"]:.2f} | '
                f'${row["book_b_net_pnl"]:.2f} | {row["book_b_trades_closed"]} | '
                f'${row["net_pnl"]:.2f} | {row["return_on_slice_start_pct"]:.2f}% | '
                f'${row["usd_per_calendar_day"]:.3f} | {row["max_continuous_drawdown_pct"]:.2f}% |')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
