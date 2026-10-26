"""Continuous frozen replay for S94 Wyckoff Phase-C."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.wyckoff_phase_c import WyckoffPhaseCConfig, build_wyckoff_signals
from .book_ab_portfolio_combo import daily_pnl_from_equity
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT',
           'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT')
WARMUP, START, END = '2024-08-01', '2025-05-01', '2026-09-01'
SLICES = {
    'development_1': ('2025-05-01', '2025-10-01'),
    'development_2': ('2025-10-01', '2026-04-01'),
    'development_3': ('2026-04-01', END),
}


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def _execution(config, scenario):
    base = config.execution()
    if scenario == 'stress':
        return replace(base, fee_bps=8.0, maker_fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(base, fee_bps=10.0, maker_fee_bps=10.0, slippage_bps=10.0)
    return base


def _slice_metrics(daily, start, end, initial=500.0):
    start, end = _utc(start), _utc(end)
    selected = daily.loc[(daily.index >= start) & (daily.index < end)]
    before = daily.loc[daily.index < start]
    start_nav = initial + float(before.sum())
    full_equity = initial + daily.cumsum()
    peak = pd.concat([
        pd.Series([initial], index=[daily.index.min() - pd.Timedelta(days=1)]),
        full_equity,
    ]).cummax().iloc[1:]
    dd = 1.0 - full_equity.reindex(selected.index) / peak.reindex(selected.index)
    return {
        'net_pnl': float(selected.sum()),
        'return_on_start_nav_pct': float(selected.sum() / start_nav * 100),
        'usd_per_calendar_day': float(selected.sum() / max(1, (end - start).days)),
        'max_continuous_drawdown_pct': float(dd.max() * 100) if len(dd) else 0.0,
    }


def _selected_trades(trades, start, end):
    start, end = _utc(start), _utc(end)
    return [trade for trade in trades if start <= _utc(trade['closed_at']) < end]


def _trade_stats(trades):
    pnl = np.array([trade['pnl'] for trade in trades], dtype=float)
    gain = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    loss = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
    return {
        'trades': len(trades),
        'profit_factor': gain / loss if loss else (None if not gain else 'Infinity'),
        'mean_net_r': float(np.mean([trade['r_multiple'] for trade in trades])) if trades else 0.0,
        'longs': sum(trade['side'] == 'LONG' for trade in trades),
        'shorts': sum(trade['side'] == 'SHORT' for trade in trades),
        'independent_event_clusters': len({
            _utc(trade['opened_at']).floor('12h') for trade in trades
        }),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s94_wyckoff_phase_c')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = WyckoffPhaseCConfig()
    markets, signals, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        signals[symbol] = build_wyckoff_signals(minutes, config)
        print(symbol, len(signals[symbol]), 'signals', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    result = {
        'protocol_sha256': protocol_hash,
        'config': asdict(config),
        'signals': {symbol: len(items) for symbol, items in signals.items()},
        'continuous_replays': {},
        'slices': {},
        'disclosure': 'All history is development-only; prospective T0 is 2026-10-14 UTC.',
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
    stress_pf = stress['profit_factor']
    pf_value = float('inf') if stress_pf == 'Infinity' else (float(stress_pf) if stress_pf else 0.0)
    historical_pass = (
        stress['trades'] >= 30
        and stress['net_pnl'] > 0
        and pf_value >= 1.15
        and stress['mean_net_r'] >= 0.08
        and stress['max_drawdown_pct'] <= 6.0
        and severe['net_pnl'] >= 0
    )
    result['decision'] = (
        'HISTORICAL_CORE_GATE_PASSED_PENDING_LOSO_AND_PAPER_FORWARD'
        if historical_pass else 'REJECTED_AT_HISTORICAL_CORE_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')

    lines = [
        '# S94 — causal Wyckoff Phase-C', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        'All intervals are development diagnostics, not OOS.', '',
        '| Slice | Costs | Trades | Long/short | Clusters | PF | Mean R | PnL | Return | DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | '
                f'{row["longs"]}/{row["shorts"]} | {row["independent_event_clusters"]} | '
                f'{pf} | {row["mean_net_r"]:.3f} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_start_nav_pct"]:.2f}% | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {result["decision"]}.**', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
