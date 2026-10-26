"""Reproducible S7 experiment: python -m backtest.run_scalp_research --help.

Selection is completed and saved BEFORE the holdout is evaluated. No live
scanner/executor registration: an unsuccessful experiment must not start trading.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from l1_filter.scalp_strategy import ScalpConfig, build_features, generate_signals
from .scalp_data import load_archives
from .scalp_simulator import execute


def variants():
    strict = ScalpConfig()
    hybrid = replace(strict, name='S7_hybrid_5m_3of5', mode='hybrid', profile='rolling_6h')
    control = replace(hybrid, name='control_momentum_5m_3of5', mode='momentum', require_divergence=False)
    return [strict, replace(strict, name='S7_reclaim_15m_3of5', minutes=15),
            hybrid, replace(hybrid, name='S7_hybrid_5m_2of5', min_score=2),
            replace(hybrid, name='S7_hybrid_5m_4of5', min_score=4),
            replace(hybrid, name='S7_hybrid_15m_3of5', minutes=15),
            replace(hybrid, name='S7_hybrid_5m_fixed_exit', trailing=False),
            control, replace(control, name='control_momentum_5m_4of5', min_score=4)]


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s7_scalping')
    parser.add_argument('--symbols', nargs='+', default=['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'])
    parser.add_argument('--data-start', default='2025-12-01')
    parser.add_argument('--train-start', default='2025-12-03')
    parser.add_argument('--validation-start', default='2026-02-01')
    parser.add_argument('--test-start', default='2026-03-01')
    parser.add_argument('--end', default='2026-04-01')
    args = parser.parse_args()
    if not args.data_start < args.train_start < args.validation_start < args.test_start < args.end:
        parser.error('Dates must increase: data < train < validation < test < end')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    configs = variants()
    protocol = {'created_at': datetime.now(timezone.utc).isoformat(), 'arguments': vars(args),
                'variants': [asdict(x) for x in configs],
                'selection_rule': 'Rank S7 variants by validation mean net return minus 0.5 * mean max DD. '
                                  'Prefer variants with positive return, PF > 1 and >=3 trades/calendar day '
                                  'on EVERY pair. If none qualify, select diagnostic best without live approval.',
                'holdout_benchmarks': ['S7_reclaim_5m_3of5', 'control_momentum_5m_3of5'],
                'costs': '5 bps taker fee + 2 bps adverse slippage per side; stress 5 bps slippage. '
                         'Actual funding rates, minute-open price proxy for mark price.',
                'limitations': ['Profile approximated from 1m typical price weighted by volume (48 bins).',
                                '1m intrabar ordering unknown: old stop takes precedence over targets.',
                                'No queue, latency, exchange quantity rounding, or order rejection model.',
                                'Independent accounts per pair, not a combined correlated portfolio.',
                                'No live deployment; target frequency is assessed, never enforced.']}
    save_json(output / 'protocol.json', protocol)
    datasets, feature_cache, signal_cache, manifests = {}, {}, {}, {}
    for symbol in args.symbols:
        minutes, funding, manifest = load_archives(symbol, args.data_start, args.end, args.cache)
        datasets[symbol] = (minutes, funding)
        manifests[symbol] = manifest
        for config in configs:
            key = (symbol, config.minutes, config.profile)
            if key not in feature_cache:
                feature_cache[key] = build_features(minutes, config.minutes, config.profile)
            signal_cache[symbol, config.name] = generate_signals(feature_cache[key], config)
        print(f'{symbol}: {len(minutes):,} verified 1m bars; features ready', flush=True)
    save_json(output / 'data_manifest.json', manifests)

    summaries = []

    def run(config, symbol, phase, start, end):
        minutes, funding = datasets[symbol]
        result = execute(minutes, funding, signal_cache[symbol, config.name],
                         feature_cache[symbol, config.minutes, config.profile], config, start, end)
        row = {'variant': config.name, 'symbol': symbol, 'phase': phase, **result['summary']}
        summaries.append(row)
        # Store every exit and full daily entry counts; no truncation at 500 trades.
        save_json(output / f'{phase}_{symbol}_{config.name}.json', result)
        print(f"{phase} {symbol} {config.name}: n={row['trades']} "
              f"day={row['trades_per_day']:.2f} net={row['return_pct']:.2f}% "
              f"PF={row['profit_factor']} DD={row['max_drawdown_pct']:.2f}%", flush=True)
        return row

    for phase, start, end in [('train', args.train_start, args.validation_start),
                              ('validation', args.validation_start, args.test_start)]:
        for config in configs:
            for symbol in args.symbols:
                run(config, symbol, phase, start, end)

    rankings = []
    for config in configs:
        if config.mode == 'momentum':
            continue
        rows = [x for x in summaries if x['phase'] == 'validation' and x['variant'] == config.name]
        qualifies = all(x['trades_per_day'] >= 3 and x['return_pct'] > 0
                        and (x['profit_factor'] or 0) > 1 for x in rows)
        score = sum(x['return_pct'] - 0.5 * x['max_drawdown_pct'] for x in rows) / len(rows)
        rankings.append({'variant': config.name, 'qualifies': qualifies, 'score': score})
    rankings.sort(key=lambda x: (x['qualifies'], x['score']), reverse=True)
    selected = rankings[0]['variant']
    selection = {'selected': selected, 'qualifies_on_validation': rankings[0]['qualifies'],
                 'rankings': rankings, 'locked_before_holdout': True}
    save_json(output / 'selection.json', selection)
    print(f'Selection locked: {selected}; qualified={rankings[0]["qualifies"]}', flush=True)
    held_names = {selected, 'S7_reclaim_5m_3of5', 'control_momentum_5m_3of5'}
    for config in configs:
        if config.name in held_names:
            for symbol in args.symbols:
                run(config, symbol, 'holdout', args.test_start, args.end)
        if config.name == selected:
            for symbol in args.symbols:
                run(replace(config, slippage_bps=5), symbol, 'holdout_stress', args.test_start, args.end)
    save_json(output / 'summary.json', summaries)
    lines = ['# S7 — scalping research', '',
             f'Data: {args.data_start} → {args.end} (UTC, end exclusive).',
             f'Train: {args.train_start} → {args.validation_start}; validation → {args.test_start}; holdout → {args.end}.', '',
             f'Selected before holdout: **{selected}**. Validation criteria met: **{selection["qualifies_on_validation"]}**.', '',
             'Each pair starts with $10,000 per phase; risk 0.25% including estimated stop costs, notional ≤ equity.',
             'Fees 5 bps/side, adverse slippage 2 bps/side (stress: 5), actual funding with minute-price proxy.',
             'Frequency includes all calendar days, including days with no entries. No live approval inferred.', '',
             '| Phase | Variant | Pair | Trades | /day | Days ≥3 | Win % | PF | Net % | MTM DD % |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in summaries:
        pf = f"{row['profit_factor']:.2f}" if row['profit_factor'] is not None else 'n/a'
        lines.append(f"| {row['phase']} | {row['variant']} | {row['symbol']} | {row['trades']} | "
                     f"{row['trades_per_day']:.2f} | {row['days_at_least_3_pct']:.1f}% | "
                     f"{row['win_rate_pct']:.1f} | {pf} | {row['return_pct']:.2f} | {row['max_drawdown_pct']:.2f} |")
    lines += ['', '## Limits', '', *[f'- {x}' for x in protocol['limitations']], '',
              'Sources: [Binance public data](https://github.com/binance/binance-public-data), '
              '[archive](https://data.binance.vision/). Archive URLs and verified SHA256 in data_manifest.json.', '']
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
