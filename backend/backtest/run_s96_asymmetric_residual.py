"""Continuous frozen replay for S96 asymmetric residual reversal."""
import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.asymmetric_residual_reversal import (
    AsymmetricResidualConfig,
    build_asymmetric_residual,
)
from .book_ab_portfolio_combo import daily_pnl_from_equity
from .residual_pair_simulator import execute_residual_pairs
from .run_s94_wyckoff_phase_c import SLICES, WARMUP, START, END, _slice_metrics
from .scalp_data import load_archives


ALTS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
        'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT')
SYMBOLS = ('BTCUSDT', *ALTS)
COSTS = {
    'base': {'fee': 5.0, 'slip': 2.0},
    'stress': {'fee': 8.0, 'slip': 5.0},
    'severe': {'fee': 10.0, 'slip': 10.0},
}


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _selected(trades, start, end):
    start, end = _utc(start), _utc(end)
    return [trade for trade in trades if start <= _utc(trade['closed_at']) < end]


def _stats(trades):
    pnl = np.array([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    losses = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
    return {
        'trades': len(trades),
        'profit_factor': gains / losses if losses else (None if not gains else 'Infinity'),
        'mean_net_r': float(np.mean([trade['r_multiple'] for trade in trades])) if trades else 0.0,
        'independent_clusters': len({_utc(trade['opened_at']).floor('12h') for trade in trades}),
        'per_symbol_pnl': {
            symbol: float(sum(trade['pnl'] for trade in trades if trade['symbol'] == symbol))
            for symbol in ALTS
        },
    }


def _pf(value):
    return float('inf') if value == 'Infinity' else (float(value) if value else 0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s96_asymmetric_residual')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    markets, manifest = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        print(symbol, len(minutes), 'minutes', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = AsymmetricResidualConfig()
    features, signals = {}, {}
    for symbol in ALTS:
        features[symbol], signals[symbol] = build_asymmetric_residual(
            markets[symbol][0], markets['BTCUSDT'][0], symbol, config)
        print(symbol, len(signals[symbol]), 'signals', flush=True)

    result = {
        'protocol_sha256': protocol_hash,
        'config': asdict(config),
        'signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'continuous_replays': {}, 'slices': {}, 'leave_one_symbol_out_stress': {},
    }
    replays = {}
    for scenario, cost in COSTS.items():
        replay = execute_residual_pairs(
            markets, features, signals, config, START, END, 500.0,
            fee_bps=cost['fee'], slippage_bps=cost['slip'],
            symbol_priority=ALTS)
        replays[scenario] = replay
        result['continuous_replays'][scenario] = replay['summary']
        (output / f'continuous_{scenario}_trades.json.gz').write_bytes(
            gzip.compress(json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        daily = daily_pnl_from_equity(replay['daily_equity'], 500.0)
        for name, bounds in SLICES.items():
            row = {**_slice_metrics(daily, *bounds), **_stats(_selected(replay['trades'], *bounds))}
            result['slices'].setdefault(name, {})[scenario] = row
            print(name, scenario, row, flush=True)

    stress, severe = replays['stress']['summary'], replays['severe']['summary']
    core_pass = (
        stress['trades'] >= 30 and stress['net_pnl'] > 0
        and _pf(stress['profit_factor']) >= 1.15
        and stress['mean_net_r'] >= 0.08
        and stress['max_drawdown_pct'] <= 6.0
        and severe['net_pnl'] >= 0
    )
    loso_pass = False
    if core_pass:
        for excluded in ALTS:
            kept = tuple(symbol for symbol in ALTS if symbol != excluded)
            replay = execute_residual_pairs(
                {'BTCUSDT': markets['BTCUSDT'], **{s: markets[s] for s in kept}},
                {s: features[s] for s in kept}, {s: signals[s] for s in kept},
                config, START, END, 500.0, fee_bps=8.0, slippage_bps=5.0,
                symbol_priority=kept)
            result['leave_one_symbol_out_stress'][excluded] = replay['summary']['net_pnl']
        loso_pass = all(value > 0 for value in result['leave_one_symbol_out_stress'].values())
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core_pass and loso_pass else 'REJECTED_AT_HISTORICAL_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')

    lines = [
        '# S96 — asymmetric residual reversal', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Slice | Costs | Pairs | Clusters | PF | Mean R | PnL | Return | DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | {row["independent_clusters"]} | '
                f'{pf} | {row["mean_net_r"]:.3f} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_start_nav_pct"]:.2f}% | {row["max_continuous_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {result["decision"]}.**', '',
                  'Historical data are development-only; no live-profit claim.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
