"""Final frozen H1 variant: confirmation-body midpoint limit."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.h1_trend_pullback import (
    H1TrendPullbackConfig,
    build_h1_features,
    generate_h1_signals,
)
from .run_h1_trend_pullback_v1 import (
    END,
    ROOT,
    TRADED,
    WARMUP,
    WINDOWS,
    _development_pass,
    _run,
    _validation_pass,
)
from .scalp_data import load_archives


def _report(result: dict) -> str:
    lines = [
        '# H1 Trend Pullback Confirm v2', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Final H1 retrospective variant. Live remains disabled.**', '',
        '| Window | Costs | Raw | Fills | WR | PF | Mean R | PnL | Max DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in result['windows'].items():
        for scenario, summary in scenarios.items():
            lines.append(
                f'| {window} | {scenario} | {result["raw_candidates_by_window"][window]} '
                f'| {summary["trades"]} | {summary["win_rate_pct"]:.1f}% '
                f'| {summary["profit_factor"]} | {summary["mean_net_r"]:.3f} '
                f'| ${summary["net_pnl"]:.2f} | {summary["max_drawdown_pct"]:.2f}% |'
            )
    lines.extend(['', f'**Decision: {result["decision"]}.**', ''])
    if result['decision'].startswith('REJECTED'):
        lines.append('H1 family is closed on the shared historical sample; no V3 tuning is allowed.')
    else:
        lines.append('A historical pass permits paper-forward only, never live execution.')
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument(
        '--output', default=str(ROOT / 'docs' / 'research' / 'h1_trend_pullback_confirm_v2'),
    )
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Freeze protocol.json before loading market data')
    digest = sha256(protocol.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'protocol.sha256').write_text(f'{digest}  protocol.json\n')

    data, manifest = {}, {}
    for symbol in TRADED:
        minutes, funding, manifest[symbol] = load_archives(
            symbol, WARMUP, END, args.cache,
        )
        data[symbol] = (minutes, funding)
        print(symbol, 'archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = H1TrendPullbackConfig(
        name='H1_TREND_PULLBACK_CONFIRM_V2',
        entry_mode='confirmation_body_midpoint',
    )
    features = {
        symbol: build_h1_features(data[symbol][0], config)
        for symbol in TRADED
    }
    signals = {
        symbol: generate_h1_signals(features[symbol], config, symbol)
        for symbol in TRADED
    }
    bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    result = {
        'protocol_sha256': digest,
        'config': asdict(config),
        'raw_candidates_by_symbol': {s: len(rows) for s, rows in signals.items()},
        'raw_candidates_by_window': {
            name: sum(start <= row['timestamp'] < end
                      for rows in signals.values() for row in rows)
            for name, (start, end) in bounds.items()
        },
        'windows': {'development': {}},
    }
    for scenario in ('base', 'stress', 'severe'):
        summary, trades = _run(data, signals, config, scenario, 'development')
        result['windows']['development'][scenario] = summary
        (output / f'development_{scenario}_trades.json.gz').write_bytes(
            gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
        )
        print('development', scenario, summary['trades'], summary['profit_factor'],
              f'${summary["net_pnl"]:.2f}', flush=True)

    if not _development_pass(result['windows']['development']['stress']):
        result['decision'] = 'REJECTED_AT_DEVELOPMENT_STRESS_GATE'
    else:
        result['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run(data, signals, config, scenario, 'validation')
            result['windows']['validation'][scenario] = summary
            (output / f'validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
            )
        if not _validation_pass(result['windows']['validation']['stress']):
            result['decision'] = 'REJECTED_AT_VALIDATION_STRESS_GATE'
        else:
            result['windows']['retrospective_diagnostic'] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary, trades = _run(
                    data, signals, config, scenario, 'retrospective_diagnostic',
                )
                result['windows']['retrospective_diagnostic'][scenario] = summary
                (output / f'diagnostic_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(json.dumps(trades, allow_nan=False).encode(), mtime=0),
                )
            result['decision'] = 'HISTORICAL_PASS_PAPER_FORWARD_ONLY'

    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n',
    )
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
