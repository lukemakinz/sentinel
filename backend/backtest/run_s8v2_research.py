"""S8v2: exit-geometry fix over S8 (see mean_reversion_scalp_v2 docstring).

Holdout is August 2026 — unused by S7 or S8 v1 in this standalone
Binance-archive engine (their holdout ended in July).
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from l1_filter.mean_reversion_scalp_v2 import (s8v2_features, s8v2_hold_variants,
                                               s8v2_signals, s8v2_variants)
from .run_scalp_revision import portfolio, SYMBOLS
from .run_scalp_research import save_json
from .scalp_data import load_archives
from .scalp_simulator import execute

MIN_VALIDATION_TRADES = 20


def _rank(rows, configs):
    rankings = []
    for config in configs:
        train = next(x for x in rows if x['variant'] == config.name and x['phase'] == 'train')
        val = next(x for x in rows if x['variant'] == config.name and x['phase'] == 'validation')
        if val['trades'] >= MIN_VALIDATION_TRADES:
            rankings.append({'variant': config.name, 'positive_both': train['return_pct'] > 0 and val['return_pct'] > 0,
                             'score': val['return_pct'] - .5 * val['eod_max_drawdown_pct']})
    rankings.sort(key=lambda x: (x['positive_both'], x['score']), reverse=True)
    return rankings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['develop', 'holdout'], required=True)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s8_mean_reversion_v2')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    if args.stage == 'develop':
        coarse = s8v2_variants()
        data_start, data_end = '2025-07-20', '2026-04-01'
        phases = [('train', '2025-08-01', '2026-02-01'), ('validation', '2026-02-01', '2026-04-01')]
        save_json(output / 'protocol.json', {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'coarse_variants_fixed_before_run': [asdict(x) for x in coarse],
            'capital_per_pair': 1000,
            'fix_over_v1': 'v1 lost because stop (0.6*ATR, at the level) was far tighter than '
                           'target (0.6-0.8x value-area width, to POC): range-edge noise hit the '
                           'stop long before price traveled that far. v2: (a) entry requires a '
                           'rejection candle at the level (wick through it, close back inside, '
                           'body in the reversal direction) before a retest limit is armed; '
                           '(b) stop sits behind the rejection wick + 0.12*ATR buffer; '
                           '(c) target is 1.0-1.5x ATR (same unit as the stop), not a large '
                           'fraction of value-area width.',
            'regime_filter': 'Unchanged from v1: htf_adx (1h ADX14) <= 20 AND 1h range contained '
                             'within the prior 24 1h bars.',
            'risk_per_trade': '0.3% of current capital, sized from stop distance; independent of '
                              'leverage (20x default; leverage only scales required margin).',
            'entry': 'Resting limit order at VAL/VAH (profile_edge) or a rolling VWAP +/-1 sigma '
                     'band (vwap_band), 6h window, armed only after a rejection candle. Maker fee '
                     '2bps, no entry slippage, 120min TTL.',
            'exit': 'Single fixed target = level + side * target_atr_mult * ATR, no trailing, no '
                   'partial. Stop = rejection wick -/+ 0.12*ATR buffer. Time-kill per max_hold_minutes.',
            'development': ['2025-08-01/2026-02-01', '2026-02-01/2026-04-01'],
            'holdout_window': '2026-08-01/2026-09-01 (unused by S7 or S8v1 in this engine)',
            'selection': f'Stage 1: rank the 6 coarse (timeframe x target_atr_mult) variants at '
                        f'max_hold_minutes=90, >= {MIN_VALIDATION_TRADES} validation trades on the '
                        'combined 4-pair portfolio. Stage 2: for the winning (timeframe, target_atr_mult), '
                        'also test max_hold_minutes=60 and re-rank all 7 variants together. Freeze one '
                        'global configuration before holdout.',
            'scenarios': '20x development; frozen holdout at 20x and 30x, with 2 and 5 bps slippage.',
            'fees_bps': {'taker': 5, 'maker_entry': 2},
            'limit_model': 'Fills only if the bar actually trades through the level (2bps '
                           'penetration), expires after 120 minutes. No queue model.',
            'liquidation': 'Conservative deposit-vs-stop buffer only; no historical mark-price liquidation simulation.',
            'stopping_rule': 'If no variant reaches profit_factor > 1 after costs on holdout for at '
                             'least 3 of 4 pairs, this is a SECOND consecutive negative result for the '
                             'S8 mean-reversion concept. Close it definitively; no third iteration '
                             'without asking the user first.'})
    else:
        selected = json.loads((output / 'selection.json').read_text())['selected']
        all_configs = s8v2_variants() + sum(
            (s8v2_hold_variants(m, tp) for m in (5, 15) for tp in (1.0, 1.25, 1.5)), [])
        configs = [x for x in all_configs if x.name == selected]
        data_start, data_end = '2026-07-01', '2026-09-01'
        phases = [('holdout_08', '2026-08-01', '2026-09-01')]

    datasets, features = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, _manifest = load_archives(symbol, data_start, data_end, args.cache)
        datasets[symbol] = minutes, funding
        print(symbol, 'archives ready', flush=True)

    def run_configs(configs, phases, extra_scenarios):
        rows, combined_rows = [], []
        for config in configs:
            key_minutes = config.minutes
            for symbol in SYMBOLS:
                if (symbol, key_minutes) not in features:
                    features[symbol, key_minutes] = s8v2_features(datasets[symbol][0], config)
            signals = {symbol: s8v2_signals(features[symbol, key_minutes], config) for symbol in SYMBOLS}
            for phase, start, end in phases:
                scenarios = [('20x', config.execution())] + extra_scenarios(config)
                for scenario, execution in scenarios:
                    results = {}
                    for symbol in SYMBOLS:
                        minutes, funding = datasets[symbol]
                        result = execute(minutes, funding, signals[symbol], features[symbol, key_minutes],
                                         execution, start, end, initial_capital=1000)
                        results[symbol] = result
                        rows.append({'variant': config.name, 'phase': phase, 'scenario': scenario,
                                    'symbol': symbol, **result['summary']})
                        (output / f'{phase}_{scenario}_{symbol}_{config.name}.json.gz').write_bytes(
                            gzip.compress(json.dumps(result, allow_nan=False).encode(), mtime=0))
                    p = {'variant': config.name, 'phase': phase, 'scenario': scenario,
                         **portfolio(results, initial_capital=1000)}
                    combined_rows.append(p)
                    print(f"{phase} {scenario} {config.name}: return={p['return_pct']:.2f}% "
                          f"PF={p['profit_factor']} n={p['trades']}", flush=True)
        return rows, combined_rows

    if args.stage == 'develop':
        rows, combined_rows = run_configs(coarse, phases, lambda cfg: [])
        stage1 = _rank(combined_rows, coarse)
        if not stage1:
            save_json(output / 'develop_summary.json', rows)
            save_json(output / 'develop_portfolio.json', combined_rows)
            raise ValueError('No S8v2 coarse candidate reached the minimum validation trade count')
        winner = next(c for c in coarse if c.name == stage1[0]['variant'])
        hold_variant = replace(winner, name=f'{winner.name}_hold60', max_hold_minutes=60)
        rows2, combined2 = run_configs([hold_variant], phases, lambda cfg: [])
        rows += rows2
        combined_rows += combined2
        save_json(output / 'develop_summary.json', rows)
        save_json(output / 'develop_portfolio.json', combined_rows)
        final = _rank(combined_rows, coarse + [hold_variant])
        if not final:
            raise ValueError('No S8v2 candidate reached the minimum validation trade count in stage 2')
        save_json(output / 'selection.json', {'selected': final[0]['variant'], 'stage1': stage1,
                                              'final_rankings': final,
                                              'locked_at': datetime.now(timezone.utc).isoformat()})
    else:
        def extra_scenarios(cfg):
            return [('30x', replace(cfg.execution(), leverage=30)),
                    ('20x_stress', replace(cfg.execution(), slippage_bps=5)),
                    ('30x_stress', replace(cfg.execution(), leverage=30, slippage_bps=5))]
        rows, combined_rows = run_configs(configs, phases, extra_scenarios)
        save_json(output / 'holdout_summary.json', rows)
        save_json(output / 'holdout_portfolio.json', combined_rows)


if __name__ == '__main__':
    main()
