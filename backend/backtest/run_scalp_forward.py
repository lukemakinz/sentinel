"""Forward check of predeclared active variants, with no parameter selection."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from l1_filter.scalp_strategy import build_features, generate_signals
from .run_scalp_research import save_json, variants
from .scalp_data import load_archives
from .scalp_simulator import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s7_forward')
    parser.add_argument('--data-start', default='2026-07-30')
    parser.add_argument('--start', default='2026-08-01')
    parser.add_argument('--end', default='2026-09-01')
    args = parser.parse_args()
    if not args.data_start < args.start < args.end:
        parser.error('Dates must increase')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    configs = [c for c in variants() if c.name in {
        'S7_hybrid_5m_3of5', 'S7_hybrid_15m_3of5', 'control_momentum_5m_3of5'}]
    save_json(output / 'protocol.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'arguments': vars(args),
        'variants_fixed_before_loading_data': [asdict(c) for c in configs],
        'purpose': 'Independent later period. Check frequency and costs for active S7 variants, '
                   'not the almost-inactive diagnostic winner. No tuning or selection on this period.',
        'stress': 'Repeat both S7 variants with slippage 5 bps/side instead of 2.'})
    summaries, manifest = [], {}
    for symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']:
        minutes, funding, manifest[symbol] = load_archives(symbol, args.data_start, args.end, args.cache)
        feature_cache = {}
        for config in configs:
            if config.minutes not in feature_cache:
                feature_cache[config.minutes] = build_features(minutes, config.minutes, config.profile)
            features = feature_cache[config.minutes]
            signals = generate_signals(features, config)
            scenarios = [('forward', config)]
            if config.mode != 'momentum':
                scenarios.append(('forward_stress', replace(config, slippage_bps=5)))
            for phase, scenario in scenarios:
                result = execute(minutes, funding, signals, features, scenario, args.start, args.end)
                row = {'variant': config.name, 'symbol': symbol, 'phase': phase, **result['summary']}
                summaries.append(row)
                save_json(output / f'{phase}_{symbol}_{config.name}.json', result)
                print(f"{phase} {symbol} {config.name}: {row['trades_per_day']:.2f}/day "
                      f"net={row['return_pct']:.2f}% PF={row['profit_factor']}", flush=True)
    save_json(output / 'summary.json', summaries)
    save_json(output / 'data_manifest.json', manifest)
    lines = ['# S7 — independent later-period check', '',
             f'{args.start} → {args.end}, UTC, end exclusive. Same execution/cost rules as the original experiment.', '',
             '| Variant | Scenario | Pair | Trades | /day | Days ≥3 | PF | Net % | MTM DD % |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] is not None else 'n/a'
        lines.append(f"| {r['variant']} | {r['phase']} | {r['symbol']} | {r['trades']} | "
                     f"{r['trades_per_day']:.2f} | {r['days_at_least_3_pct']:.1f}% | {pf} | "
                     f"{r['return_pct']:.2f} | {r['max_drawdown_pct']:.2f} |")
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
