"""Continuous frozen replay for S95 Wyckoff Phase-D SOS/SOW + LPS/LPSY."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

from l1_filter.wyckoff_phase_d import WyckoffPhaseDConfig, build_wyckoff_phase_d_signals
from .book_ab_portfolio_combo import daily_pnl_from_equity
from .cluster_scalp_simulator import execute_cluster
from .run_s94_wyckoff_phase_c import SLICES, SYMBOLS, WARMUP, START, END, _slice_metrics, _trade_stats
from .scalp_data import load_archives


def _execution(config, scenario):
    base = config.execution()
    if scenario == 'stress':
        return replace(base, fee_bps=8.0, maker_fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(base, fee_bps=10.0, maker_fee_bps=10.0, slippage_bps=10.0)
    return base


def _utc(value):
    import pandas as pd
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _selected_trades(trades, start, end):
    start, end = _utc(start), _utc(end)
    return [trade for trade in trades if start <= _utc(trade['closed_at']) < end]


def _pf_value(value):
    return float('inf') if value == 'Infinity' else (float(value) if value else 0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s95_wyckoff_phase_d')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = WyckoffPhaseDConfig()
    markets, signals, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        signals[symbol] = build_wyckoff_phase_d_signals(minutes, config)
        print(symbol, len(signals[symbol]), 'signals', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    result = {
        'protocol_sha256': protocol_hash,
        'config': asdict(config),
        'signals': {symbol: len(items) for symbol, items in signals.items()},
        'continuous_replays': {}, 'slices': {},
        'disclosure': 'All history is development-only.',
    }
    for scenario in ('base', 'stress', 'severe'):
        replay = execute_cluster(
            markets, signals, _execution(config, scenario), START, END,
            initial_capital=500.0, symbol_priority=SYMBOLS)
        daily = daily_pnl_from_equity(replay['daily_equity'], 500.0)
        result['continuous_replays'][scenario] = replay['summary']
        (output / f'continuous_{scenario}_trades.json.gz').write_bytes(
            gzip.compress(json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        for name, bounds in SLICES.items():
            trades = _selected_trades(replay['trades'], *bounds)
            row = {**_slice_metrics(daily, *bounds), **_trade_stats(trades)}
            result['slices'].setdefault(name, {})[scenario] = row
            print(name, scenario, row, flush=True)

    stress = result['continuous_replays']['stress']
    severe = result['continuous_replays']['severe']
    passed = (
        stress['trades'] >= 30 and stress['net_pnl'] > 0
        and _pf_value(stress['profit_factor']) >= 1.15
        and stress['mean_net_r'] >= 0.08
        and stress['max_drawdown_pct'] <= 6.0
        and severe['net_pnl'] >= 0
    )
    result['decision'] = (
        'HISTORICAL_CORE_GATE_PASSED_PENDING_ROBUSTNESS_AND_PAPER_FORWARD'
        if passed else 'REJECTED_AT_HISTORICAL_CORE_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    lines = [
        '# S95 — Wyckoff Phase-D SOS/SOW + LPS/LPSY', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Slice | Costs | Trades | Long/short | PF | Mean R | PnL | Return | DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | {row["longs"]}/{row["shorts"]} | '
                f'{pf} | {row["mean_net_r"]:.3f} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_start_nav_pct"]:.2f}% | {row["max_continuous_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {result["decision"]}.**', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
