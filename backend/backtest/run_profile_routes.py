"""User-specified $10 margin / $2.50 risk, HTF-directed volume-profile routes."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from l1_filter.profile_routes import route_features, route_signals, route_variants
from .run_scalp_revision import portfolio, SYMBOLS
from .run_scalp_research import save_json
from .scalp_data import load_archives
from .scalp_simulator import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['develop', 'holdout'], required=True)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s7_trend_only')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    configs = route_variants()
    if args.stage == 'develop':
        save_json(output / 'protocol.json', {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'variants_fixed_before_run': [asdict(x) for x in configs],
            'capital_per_pair': 1000, 'margin_cap_usd': 10, 'risk_cap_usd': 2.5,
            'development': ['2025-08-01/2026-02-01', '2026-02-01/2026-04-01'],
            'unused_evaluation': '2026-04-01/2026-08-01',
            'trend_only': 'No countertrend branch. bias4h == side is a hard requirement for every '
                          'entry, with no "strong reversal" exception. A prior revision (S7vp) had '
                          'such an exception and did not survive holdout; it is removed here, not tuned.',
            'selection': 'At least 40 validation trades across four pairs. Prefer positive portfolio '
                         'in both splits, then validation return minus half EOD DD. '
                         'Freeze one global configuration before unused evaluation.',
            'disclosure': 'December-March and August periods were used by earlier S7 revisions '
                          '(indicator-confluence and countertrend variants). April-July 2026 has not '
                          'been used to pick parameters for any S7 variant and is held aside as holdout. '
                          'This is a retrospective screen, not real-time forward trading.',
            'scenarios': '20x development; frozen holdout at 20x and 30x, with 2 and 5 bps slippage.',
            'fees_bps': {'taker': 5, 'maker_entry': 2},
            'limit_model': 'Must be non-marketable at placement, penetrate 2 bps, expire after 30 minutes. '
                           'No same-fill-minute profit target. No queue model.',
            'liquidation': 'Conservative deposit-vs-stop buffer only; no historical mark-price liquidation simulation.',
            'stopping_rule': 'If no variant reaches profit_factor > 1 after costs on holdout for at '
                             'least 3 of 4 pairs, this closes the indicator/price-action S7 scalping '
                             'research direction. No further variant search follows a negative holdout.'})
        data_start, data_end = '2025-07-20', '2026-04-01'
        phases = [('train', '2025-08-01', '2026-02-01'), ('validation', '2026-02-01', '2026-04-01')]
    else:
        selected = json.loads((output / 'selection.json').read_text())['selected']
        configs = [x for x in configs if x.name == selected]
        data_start, data_end = '2026-03-20', '2026-08-01'
        phases = [(f'holdout_{m:02}', f'2026-{m:02}-01', f'2026-{m+1:02}-01') for m in range(4, 8)]
    datasets, features, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, manifest[symbol] = load_archives(symbol, data_start, data_end, args.cache)
        datasets[symbol] = minutes, funding
        for minutes_per_bar, days in {(x.minutes, x.profile_days) for x in configs}:
            features[symbol, minutes_per_bar, days] = route_features(minutes, minutes_per_bar, days)
        print(symbol, 'features ready', flush=True)
    save_json(output / f'{args.stage}_manifest.json', manifest)
    rows, combined_rows = [], []
    for config in configs:
        signals = {symbol: route_signals(features[symbol, config.minutes, config.profile_days], config) for symbol in SYMBOLS}
        for phase, start, end in phases:
            scenarios = [('20x', config.execution())]
            if args.stage == 'holdout':
                scenarios.extend([('30x', replace(config.execution(), leverage=30)),
                                  ('20x_stress', replace(config.execution(), slippage_bps=5)),
                                  ('30x_stress', replace(config.execution(), leverage=30, slippage_bps=5))])
            for scenario, execution in scenarios:
                results = {}
                for symbol in SYMBOLS:
                    minutes, funding = datasets[symbol]
                    result = execute(minutes, funding, signals[symbol],
                                     features[symbol, config.minutes, config.profile_days], execution,
                                     start, end, initial_capital=1000)
                    results[symbol] = result
                    rows.append({'variant': config.name, 'phase': phase, 'scenario': scenario,
                                 'symbol': symbol, **result['summary']})
                    (output / f'{phase}_{scenario}_{symbol}_{config.name}.json.gz').write_bytes(
                        gzip.compress(json.dumps(result, allow_nan=False).encode(), mtime=0))
                p = {'variant': config.name, 'phase': phase, 'scenario': scenario,
                     **portfolio(results, initial_capital=1000)}
                combined_rows.append(p)
                print(f"{phase} {scenario} {config.name}: return={p['return_pct']:.2f}% "
                      f"PF={p['profit_factor']} n={p['trades']} win-days={p['profitable_days_pct']:.1f}%", flush=True)
    save_json(output / f'{args.stage}_summary.json', rows)
    save_json(output / f'{args.stage}_portfolio.json', combined_rows)
    if args.stage == 'develop':
        rankings = []
        for config in configs:
            train, val = [next(x for x in combined_rows if x['variant'] == config.name and x['phase'] == phase)
                          for phase in ('train', 'validation')]
            if val['trades'] >= 40:
                rankings.append({'variant': config.name, 'positive_both': train['return_pct'] > 0 and val['return_pct'] > 0,
                                 'score': val['return_pct'] - .5 * val['eod_max_drawdown_pct']})
        rankings.sort(key=lambda x: (x['positive_both'], x['score']), reverse=True)
        if not rankings:
            raise ValueError('No profile route candidate reached 40 validation trades')
        save_json(output / 'selection.json', {'selected': rankings[0]['variant'], 'rankings': rankings,
                                             'locked_at': datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    main()
