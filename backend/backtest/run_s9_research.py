"""Develop and evaluate the causal S9 session-momentum scalp."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from l1_filter.session_momentum_scalp import (
    session_momentum_features,
    session_momentum_signals,
    session_momentum_variants,
)
from .run_scalp_revision import SYMBOLS, portfolio
from .run_scalp_research import save_json
from .scalp_data import load_archives
from .scalp_simulator import execute


MIN_VALIDATION_TRADES = 80


def _rank(rows, configs):
    rankings = []
    for config in configs:
        train = next(x for x in rows if x['variant'] == config.name and x['phase'] == 'train')
        validation = next(x for x in rows if x['variant'] == config.name and x['phase'] == 'validation')
        if validation['trades'] < MIN_VALIDATION_TRADES:
            continue
        rankings.append({
            'variant': config.name,
            'positive_both': train['return_pct'] > 0 and validation['return_pct'] > 0,
            'profitable_pairs_validation': validation['profitable_pairs'],
            'score': validation['return_pct'] - 0.5 * validation['eod_max_drawdown_pct'],
        })
    rankings.sort(key=lambda x: (x['positive_both'], x['profitable_pairs_validation'], x['score']),
                  reverse=True)
    return rankings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['develop', 'holdout'], required=True)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s9_session_momentum')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    configs = session_momentum_variants()
    if args.stage == 'develop':
        save_json(output / 'protocol.json', {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'variants_fixed_before_run': [asdict(x) for x in configs],
            'capital_per_pair': 1000,
            'risk_per_trade': '0.2% of current capital, stop-distance sized',
            'leverage': 20,
            'hypothesis': 'In a moderate 1h trend, a pullback into EMA20 or session VWAP followed by a closed micro-break has positive short-horizon expectancy. RSI5 recovery, EMA9/20 alignment, candle delta and relative volume are scored x-of-y; they do not replace mandatory regime/location/price trigger.',
            'development': ['2025-08-01/2026-02-01', '2026-02-01/2026-04-01'],
            'holdout': '2026-08-01/2026-09-01; untouched by S9 parameter selection',
            'selection': f'At least {MIN_VALIDATION_TRADES} validation trades. Prefer positive train and validation, then number of profitable validation pairs, then validation return minus half drawdown. Freeze exactly one global variant before holdout.',
            'costs_bps': {'taker_fee_each_side': 5, 'maker_entry': 2, 'slippage_each_taker_fill': 2},
            'risk_controls': 'London+NY hours only, daily loss stop 1%, ADX 18-45, 65% off at 0.6R then cost-aware breakeven/0.85ATR trail, max hold 75/120m.',
            'success_rule': 'Positive holdout portfolio, PF>1, at least 3/4 profitable pairs, max DD<5%, and at least 40 holdout trades. Passing is evidence for paper trading only, never a profit guarantee.',
        })
        phases = [('train', '2025-08-01', '2026-02-01'),
                  ('validation', '2026-02-01', '2026-04-01')]
        data_start, data_end = '2025-07-20', '2026-04-01'
    else:
        selected = json.loads((output / 'selection.json').read_text())['selected']
        configs = [x for x in configs if x.name == selected]
        phases = [('holdout_08', '2026-08-01', '2026-09-01')]
        data_start, data_end = '2026-07-20', '2026-09-01'

    datasets, features, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, manifest[symbol] = load_archives(symbol, data_start, data_end, args.cache)
        datasets[symbol] = minutes, funding
        for timeframe in {x.minutes for x in configs}:
            features[symbol, timeframe] = session_momentum_features(minutes, timeframe)
        print(symbol, 'features ready', flush=True)
    save_json(output / f'{args.stage}_manifest.json', manifest)

    rows, portfolios = [], []
    for config in configs:
        signals = {symbol: session_momentum_signals(features[symbol, config.minutes], config)
                   for symbol in SYMBOLS}
        for phase, start, end in phases:
            scenarios = [('20x', config.execution())]
            if args.stage == 'holdout':
                scenarios.append(('20x_stress', replace(config.execution(), slippage_bps=5)))
            for scenario, execution in scenarios:
                results = {}
                for symbol in SYMBOLS:
                    minutes, funding = datasets[symbol]
                    result = execute(minutes, funding, signals[symbol], features[symbol, config.minutes],
                                     execution, start, end, initial_capital=1000)
                    results[symbol] = result
                    rows.append({'variant': config.name, 'phase': phase, 'scenario': scenario,
                                 'symbol': symbol, **result['summary']})
                    payload = json.dumps(result, allow_nan=False).encode()
                    (output / f'{phase}_{scenario}_{symbol}_{config.name}.json.gz').write_bytes(
                        gzip.compress(payload, mtime=0))
                combined = {'variant': config.name, 'phase': phase, 'scenario': scenario,
                            **portfolio(results, initial_capital=1000)}
                combined['profitable_pairs'] = sum(x['summary']['return_pct'] > 0 for x in results.values())
                portfolios.append(combined)
                print(f"{phase} {config.name}: return={combined['return_pct']:.2f}% "
                      f"PF={combined['profit_factor']} n={combined['trades']} "
                      f"positive={combined['profitable_pairs']}/4", flush=True)

    save_json(output / f'{args.stage}_summary.json', rows)
    save_json(output / f'{args.stage}_portfolio.json', portfolios)
    if args.stage == 'develop':
        rankings = _rank(portfolios, configs)
        if not rankings:
            raise ValueError('No S9 variant reached the minimum validation trade count')
        viable = [x for x in rankings if x['positive_both'] and x['profitable_pairs_validation'] >= 3]
        save_json(output / 'selection.json', {
            'selected': viable[0]['variant'] if viable else None,
            'status': 'selected_for_holdout' if viable else 'rejected_in_development',
            'rankings': rankings,
            'locked_at': datetime.now(timezone.utc).isoformat(),
        })


if __name__ == '__main__':
    main()
