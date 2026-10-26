"""Compare continuous BENCH_AB_R3 with frozen Book A + strict Book B v2."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
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
from .book_ab_portfolio_combo import daily_pnl_from_equity, merge_book_daily
from .cluster_scalp_simulator import execute_cluster
from .run_bench_ab_r3 import _slice_summary
from .scalp_data import load_archives


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WARMUP, START, END = '2024-08-01', '2025-05-01', '2026-09-01'
SLICES = {
    'development_1': ('2025-05-01', '2025-10-01'),
    'development_2': ('2025-10-01', '2026-04-01'),
    'development_3': ('2026-04-01', END),
}
COSTS = {
    'base': {'a': 7.0, 'fee': 7.0, 'slip': 2.0},
    'stress': {'a': 12.0, 'fee': 8.0, 'slip': 5.0},
    'severe': {'a': 20.0, 'fee': 10.0, 'slip': 10.0},
}


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _execution(cost):
    return replace(
        BookBQuietBreakoutConfig().execution(),
        fee_bps=cost['fee'], maker_fee_bps=cost['fee'],
        slippage_bps=cost['slip'], fixed_risk_usd=6.0,
        drawdown_halt_fraction=0.28, daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
    )


def _block_bootstrap_lower(excess: pd.Series, block=28, samples=10000, seed=9404):
    values = excess.to_numpy(dtype=float)
    if not len(values):
        return 0.0
    rng = np.random.default_rng(seed)
    starts = np.arange(max(1, len(values) - block + 1))
    draws = []
    blocks_needed = int(np.ceil(len(values) / block))
    for _ in range(samples):
        selected = np.concatenate([
            values[s:s + block] for s in rng.choice(starts, blocks_needed, replace=True)
        ])[:len(values)]
        draws.append(float(selected.sum()))
    return float(np.quantile(draws, 0.025))


def _compare(base_daily, challenger_daily, start, end):
    start, end = _utc(start), _utc(end)
    base = base_daily.loc[(base_daily.index >= start) & (base_daily.index < end)]
    challenger = challenger_daily.loc[
        (challenger_daily.index >= start) & (challenger_daily.index < end)]
    frame = pd.DataFrame({'base': base, 'challenger': challenger}).fillna(0.0)
    excess = frame.challenger - frame.base
    return {
        'excess_pnl': float(excess.sum()),
        'positive_excess_month_share': float((excess.resample('ME').sum() > 0).mean()),
        'paired_28d_bootstrap_95_lower_excess_pnl': _block_bootstrap_lower(excess),
    }


def _closed_count(trades, start, end):
    start, end = _utc(start), _utc(end)
    return sum(start <= _utc(trade['closed_at']) < end for trade in trades)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/book_ab_r4_quiet_v2')
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

    baseline_signals = {'BTCUSDT': build_routed_quiet_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', BookBQuietRouterConfig())}
    challenger_signals = {'BTCUSDT': build_quiet_breakout_signals(
        minutes['BTCUSDT'], minutes, 'BTCUSDT', BOOK_B_QUIET_V2)}
    market = {'BTCUSDT': (minutes['BTCUSDT'], funding['BTCUSDT'])}
    result = {
        'protocol_sha256': protocol_hash,
        'signal_counts': {
            'r3_router': len(baseline_signals['BTCUSDT']),
            'r4_quiet_v2': len(challenger_signals['BTCUSDT']),
        },
        'full': {}, 'slices': {},
    }
    for scenario, cost in COSTS.items():
        a = simulate_book_a(
            minutes, replace(BOOK_A_ALT_RM, taker_fee_bps=cost['a']),
            _utc(START), _utc(END), 250.0, risk=BOOK_A_RISK_DEFAULT)
        execution = _execution(cost)
        b_base = execute_cluster(
            market, baseline_signals, execution, START, END, 250.0, ('BTCUSDT',))
        b_new = execute_cluster(
            market, challenger_signals, execution, START, END, 250.0, ('BTCUSDT',))
        base_daily = merge_book_daily(
            a.daily_pnl, daily_pnl_from_equity(b_base['daily_equity'], 250.0))
        new_daily = merge_book_daily(
            a.daily_pnl, daily_pnl_from_equity(b_new['daily_equity'], 250.0))
        result['full'][scenario] = {
            'r3': {**_slice_summary(base_daily, START, END),
                   'book_b_pnl': b_base['summary']['net_pnl'],
                   'book_b_trades': b_base['summary']['trades']},
            'r4': {**_slice_summary(new_daily, START, END),
                   'book_b_pnl': b_new['summary']['net_pnl'],
                   'book_b_trades': b_new['summary']['trades']},
            **_compare(base_daily, new_daily, START, END),
        }
        for name, bounds in SLICES.items():
            result['slices'].setdefault(name, {})[scenario] = {
                'r3': {**_slice_summary(base_daily, *bounds),
                       'book_b_trades': _closed_count(b_base['trades'], *bounds)},
                'r4': {**_slice_summary(new_daily, *bounds),
                       'book_b_trades': _closed_count(b_new['trades'], *bounds)},
                **_compare(base_daily, new_daily, *bounds),
            }
        print(scenario, result['full'][scenario], flush=True)

    stress, severe = result['full']['stress'], result['full']['severe']
    passes = (
        stress['r4']['net_pnl'] > stress['r3']['net_pnl']
        and stress['r4']['max_continuous_drawdown_pct'] <= stress['r3']['max_continuous_drawdown_pct']
        and stress['r4']['expected_shortfall_95_daily_return_pct']
            >= stress['r3']['expected_shortfall_95_daily_return_pct']
        and severe['r4']['net_pnl'] >= severe['r3']['net_pnl']
        and stress['positive_excess_month_share'] >= 0.60
        and stress['paired_28d_bootstrap_95_lower_excess_pnl'] > 0
    )
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if passes else 'REJECTED_AT_HISTORICAL_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')

    lines = [
        '# Book A+B R4 — strict quiet-v2 repair', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Slice | Costs | R3 PnL | R4 PnL | Excess | R3 DD | R4 DD | R3/R4 B trades |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {name} | {scenario} | ${row["r3"]["net_pnl"]:.2f} | '
                f'${row["r4"]["net_pnl"]:.2f} | ${row["excess_pnl"]:.2f} | '
                f'{row["r3"]["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["r4"]["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["r3"]["book_b_trades"]}/{row["r4"]["book_b_trades"]} |')
    lines.extend(['', f'**Decision: {result["decision"]}.**', '',
                  'Historical data are discovery-affected; this is not an OOS profit claim.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
