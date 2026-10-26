"""S7 revision experiment. Bounded hypotheses, frozen selection, unused periods."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.scalp_strategy_v2 import revision_features, revision_signals, revision_variants
from .scalp_data import load_archives
from .scalp_simulator import execute
from .run_scalp_research import save_json

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']


def portfolio(results, initial_capital=10000):
    """Four equal, separately funded sleeves; no cross-pair rebalancing."""
    equity = pd.DataFrame({s: r['daily_equity'] for s, r in results.items()}).sum(axis=1)
    initial = initial_capital * len(results)
    returns = equity.pct_change()
    returns.iloc[0] = equity.iloc[0] / initial - 1
    values = np.r_[initial, equity.to_numpy()]
    pnls = [t['pnl'] for r in results.values() for t in r['trades']]
    wins, losses = sum(max(p, 0) for p in pnls), -sum(min(p, 0) for p in pnls)
    # Moving-block bootstrap of synchronized portfolio days, conditional on
    # this fixed strategy. Does not correct development multiple testing.
    rng = np.random.default_rng(73)
    daily = returns.to_numpy()
    block = min(7, len(daily))
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, len(daily) - block + 1, size=int(np.ceil(len(daily) / block)))
        sample = np.concatenate([daily[k:k+block] for k in starts])[:len(daily)]
        samples.append(sample.mean() * 100)
    return {'return_pct': float((equity.iloc[-1] / initial - 1) * 100),
            'mean_daily_return_pct': float(returns.mean() * 100),
            'daily_mean_95pct_block_bootstrap': np.quantile(samples, [.025, .975]).tolist(),
            'profitable_days_pct': float((returns > 0).mean() * 100),
            'losing_days_pct': float((returns < 0).mean() * 100),
            'worst_day_pct': float(returns.min() * 100),
            'eod_max_drawdown_pct': float(((1 - values / np.maximum.accumulate(values)) * 100).max()),
            'trades': len(pnls), 'trades_per_day_all_pairs': len(pnls) / len(equity),
            'profit_factor': wins / losses if losses else None,
            'daily_equity': equity.to_dict()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['develop', 'holdout'], required=True)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s7_revision')
    parser.add_argument('--warmup-start', default='2025-12-01')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    variants = revision_variants()
    if args.stage == 'develop':
        save_json(output / 'protocol.json', {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'variants': [asdict(c) for c in variants],
            'development': ['2025-12-03/2026-02-01', '2026-02-01/2026-04-01'],
            'unused_evaluation': '2026-04-01/2026-08-01',
            'disclosure': 'December-March and August were examined in v1. March is now development, '
                          'not an untouched holdout. April-July have not been examined; '
                          'this is a retrospective unused-period evaluation, not actual forward trading.',
            'selection': 'At least 100 validation trades combined. Rank by positive return in BOTH '
                         'development splits first, then validation portfolio return minus half EOD DD. '
                         'One global rule for all symbols. No required minimum daily trade count.',
            'costs': '5 bps fee, 2 bps adverse slippage each side, historical funding; no optimistic maker fills.',
            'holdout_plan': 'Evaluate the locked candidate on four unused months, and 5 bps slippage stress.'})
        phases = [('train', '2025-12-03', '2026-02-01'),
                  ('validation', '2026-02-01', '2026-04-01')]
        data_start, data_end = args.warmup_start, '2026-04-01'
    else:
        selection = json.loads((output / 'selection.json').read_text())
        variants = [x for x in variants if x.name == selection['selected']]
        if not variants:
            raise ValueError('No matching frozen candidate')
        phases = [(f'holdout_{month:02}', f'2026-{month:02}-01', f'2026-{month+1:02}-01') for month in range(4, 8)]
        data_start, data_end = '2026-03-20', '2026-08-01'

    rows, portfolio_results = [], []
    datasets, features = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, manifest = load_archives(symbol, data_start, data_end, args.cache)
        datasets[symbol] = minutes, funding
        save_json(output / f'{args.stage}_{symbol}_manifest.json', manifest)
        for interval in {v.minutes for v in variants}:
            features[symbol, interval] = revision_features(minutes, interval)
        print(f'{symbol}: data and causal features ready', flush=True)
    for config in variants:
        signal_cache = {symbol: revision_signals(features[symbol, config.minutes], config) for symbol in SYMBOLS}
        for phase, start, end in phases:
            scenarios = [('base', config.execution())]
            if args.stage == 'holdout':
                scenarios.append(('stress', replace(config.execution(), slippage_bps=5)))
                if config.execution().leverage == 20:
                    scenarios.append(('30x', replace(config.execution(), leverage=30)))
            for scenario_name, execution in scenarios:
                results = {}
                for symbol in SYMBOLS:
                    minutes, funding = datasets[symbol]
                    result = execute(minutes, funding, signal_cache[symbol], features[symbol, config.minutes],
                                     execution, start, end)
                    results[symbol] = result
                    row = {'variant': config.name, 'phase': phase, 'scenario': scenario_name,
                           'symbol': symbol, **result['summary']}
                    rows.append(row)
                    path = output / f'{phase}_{scenario_name}_{symbol}_{config.name}.json.gz'
                    path.write_bytes(gzip.compress(json.dumps(result, allow_nan=False).encode(), mtime=0))
                combined = {'variant': config.name, 'phase': phase, 'scenario': scenario_name, **portfolio(results)}
                portfolio_results.append(combined)
                print(f"{phase}/{scenario_name} {config.name}: portfolio={combined['return_pct']:.2f}% "
                      f"PF={combined['profit_factor']} n={combined['trades']} "
                      f"winning-days={combined['profitable_days_pct']:.1f}%", flush=True)
    save_json(output / f'{args.stage}_summary.json', rows)
    save_json(output / f'{args.stage}_portfolio.json', portfolio_results)
    if args.stage == 'develop':
        rankings = []
        for config in variants:
            train = next(x for x in portfolio_results if x['variant'] == config.name and x['phase'] == 'train')
            val = next(x for x in portfolio_results if x['variant'] == config.name and x['phase'] == 'validation')
            if val['trades'] < 100:
                continue
            rankings.append({'variant': config.name,
                             'positive_both': train['return_pct'] > 0 and val['return_pct'] > 0,
                             'score': val['return_pct'] - .5 * val['eod_max_drawdown_pct']})
        rankings.sort(key=lambda x: (x['positive_both'], x['score']), reverse=True)
        if not rankings:
            raise ValueError('No candidate has enough validation trades')
        save_json(output / 'selection.json', {'selected': rankings[0]['variant'],
                                             'rankings': rankings, 'locked_at': datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    main()
