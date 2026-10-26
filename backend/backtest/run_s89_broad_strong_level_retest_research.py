"""Frozen retrospective evaluation for S89 Broad Strong Level Retest."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.broad_strong_level_retest import BroadStrongLevelRetestConfig
from l1_filter.hourly_strong_level_retest import hourly_strong_level_signals
from .cluster_scalp_simulator import execute_cluster
from .level_retest_orders import materialize_first_retests
from .run_s87_strong_level_retest_research import _development_pass, _numeric_pf
from .scalp_data import load_archives


TRADED = (
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
    'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT',
)
WARMUP, END = '2025-03-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-07-01', '2026-01-01'),
    'validation': ('2026-01-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _execution(config, scenario):
    execution = config.execution()
    if scenario == 'stress':
        return replace(
            execution, maker_fee_bps=5.0, fee_bps=8.0,
            slippage_bps=5.0, limit_penetration_bps=5.0)
    if scenario == 'severe':
        return replace(
            execution, maker_fee_bps=10.0, fee_bps=10.0,
            slippage_bps=10.0, limit_penetration_bps=10.0)
    return execution


def _validation_pass(scenarios):
    base, stress = scenarios['base'], scenarios['stress']
    contribution = base['largest_symbol_gross_profit_share_pct']
    return (
        base['trades'] >= 10
        and _numeric_pf(base) >= 1.15
        and _numeric_pf(stress) >= 1.00
        and base['positive_symbols'] >= 3
        and contribution is not None
        and contribution <= 50
    )


def _report(result):
    lines = [
        '# S89 — Broad Strong Level Retest',
        '',
        f'Hash zamrożonego protokołu: `{result["protocol_sha256"]}`.',
        '',
        'Jedna strategia na ośmiu płynnych rynkach. Niezależne limity mogą ',
        'czekać równolegle, ale konto utrzymuje tylko jedną pozycję. ',
        'Badanie retrospektywne; brak zgody na live.',
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
        f'Surowe setupy: {result["raw_candidates_by_window"]}.',
        '',
        f'Wykonalne pierwsze re-testy: {result["materialized_by_window_and_scenario"]}.',
        '',
        'Kapitał $250; ryzyko 0,20%; maksymalnie jedna otwarta pozycja; ',
        'notional do 1x equity; lewar do 5x. Wynik odrzucony na dowolnej ',
        'niezaliczonej bramce nie jest strojony ani wdrażany.',
        '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s89_broad_strong_level_retest')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before data are loaded')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = BroadStrongLevelRetestConfig()
    markets, raw, manifest = {}, {}, {}
    for symbol in TRADED:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, str(cache))
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        _, raw[symbol] = hourly_strong_level_signals(minutes, config)
        print(symbol, len(raw[symbol]), 'armed levels', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    bounds = {
        name: (pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC'))
        for name, (start, end) in WINDOWS.items()
    }
    executions = {
        scenario: _execution(config, scenario)
        for scenario in ('base', 'stress', 'severe')
    }
    materialized = {
        scenario: {
            symbol: materialize_first_retests(
                markets[symbol][0], raw[symbol], execution.limit_penetration_bps)
            for symbol in TRADED
        }
        for scenario, execution in executions.items()
    }
    result = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective research; not paper-forward and not live-approved',
        'config': asdict(config),
        'raw_candidates_by_window': {
            name: sum(
                start <= signal['timestamp'] < end
                for signals in raw.values() for signal in signals)
            for name, (start, end) in bounds.items()
        },
        'materialized_by_window_and_scenario': {
            scenario: {
                name: sum(
                    start <= signal['timestamp'] < end
                    for signals in scenario_signals.values() for signal in signals)
                for name, (start, end) in bounds.items()
            }
            for scenario, scenario_signals in materialized.items()
        },
        'windows': {},
    }

    def evaluate(window):
        result['windows'][window] = {}
        for scenario, execution in executions.items():
            replay = execute_cluster(
                markets, materialized[scenario], execution,
                *WINDOWS[window], initial_capital=250.0,
                symbol_priority=TRADED)
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
