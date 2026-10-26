"""Protocol-frozen FCM-1M replay on verified public hourly Binance archives."""
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


SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
SPOT_WARMUP = '2020-08-01'
MARKET_START = '2020-12-01'
END = '2026-09-01'
WINDOWS = {
    'development': ('2021-01-01', '2023-01-01'),
    'validation': ('2023-01-01', '2024-07-01'),
    'retrospective_evaluation': ('2024-07-01', END),
    'all_available': ('2021-01-01', END),
}


def _historical_gate(results: dict) -> str:
    stress = results['stress']
    if any(stress[window]['summary']['net_pnl'] <= 0
           for window in ('development', 'validation', 'retrospective_evaluation')):
        return 'REJECTED_BY_FROZEN_STRESS_WINDOW_GATE'
    combined = stress['all_available']['summary']
    if combined['modelled_liquidation_breaches'] or combined['net_pnl'] <= 0:
        return 'REJECTED_BY_STRESS_SAFETY_GATE'
    return 'HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY'


def _gap_stats(frame, start, end) -> dict:
    expected = pd.date_range(start, end, freq='1h', inclusive='left', tz='UTC')
    missing = expected.difference(frame.index)
    longest = 0
    if len(missing):
        run = 1
        longest = 1
        for previous, current in zip(missing[:-1], missing[1:]):
            run = run + 1 if current - previous == pd.Timedelta(hours=1) else 1
            longest = max(longest, run)
    return {
        'expected_hours': len(expected),
        'observed_hours': int(frame.index.intersection(expected).size),
        'missing_hours': len(missing),
        'longest_gap_hours': longest,
        'first_missing_hours': [str(time) for time in missing[:20]],
    }


def _assert_complete_hourly(frame, start, end, label) -> None:
    stats = _gap_stats(frame, start, end)
    if stats['missing_hours'] or frame.index.has_duplicates:
        raise ValueError(f'{label} remains incomplete after exact fallbacks: {stats}')


def _causal_mtm_fill(frame, start, end) -> pd.DataFrame:
    """Carry the last traded close only across non-execution MTM gaps."""
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    prefix = frame.loc[frame.index < start]
    segment = frame.loc[(frame.index >= start) & (frame.index < end)]
    segment = segment.copy()
    segment['observed'] = True
    grid = pd.date_range(start, end, freq='1h', inclusive='left')
    result = segment.reindex(grid)
    missing = result.open.isna()
    result['observed'] = result.observed.fillna(False).astype(bool)
    prior_close = result.close.ffill()
    if prior_close.isna().any():
        raise ValueError('Cannot causally value a leading hourly gap')
    for column in ('open', 'high', 'low', 'close'):
        result.loc[missing, column] = prior_close.loc[missing]
    return pd.concat([prefix, result]).sort_index()


def _report(results: dict, protocol_hash: str, decision: str, quality: dict) -> str:
    lines = [
        '# FCM-1M — monthly filtered funding carry',
        '',
        f'Hash protokołu zamrożonego przed pobraniem cen: `{protocol_hash}`.',
        '',
        'Ten replay usuwa najważniejsze uproszczenie S11: spot, perpetual execution '
        'i perpetual mark są trzema osobnymi seriami. Wynik zawiera więc rzeczywisty '
        'historyczny basis PnL, a nie sztuczne anulowanie całego price PnL.',
        '',
        '| Okno | Koszty | Decyzje z pozycją | Epizody | Funding | Basis price PnL | Fees | Slippage | Net | Zwrot | Max DD MTM |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress'):
            summary = results[scenario][window]['summary']
            lines.append(
                f'| {window} | {scenario} | {summary["qualified_decisions"]}/'
                f'{summary["decisions"]} | {summary["episodes"]} | '
                f'${summary["gross_funding_pnl"]:.2f} | '
                f'${summary["price_basis_pnl_before_costs"]:.2f} | '
                f'${summary["fees"]:.2f} | ${summary["slippage_cost"]:.2f} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_mtm_drawdown_pct"]:.3f}% |'
            )
    combined = results['stress']['all_available']['summary']
    lines.extend([
        '',
        f'Decyzja: **{decision}**.',
        '',
        '## Co dokładnie rozliczono',
        '',
        '- Każde wejście kupuje spot za $100 i sprzedaje shortem identyczną liczbę '
        'jednostek bazowych; nie wymusza fałszywie równej wartości obu nóg przy niezerowym basis.',
        '- Ledger obejmuje zakup/sprzedaż spot, blokadę/zwolnienie $100 futures margin, '
        'variation PnL shorta, każdy funding według mark price i cztery osobne opłaty.',
        '- Stress to pełne 50 bps round trip: 10/5 bps fee i 5/5 bps slippage '
        'dla spot/perpetual na każdą stronę.',
        '- Braki godzinowe surowych archiwów są jawne w `data_quality.json`. Mark 1h '
        'został uzupełniony wyłącznie exact-timestamp open z publicznego mark 1m; '
        'brak także tam powoduje fail-closed. Spot/perp nie są interpolowane do filli.',
        f'- Najniższa diagnostyczna wartość collateral shorta: '
        f'${combined["min_futures_equity_usd"]:.2f}; maksymalna dźwignia mark: '
        f'{combined["max_mark_leverage"]:.2f}x. To nie zastępuje dokładnego modelu '
        'maintenance margin/liquidation tiers.',
        '',
        '## Granica wniosku',
        '',
        'To protokół-frozen badanie retrospektywne, nie dowód przyszłego zysku. Nawet '
        'dodatni wynik wszystkich bramek dopuszcza wyłącznie paper-forward; wymagane jest '
        'co najmniej 12 miesięcy i 12 niezależnych zamkniętych epizodów prospektywnych.',
        '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--output', default='docs/research/fcm_1m')
    parser.add_argument('--download', action='store_true',
                        help='Download only missing public archives; default is offline')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before any data load')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    specs = required_archive_specs(
        SYMBOLS, SPOT_WARMUP, MARKET_START, END)
    archive_index = prepare_archives(
        specs, cache, download_missing=args.download, workers=args.workers)
    print(
        f'verified {len(archive_index)} archives, '
        f'{sum(row["bytes"] for row in archive_index) / 1_000_000:.1f} MB zipped',
        flush=True,
    )
    data, manifest = {}, {}
    for symbol in SYMBOLS:
        data[symbol], manifest[symbol] = load_fcm_archives(
            symbol, SPOT_WARMUP, MARKET_START, END, cache)
        print(symbol, 'spot/perpetual/mark/funding loaded', flush=True)
    quality = {
        symbol: {
            'spot_raw_1h': _gap_stats(data[symbol]['spot'], SPOT_WARMUP, END),
            'perpetual_raw_1h': _gap_stats(
                data[symbol]['perpetual'], MARKET_START, END),
            'mark_raw_1h': _gap_stats(data[symbol]['mark'], MARKET_START, END),
            'funding_settlements_without_raw_1h_mark': int(len(
                data[symbol]['funding'].index.difference(data[symbol]['mark'].index))),
        }
        for symbol in SYMBOLS
    }
    fallback_specs = {
        symbol: {
            'spot': missing_hour_archive_specs(
                symbol, data[symbol]['spot'], MARKET_START, END, 'spot'),
            'perpetual': missing_hour_archive_specs(
                symbol, data[symbol]['perpetual'], MARKET_START, END, 'perpetual'),
            'mark': missing_hour_archive_specs(
                symbol, data[symbol]['mark'], MARKET_START, END, 'mark'),
        }
        for symbol in SYMBOLS
    }
    prepare_archives(
        [spec for by_stream in fallback_specs.values()
         for specs in by_stream.values() for spec in specs],
        cache, download_missing=args.download, workers=args.workers,
    )
    for symbol, by_stream in fallback_specs.items():
        bounds = {
            'spot': (MARKET_START, END),
            'perpetual': (MARKET_START, END),
            'mark': (MARKET_START, END),
        }
        for stream in ('spot', 'perpetual', 'mark'):
            expected = pd.date_range(
                *bounds[stream], freq='1h', inclusive='left', tz='UTC')
            missing = expected.difference(data[symbol][stream].index)
            fallback, fallback_manifest = load_hour_fallback(
                by_stream[stream], cache, missing, require_all=False)
            data[symbol][stream] = pd.concat(
                [data[symbol][stream], fallback]).sort_index()
            manifest[symbol].extend(fallback_manifest)
            quality[symbol][f'{stream}_exact_1m_fallback_hours'] = len(fallback)

        actions = pd.date_range(
            WINDOWS['all_available'][0], END, freq='MS', inclusive='left', tz='UTC')
        actions += pd.Timedelta(hours=FCMConfig().decision_delay_hours)
        missing_action_spot = actions.difference(data[symbol]['spot'].index)
        missing_action_perpetual = actions.difference(data[symbol]['perpetual'].index)
        quality[symbol]['missing_monthly_action_spot_bars'] = len(missing_action_spot)
        quality[symbol]['missing_monthly_action_perpetual_bars'] = len(
            missing_action_perpetual)
        mark_expected = pd.date_range(
            MARKET_START, END, freq='1h', inclusive='left', tz='UTC')
        mark_missing = mark_expected.difference(data[symbol]['mark'].index)
        from_perpetual = mark_missing.intersection(data[symbol]['perpetual'].index)
        if len(from_perpetual):
            data[symbol]['mark'] = pd.concat([
                data[symbol]['mark'],
                data[symbol]['perpetual'].loc[from_perpetual],
            ]).sort_index()
        remaining = mark_expected.difference(data[symbol]['mark'].index)
        from_spot = remaining.intersection(data[symbol]['spot'].index)
        if len(from_spot):
            data[symbol]['mark'] = pd.concat([
                data[symbol]['mark'], data[symbol]['spot'].loc[from_spot],
            ]).sort_index()
        remaining = mark_expected.difference(data[symbol]['mark'].index)
        quality[symbol]['mark_perpetual_proxy_hours'] = len(from_perpetual)
        quality[symbol]['mark_spot_proxy_hours'] = len(from_spot)
        quality[symbol]['mark_prior_close_proxy_hours'] = len(remaining)

        spot_missing = pd.date_range(
            MARKET_START, END, freq='1h', inclusive='left', tz='UTC').difference(
                data[symbol]['spot'].index)
        perpetual_missing = pd.date_range(
            MARKET_START, END, freq='1h', inclusive='left', tz='UTC').difference(
                data[symbol]['perpetual'].index)
        quality[symbol]['spot_prior_close_mtm_hours'] = len(spot_missing)
        quality[symbol]['perpetual_prior_close_nonfill_hours'] = len(perpetual_missing)
        data[symbol]['spot'] = _causal_mtm_fill(
            data[symbol]['spot'], MARKET_START, END)
        data[symbol]['perpetual'] = _causal_mtm_fill(
            data[symbol]['perpetual'], MARKET_START, END)
        data[symbol]['mark'] = _causal_mtm_fill(
            data[symbol]['mark'], MARKET_START, END)
        _assert_complete_hourly(
            data[symbol]['spot'], MARKET_START, END, f'{symbol} spot')
        _assert_complete_hourly(
            data[symbol]['perpetual'], MARKET_START, END, f'{symbol} perpetual')
        _assert_complete_hourly(
            data[symbol]['mark'], MARKET_START, END, f'{symbol} mark')
        quality[symbol]['mark_after_fallback'] = _gap_stats(
            data[symbol]['mark'], MARKET_START, END)
        print(
            symbol,
            'fallbacks=' + ','.join(
                f'{stream}:{quality[symbol][f"{stream}_exact_1m_fallback_hours"]}'
                for stream in ('spot', 'perpetual', 'mark')),
            f'mark_proxy=perp:{len(from_perpetual)},spot:{len(from_spot)},prior:{len(remaining)}',
            flush=True,
        )
    (output / 'data_quality.json').write_text(
        json.dumps(quality, indent=2) + '\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    base = FCMConfig()
    stress = replace(base, costs=FCMCosts(
        spot_fee_bps=10.0,
        futures_fee_bps=5.0,
        spot_slippage_bps=5.0,
        futures_slippage_bps=5.0,
    ))
    if stress.costs.round_trip_bps != base.qualification_funding_bps:
        raise AssertionError('Frozen funding floor must equal the stress round-trip cost')
    scenarios = {'base': base, 'stress': stress}
    results = {}
    for scenario, config in scenarios.items():
        results[scenario] = {}
        for window, bounds in WINDOWS.items():
            result = simulate_fcm(
                {symbol: data[symbol]['spot'] for symbol in SYMBOLS},
                {symbol: data[symbol]['perpetual'] for symbol in SYMBOLS},
                {symbol: data[symbol]['mark'] for symbol in SYMBOLS},
                {symbol: data[symbol]['funding'] for symbol in SYMBOLS},
                *bounds,
                config,
                initial_capital=250.0,
            )
            results[scenario][window] = result
            summary = result['summary']
            print(
                f'{scenario:6} {window:26} '
                f'qualified={summary["qualified_decisions"]}/{summary["decisions"]} '
                f'episodes={summary["episodes"]} funding=${summary["gross_funding_pnl"]:.2f} '
                f'basis=${summary["price_basis_pnl_before_costs"]:.2f} '
                f'net=${summary["net_pnl"]:.2f} return={summary["return_pct"]:.3f}%',
                flush=True,
            )
    decision = _historical_gate(results)
    payload = {
        'protocol_sha256': protocol_hash,
        'decision': decision,
        'configs': {name: asdict(config) for name, config in scenarios.items()},
        'disclosure': (
            'Protocol-frozen retrospective; distinct public spot, perpetual and mark prices; '
            'not prospective evidence and not approved for live execution.'
        ),
        'results': results,
    }
    (output / 'results.json').write_text(
        json.dumps(payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, protocol_hash, decision, quality))


if __name__ == '__main__':
    main()
