"""S31: one frozen safety mutation of monthly filtered funding carry."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .funding_carry_data import (
    load_hour_fallback,
    load_fcm_archives,
    missing_hour_archive_specs,
    prepare_archives,
    required_archive_specs,
)
from .funding_carry_v2 import FCMConfig, FCMCosts, simulate_fcm
from .run_fcm_1m_research import (
    END,
    MARKET_START,
    SPOT_WARMUP,
    SYMBOLS,
    WINDOWS,
    _assert_complete_hourly,
    _causal_mtm_fill,
    _gap_stats,
)


INITIAL_CAPITAL = 250.0


def _load_data(cache: Path, output: Path, download: bool, workers: int):
    specs = required_archive_specs(SYMBOLS, SPOT_WARMUP, MARKET_START, END)
    archive_index = prepare_archives(
        specs, cache, download_missing=download, workers=workers)
    print(f'verified {len(archive_index)} primary archives', flush=True)
    data, manifest = {}, {}
    for symbol in SYMBOLS:
        data[symbol], manifest[symbol] = load_fcm_archives(
            symbol, SPOT_WARMUP, MARKET_START, END, cache)

    quality = {
        symbol: {
            'spot_raw_1h': _gap_stats(data[symbol]['spot'], SPOT_WARMUP, END),
            'perpetual_raw_1h': _gap_stats(
                data[symbol]['perpetual'], MARKET_START, END),
            'mark_raw_1h': _gap_stats(data[symbol]['mark'], MARKET_START, END),
        }
        for symbol in SYMBOLS
    }
    fallback_specs = {
        symbol: {
            stream: missing_hour_archive_specs(
                symbol, data[symbol][stream], MARKET_START, END, stream)
            for stream in ('spot', 'perpetual', 'mark')
        }
        for symbol in SYMBOLS
    }
    prepare_archives(
        [spec for streams in fallback_specs.values()
         for specs_by_stream in streams.values() for spec in specs_by_stream],
        cache, download_missing=download, workers=workers,
    )
    for symbol, streams in fallback_specs.items():
        for stream in ('spot', 'perpetual', 'mark'):
            expected = pd.date_range(
                MARKET_START, END, freq='1h', inclusive='left', tz='UTC')
            missing = expected.difference(data[symbol][stream].index)
            fallback, fallback_manifest = load_hour_fallback(
                streams[stream], cache, missing, require_all=False)
            data[symbol][stream] = pd.concat(
                [data[symbol][stream], fallback]).sort_index()
            manifest[symbol].extend(fallback_manifest)
            quality[symbol][f'{stream}_exact_1m_fallback_hours'] = len(fallback)

        expected = pd.date_range(
            MARKET_START, END, freq='1h', inclusive='left', tz='UTC')
        mark_missing = expected.difference(data[symbol]['mark'].index)
        from_perpetual = mark_missing.intersection(data[symbol]['perpetual'].index)
        if len(from_perpetual):
            data[symbol]['mark'] = pd.concat([
                data[symbol]['mark'],
                data[symbol]['perpetual'].loc[from_perpetual],
            ]).sort_index()
        remaining = expected.difference(data[symbol]['mark'].index)
        from_spot = remaining.intersection(data[symbol]['spot'].index)
        if len(from_spot):
            data[symbol]['mark'] = pd.concat([
                data[symbol]['mark'], data[symbol]['spot'].loc[from_spot],
            ]).sort_index()
        remaining = expected.difference(data[symbol]['mark'].index)
        quality[symbol]['mark_perpetual_proxy_hours'] = len(from_perpetual)
        quality[symbol]['mark_spot_proxy_hours'] = len(from_spot)
        quality[symbol]['mark_prior_close_proxy_hours'] = len(remaining)

        for stream in ('spot', 'perpetual', 'mark'):
            before = expected.difference(data[symbol][stream].index)
            quality[symbol][f'{stream}_prior_close_mtm_hours'] = len(before)
            data[symbol][stream] = _causal_mtm_fill(
                data[symbol][stream], MARKET_START, END)
            _assert_complete_hourly(
                data[symbol][stream], MARKET_START, END,
                f'{symbol} {stream}')
        print(symbol, 'data and causal gap policy ready', flush=True)

    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(
        json.dumps(quality, indent=2) + '\n')
    return data, quality


def _gate(results: dict) -> str:
    stress = results['stress']
    if any(stress[window]['summary']['net_pnl'] <= 0 for window in WINDOWS):
        return 'REJECTED_BY_STRESS_WINDOW_GATE'
    combined = stress['all_available']['summary']
    if combined['modelled_liquidation_breaches']:
        return 'REJECTED_BY_COLLATERAL_EXHAUSTION'
    if combined['min_futures_equity_usd'] < 95.0:
        return 'REJECTED_BY_COLLATERAL_BUFFER_GATE'
    if combined['max_mark_leverage'] > 1.0:
        return 'REJECTED_BY_MARK_LEVERAGE_GATE'
    return 'HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY'


def _projection(results: dict) -> dict:
    bounds = WINDOWS['retrospective_evaluation']
    days = (pd.Timestamp(bounds[1]) - pd.Timestamp(bounds[0])).days
    result = {}
    for scenario in ('base', 'stress'):
        net = results[scenario]['retrospective_evaluation']['summary']['net_pnl']
        daily = net / days
        result[scenario] = {
            'window_days': days,
            'realised_average_pnl_per_day_usd_on_250': daily,
            'linear_capital_for_25_usd_per_day': (
                INITIAL_CAPITAL * 25.0 / daily if daily > 0 else None),
            'warning': 'mechanical linear extrapolation; ignores capacity and is not a forecast',
        }
    return result


def _report(results: dict, protocol_hash: str, decision: str,
            projection: dict) -> str:
    lines = [
        '# S31 — safer monthly-reset funding carry', '',
        f'Frozen protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | Episodes | Funding | Basis PnL | Net | Return | Min futures equity | Max mark leverage | Breaches |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress'):
            summary = results[scenario][window]['summary']
            lines.append(
                f'| {window} | {scenario} | {summary["episodes"]} | '
                f'${summary["gross_funding_pnl"]:.2f} | '
                f'${summary["price_basis_pnl_before_costs"]:.2f} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'${summary["min_futures_equity_usd"]:.2f} | '
                f'{summary["max_mark_leverage"]:.3f}x | '
                f'{summary["modelled_liquidation_breaches"]} |'
            )
    lines.extend(['', f'Decision: **{decision}**.', '', '## $25/day reality check', ''])
    for scenario in ('base', 'stress'):
        row = projection[scenario]
        capital = row['linear_capital_for_25_usd_per_day']
        capital_text = 'not applicable (non-positive)' if capital is None else f'${capital:,.0f}'
        lines.append(
            f'- {scenario}: the newest retrospective window averaged '
            f'${row["realised_average_pnl_per_day_usd_on_250"]:.4f}/day on $250; '
            f'a purely linear $25/day extrapolation is {capital_text} capital.'
        )
    lines.extend([
        '',
        'The extrapolation is not a forecast. All periods were already viewed, '
        'maintenance tiers are not modelled, and live execution remains disabled. '
        'A historical pass permits only a frozen prospective paper test.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--output', default='docs/research/s31_fcm_monthly_reset')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol = output / 'protocol.json'
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != recorded_hash:
        raise ValueError('Frozen S31 protocol hash mismatch')

    data, _quality = _load_data(
        cache, output, args.download, args.workers)
    base = FCMConfig(
        name='S31_fcm_safe_monthly_reset',
        spot_notional_usd=50.0,
        futures_margin_usd=190.0,
        reserve_usd=10.0,
        max_initial_futures_leverage=.30,
        force_monthly_reset=True,
    )
    stress = replace(base, costs=FCMCosts(
        spot_fee_bps=10.0, futures_fee_bps=5.0,
        spot_slippage_bps=5.0, futures_slippage_bps=5.0,
    ))
    if stress.costs.round_trip_bps != base.qualification_funding_bps:
        raise AssertionError('Funding floor must equal stress round-trip cost')

    scenarios = {'base': base, 'stress': stress}
    results = {}
    for scenario, config in scenarios.items():
        results[scenario] = {}
        for window, bounds in WINDOWS.items():
            replay = simulate_fcm(
                {symbol: data[symbol]['spot'] for symbol in SYMBOLS},
                {symbol: data[symbol]['perpetual'] for symbol in SYMBOLS},
                {symbol: data[symbol]['mark'] for symbol in SYMBOLS},
                {symbol: data[symbol]['funding'] for symbol in SYMBOLS},
                *bounds, config, initial_capital=INITIAL_CAPITAL,
            )
            results[scenario][window] = replay
            summary = replay['summary']
            print(scenario, window, 'episodes', summary['episodes'],
                  'net', f'${summary["net_pnl"]:.2f}',
                  'min-futures-equity',
                  f'${summary["min_futures_equity_usd"]:.2f}', flush=True)

    decision = _gate(results)
    projection = _projection(results)
    payload = {
        'protocol_sha256': actual_hash,
        'decision': decision,
        'configs': {name: asdict(config) for name, config in scenarios.items()},
        'capital_projection': projection,
        'disclosure': 'single retrospective risk mutation; no untouched holdout',
        'results': results,
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, actual_hash, decision, projection))


if __name__ == '__main__':
    main()
