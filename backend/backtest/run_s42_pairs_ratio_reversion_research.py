"""Offline, gate-by-gate retrospective for S42: relative-value mean
reversion on 7 ALT/BTC ratios, reusing S40/S41's entry/exit formulas
unmodified on a synthetic ratio instrument (see ratio_data.build_ratio_
minutes and the protocol's synthetic_instrument_disclosure). Costs are
doubled relative to S40/S41 to approximate two-leg execution. Reuses
already-cached BTCUSDT + alt USDT-perp archives -- no new data source.
"""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.htf_extreme_reversion_scalp import (
    HTFExtremeReversionConfig,
    generate_htf_extreme_signals,
    htf_extreme_features,
)
from .cluster_scalp_simulator import execute_cluster
from .ratio_data import build_ratio_minutes
from .scalp_data import load_archives


LEGS = ('ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'SUIUSDT', 'DOGEUSDT')
TRADED = ('ETHBTC', 'BNBBTC', 'SOLBTC', 'XRPBTC', 'ADABTC', 'SUIBTC', 'DOGEBTC')
LEG_OF = dict(zip(TRADED, LEGS))
WARMUP, END = '2023-12-01', '2026-09-01'
WINDOWS = {
    'development': ('2024-01-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def central_variants() -> list[HTFExtremeReversionConfig]:
    return [
        HTFExtremeReversionConfig('S42_pairs_reversion_rsi', 'rsi_extreme'),
        HTFExtremeReversionConfig('S42_pairs_reversion_bb', 'bb_extreme'),
    ]


def _numeric_pf(summary: dict) -> float:
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _development_pass(summary: dict) -> bool:
    return (summary['trades'] >= 40 and summary['net_pnl'] > 0
            and _numeric_pf(summary) > 1.05)


def _validation_pass(base: dict, stress: dict) -> bool:
    contribution = base['largest_symbol_gross_profit_share_pct']
    return (
        base['trades'] >= 20
        and _numeric_pf(base) > 1.10
        and _numeric_pf(stress) >= 1.00
        and base['positive_symbols'] >= 2
        and contribution is not None and contribution <= 60
    )


def _scenario_execution(config, scenario):
    execution = config.execution()
    # Cost tiers are doubled relative to S40/S41's single-leg defaults --
    # see the protocol's cost_doubling_disclosure.
    tiers = {
        'base': dict(maker_fee_bps=4.0, fee_bps=10.0, slippage_bps=4.0, limit_penetration_bps=4.0),
        'stress': dict(maker_fee_bps=10.0, fee_bps=16.0, slippage_bps=10.0, limit_penetration_bps=10.0),
        'severe': dict(maker_fee_bps=20.0, fee_bps=20.0, slippage_bps=20.0, limit_penetration_bps=20.0),
    }
    return replace(execution, **tiers[scenario])


def _run_window(data, signals, config, scenario, start, end):
    execution = _scenario_execution(config, scenario)
    result = execute_cluster(
        {symbol: data[symbol] for symbol in TRADED}, signals, execution,
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary'], result['trades']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s42_pairs_ratio_reversion')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before any data are loaded')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')
    output.mkdir(parents=True, exist_ok=True)

    btc_minutes, _, btc_manifest = load_archives('BTCUSDT', WARMUP, END, str(cache))
    data, manifest = {}, {'klines_funding': {'BTCUSDT': btc_manifest}}
    for leg in LEGS:
        leg_minutes, _, leg_manifest = load_archives(leg, WARMUP, END, str(cache))
        manifest['klines_funding'][leg] = leg_manifest
        print(leg, 'archives ready', flush=True)
    for symbol, leg in LEG_OF.items():
        leg_minutes, _, _ = load_archives(leg, WARMUP, END, str(cache))
        ratio_minutes = build_ratio_minutes(leg_minutes, btc_minutes)
        zero_funding = pd.Series(dtype=float)
        data[symbol] = ratio_minutes, zero_funding
        print(symbol, 'ratio built', len(ratio_minutes), flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    window_bounds = {
        name: (pd.Timestamp(bounds[0], tz='UTC'), pd.Timestamp(bounds[1], tz='UTC'))
        for name, bounds in WINDOWS.items()
    }
    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}

    all_results = {}
    for config in central_variants():
        features = {symbol: htf_extreme_features(data[symbol][0], config) for symbol in TRADED}
        raw = {
            symbol: generate_htf_extreme_signals(features[symbol], config, symbol)
            for symbol in TRADED
        }
        route_result = {
            'config': asdict(config),
            'raw_candidates_by_window': {
                window: sum(
                    start <= signal['timestamp'] < end
                    for signals in raw.values() for signal in signals
                )
                for window, (start, end) in window_bounds.items()
            },
            'windows': {},
        }
        for window in ('development',):
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary, trades = _run_window(markets, raw, config, scenario, *WINDOWS[window])
                route_result['windows'][window][scenario] = summary
                payload = json.dumps(trades, allow_nan=False).encode()
                (output / f'{config.name}_{window}_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(payload, mtime=0))
                print(config.name, window, scenario, summary['trades'],
                      summary['profit_factor'], f'${summary["net_pnl"]:.2f}', flush=True)

        dev = route_result['windows']['development']['base']
        if not _development_pass(dev):
            route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
            all_results[config.name] = route_result
            continue

        route_result['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(markets, raw, config, scenario, *WINDOWS['validation'])
            route_result['windows']['validation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.name}_validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        validation = route_result['windows']['validation']
        if not _validation_pass(validation['base'], validation['stress']):
            route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
            all_results[config.name] = route_result
            continue

        route_result['windows']['retrospective_evaluation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(
                markets, raw, config, scenario, *WINDOWS['retrospective_evaluation'])
            route_result['windows']['retrospective_evaluation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.name}_evaluation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        all_results[config.name] = route_result

    result = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective diagnostic; synthetic single-instrument two-leg proxy; not a live paper-forward result',
        'results': all_results,
    }
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
