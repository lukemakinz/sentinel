"""Frozen retrospective evaluation for S88 Hourly Strong Level Retest."""
import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.hourly_strong_level_retest import (
    HourlyStrongLevelRetestConfig,
    hourly_strong_level_signals,
)
from .run_s87_strong_level_retest_research import (
    END,
    TRADED,
    WARMUP,
    WINDOWS,
    _development_pass,
    _run_window,
    _validation_pass,
)
from .scalp_data import load_archives


def _report(result: dict) -> str:
    lines = [
        '# S88 — Hourly Strong Level Retest',
        '',
        f'Hash zamrożonego protokołu: `{result["protocol_sha256"]}`.',
        '',
        'Jedna trasa zastępująca zbyt rzadką S87: 1h causalny order block, ',
        'wielokrotnie potwierdzony S/R, score siły i limit oczekujący przed ',
        'pierwszym re-testem. Badanie retrospektywne; brak zgody na live.',
        '',
        '| Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in result['windows'].items():
        for scenario, summary in scenarios.items():
            pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
            lines.append(
                f'| {window} | {scenario} | {summary["trades"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {pf} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% |'
            )
    lines.extend([
        '',
        f'**Decyzja: {result["decision"]}.**',
        '',
        f'Surowe setupy w oknach: {result["raw_candidates_by_window"]}.',
        '',
        'Kapitał $250; ryzyko 0,20%; jeden globalny pending i jedna pozycja; ',
        'notional maks. 1x equity; lewar maks. 5x. Brak siatki parametrów i ',
        'brak wyboru „najmniej złej” wersji po wyniku.',
        '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s88_hourly_strong_level_retest')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before data are loaded')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = HourlyStrongLevelRetestConfig()
    markets, manifest, signals = {}, {}, {}
    for symbol in TRADED:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, str(cache))
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        _, signals[symbol] = hourly_strong_level_signals(minutes, config)
        print(symbol, len(signals[symbol]), 'hourly strong levels', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    result = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective research; not paper-forward and not live-approved',
        'config': asdict(config),
        'raw_candidates_by_window': {
            name: sum(
                start <= signal['timestamp'] < end
                for symbol_signals in signals.values()
                for signal in symbol_signals
            )
            for name, (start, end) in bounds.items()
        },
        'windows': {},
    }

    def evaluate(window):
        result['windows'][window] = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = _run_window(
                markets, signals, config, scenario, *WINDOWS[window])
            result['windows'][window][scenario] = replay['summary']
            payload = json.dumps(replay['trades'], allow_nan=False).encode()
            (output / f'{window}_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
            summary = replay['summary']
            print(window, scenario, summary['trades'], summary['profit_factor'],
                  f'${summary["net_pnl"]:.2f}', flush=True)

    evaluate('development')
    if not _development_pass(result['windows']['development']):
        result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
    else:
        evaluate('validation')
        if not _validation_pass(result['windows']['validation']):
            result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        else:
            evaluate('retrospective_evaluation')
            result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'

    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))


if __name__ == '__main__':
    main()
