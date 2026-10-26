"""Continuous frozen replay for S93 delta-neutral basis compression."""
import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.basis_compression import (
    BasisCompressionConfig,
    basis_compression_signals,
    basis_features,
)
from .book_ab_portfolio_combo import daily_pnl_from_equity
from .perp_spot_basis_reversion import execute_basis_compression
from .run_s94_wyckoff_phase_c import SLICES, WARMUP, START, END, _slice_metrics
from .scalp_data import load_archives
from .spot_data import load_spot_archives


SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
COSTS = {
    'base': {'spot_side': 12.0, 'perp_side': 7.0, 'leg_risk': 4.0},
    'stress': {'spot_side': 15.0, 'perp_side': 13.0, 'leg_risk': 10.0},
    'severe': {'spot_side': 20.0, 'perp_side': 20.0, 'leg_risk': 20.0},
}


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _selected(trades, start, end):
    start, end = _utc(start), _utc(end)
    return [trade for trade in trades if start <= _utc(trade['closed_at']) < end]


def _stats(trades):
    pnl = np.array([t['pnl'] for t in trades], dtype=float)
    gain = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    loss = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
    return {
        'trades': len(trades),
        'profit_factor': gain / loss if loss else (None if not gain else 'Infinity'),
        'per_symbol_pnl': {
            symbol: float(sum(t['pnl'] for t in trades if t['symbol'] == symbol))
            for symbol in SYMBOLS
        },
    }


def _pf(value):
    return float('inf') if value == 'Infinity' else (float(value) if value else 0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s93_basis_compression')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    spots, perps, funding, manifest = {}, {}, {}, {}
    for symbol in SYMBOLS:
        spots[symbol], spot_sources = load_spot_archives(symbol, WARMUP, END, args.cache)
        perps[symbol], funding[symbol], perp_sources = load_archives(
            symbol, WARMUP, END, args.cache)
        manifest[symbol] = {'spot': spot_sources, 'perpetual': perp_sources}
        print(symbol, len(spots[symbol]), 'common spot minutes', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = BasisCompressionConfig()
    features, signals = {}, {}
    for symbol in SYMBOLS:
        features[symbol] = basis_features(spots[symbol], perps[symbol], config)
        signals[symbol] = basis_compression_signals(
            features[symbol], funding[symbol], symbol, config)
        print(symbol, len(signals[symbol]), 'signals', flush=True)

    markets = {symbol: (perps[symbol], funding[symbol]) for symbol in SYMBOLS}
    result = {
        'protocol_sha256': protocol_hash, 'config': asdict(config),
        'signals': {s: len(v) for s, v in signals.items()},
        'continuous_replays': {}, 'slices': {},
    }
    replays = {}
    for scenario, cost in COSTS.items():
        replay = execute_basis_compression(
            spots, markets, features, signals, config, START, END, 500.0,
            costs=cost, symbol_priority=SYMBOLS)
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
        stress['trades'] >= 20 and stress['net_pnl'] > 0
        and _pf(stress['profit_factor']) >= 1.20
        and stress['max_drawdown_pct'] <= 2.0
        and severe['net_pnl'] >= 0
    )
    if stress['trades'] == 0:
        result['decision'] = 'INCONCLUSIVE_NO_EPISODES_AT_FROZEN_COST_THRESHOLD'
    else:
        result['decision'] = (
            'HISTORICAL_CORE_GATE_PASSED_PENDING_LOSO_AND_PAPER_FORWARD'
            if core_pass else 'REJECTED_AT_HISTORICAL_CORE_GATE'
        )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    lines = [
        '# S93 — delta-neutral basis compression', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Slice | Costs | Episodes | PF | PnL | Return | DD |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | {pf} | '
                f'${row["net_pnl"]:.2f} | {row["return_on_start_nav_pct"]:.2f}% | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {result["decision"]}.**', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
