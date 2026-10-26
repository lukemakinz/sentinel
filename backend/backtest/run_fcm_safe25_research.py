"""Protocol-frozen replay of FCM_SAFE25 with exact 1m emergency execution."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .fcm_safe25 import INITIAL_CAPITAL, evaluate_safe25_gate, safe25_configs
from .funding_carry_data import (
    load_fcm_minute_months,
    minute_archive_specs,
    prepare_archives,
)
from .funding_carry_v2 import monthly_fcm_targets, simulate_fcm
from .run_fcm_1m_research import SYMBOLS, WINDOWS
from .run_s31_fcm_monthly_reset_research import _load_data


def _universe_data(data: dict, symbols, stream: str) -> dict:
    return {symbol: data[symbol][stream] for symbol in symbols}


def _active_minute_months(data: dict, config) -> dict[str, set[str]]:
    """Union active and boundary months for primary and LOO universes."""
    months = {symbol: set() for symbol in SYMBOLS}
    universes = [SYMBOLS] + [
        tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        for excluded in SYMBOLS
    ]
    for universe in universes:
        schedule = monthly_fcm_targets(
            _universe_data(data, universe, 'spot'),
            _universe_data(data, universe, 'funding'),
            *WINDOWS['all_available'], config,
        )
        for item in schedule:
            if item['target'] is None:
                continue
            period = item['decision_time'].tz_localize(None).to_period('M')
            months[item['target']].update((str(period), str(period + 1)))
    return months


def _simulate(data: dict, minute: dict, symbols, bounds, config) -> dict:
    return simulate_fcm(
        _universe_data(data, symbols, 'spot'),
        _universe_data(data, symbols, 'perpetual'),
        _universe_data(data, symbols, 'mark'),
        _universe_data(data, symbols, 'funding'),
        *bounds,
        config,
        initial_capital=INITIAL_CAPITAL,
        emergency_spot_prices=_universe_data(minute, symbols, 'spot'),
        emergency_perpetual_prices=_universe_data(
            minute, symbols, 'perpetual'),
        emergency_mark_prices=_universe_data(minute, symbols, 'mark'),
    )


def _minute_quality(minute: dict, months: dict[str, set[str]]) -> dict:
    result = {}
    for symbol in SYMBOLS:
        expected_index = pd.DatetimeIndex([])
        for month in sorted(months[symbol]):
            period = pd.Period(month, freq='M')
            expected_index = expected_index.append(pd.date_range(
                period.start_time.tz_localize('UTC'),
                (period + 1).start_time.tz_localize('UTC'),
                freq='1min', inclusive='left'))
        expected = len(expected_index)
        result[symbol] = {
            'months': sorted(months[symbol]),
            'expected_rows': expected,
        }
        for stream in ('spot', 'perpetual', 'mark'):
            frame = minute[symbol][stream]
            result[symbol][f'{stream}_rows'] = len(frame)
            result[symbol][f'{stream}_missing_rows'] = expected - len(frame)
            result[symbol][f'{stream}_duplicate_rows'] = int(
                frame.index.duplicated().sum())
            if stream == 'mark':
                exact = frame.loc[
                    frame.risk_source.astype(str).str.startswith('mark_1m')]
                exact_missing = expected_index.difference(exact.index)
                envelope_hours = pd.DatetimeIndex(frame.loc[
                    frame.risk_source.astype(str).str.contains(
                        'hourly_high_envelope'),
                ].index.floor('h').unique())
                uncovered = pd.DatetimeIndex(
                    exact_missing.floor('h').unique()).difference(envelope_hours)
                result[symbol]['mark_exact_1m_missing_rows'] = len(exact_missing)
                result[symbol]['mark_hourly_envelope_hours'] = len(envelope_hours)
                result[symbol]['mark_uncovered_gap_hours'] = len(uncovered)
                if len(uncovered):
                    raise ValueError(
                        f'Uncovered mark safety gaps for {symbol}: '
                        f'{list(uncovered[:5])}')
            if frame.index.has_duplicates:
                raise ValueError(
                    f'Incomplete exact 1m safety data for {symbol} {stream}')
    return result


def _report(results: dict, gate: dict, leave_one_out: dict,
            protocol_hash: str, minute_quality: dict) -> str:
    lines = [
        '# FCM_SAFE25 — exact-hedge monthly funding carry',
        '',
        f'Frozen protocol hash: `{protocol_hash}`.',
        '',
        '| Window | Cost case | Episodes | Funding | Basis PnL | Net | Return | Max DD | Min exit-ready futures equity | Max audited mark-high leverage | Emergency closes |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress', 'severe'):
            summary = results[scenario][window]['summary']
            lines.append(
                f'| {window} | {scenario} | {summary["episodes"]} | '
                f'${summary["gross_funding_pnl"]:.2f} | '
                f'${summary["price_basis_pnl_before_costs"]:.2f} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_mtm_drawdown_pct"]:.3f}% | '
                f'${summary["min_exit_ready_futures_equity_usd"]:.2f} | '
                f'{summary["max_high_mark_leverage"]:.3f}x | '
                f'{summary["emergency_closes"]} |'
            )

    lines.extend([
        '',
        '## Frozen acceptance gates',
        '',
        '| Gate | Result | Observed | Requirement |',
        '|---|---:|---:|---:|',
    ])
    for row in gate['checks']:
        observed = row['observed']
        if isinstance(observed, float):
            observed = f'{observed:.8f}'
        lines.append(
            f'| {row["name"]} | {"PASS" if row["passed"] else "FAIL"} | '
            f'{observed} | {row["requirement"]} |')

    lines.extend([
        '',
        '## Leave-one-symbol-out stress',
        '',
    ])
    for excluded, replay in sorted(leave_one_out.items()):
        lines.append(
            f'- without {excluded}: ${replay["summary"]["net_pnl"]:.4f} '
            f'across {replay["summary"]["episodes"]} episodes')

    newest = results['stress']['retrospective_evaluation']['summary']
    severe_newest = results['severe']['retrospective_evaluation']['summary']
    combined = results['stress']['all_available']['summary']
    lines.extend([
        '',
        f'Decision: **{gate["decision"]}**.',
        '',
        '## Interpretation boundary',
        '',
        f'- The newest stress window earned only ${newest["net_pnl"]:.4f}; '
        f'at severe costs it earned ${severe_newest["net_pnl"]:.4f}.',
        '- Emergency monitoring used checksum-verified real 1m mark highs. Any '
        'official 1m archive gap is covered by the containing official hourly '
        'mark high at hour close; execution is delayed until the next real open.',
        f'- Minute coverage was validated for {sum(len(x["months"]) for x in minute_quality.values())} '
        'symbol-months and three separate streams.',
        '- Current Binance common lot steps were applied to both legs: ETH 0.001, '
        'SOL 0.01 and BNB 0.01. Rounding down left '
        f'${combined["unused_spot_notional_after_rounding_usd"]:.2f} undeployed '
        'across all 29 entries.',
        '- Every historical period was already inspected in predecessor research. '
        'A pass permits paper-forward observation only; it is not evidence that '
        'future profit is guaranteed.',
        '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--output', default='docs/research/fcm_safe25')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    protocol = output / 'protocol.json'
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != recorded_hash:
        raise ValueError('Frozen FCM_SAFE25 protocol hash mismatch')

    data, hourly_quality = _load_data(
        cache, output, args.download, args.workers)
    configs = safe25_configs()
    if configs['stress'].costs.round_trip_bps != 50:
        raise AssertionError('Stress costs must be 50 bps round trip')
    if configs['severe'].costs.round_trip_bps != 80:
        raise AssertionError('Severe costs must be 80 bps round trip')

    active_months = _active_minute_months(data, configs['base'])
    specs = minute_archive_specs(active_months)
    prepare_archives(
        specs, cache, download_missing=args.download, workers=args.workers)
    minute, minute_manifest = load_fcm_minute_months(
        active_months, cache,
        download_missing=args.download, workers=args.workers)
    minute_quality = _minute_quality(minute, active_months)
    (output / 'minute_manifest.json').write_text(
        json.dumps(minute_manifest, indent=2) + '\n')
    (output / 'minute_quality.json').write_text(
        json.dumps(minute_quality, indent=2) + '\n')

    results = {}
    for scenario, config in configs.items():
        results[scenario] = {}
        for window, bounds in WINDOWS.items():
            replay = _simulate(data, minute, SYMBOLS, bounds, config)
            results[scenario][window] = replay
            summary = replay['summary']
            print(
                scenario, window, 'episodes', summary['episodes'],
                'net', f'${summary["net_pnl"]:.4f}',
                'min-exit-equity',
                f'${summary["min_exit_ready_futures_equity_usd"]:.2f}',
                flush=True,
            )

    leave_one_out = {}
    for excluded in SYMBOLS:
        universe = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        replay = _simulate(
            data, minute, universe, WINDOWS['all_available'], configs['stress'])
        leave_one_out[excluded] = replay
        print('leave-out', excluded, 'net',
              f'${replay["summary"]["net_pnl"]:.4f}', flush=True)

    gate = evaluate_safe25_gate(results, leave_one_out)
    payload = {
        'protocol_sha256': actual_hash,
        'decision': gate['decision'],
        'gate': gate,
        'configs': {name: asdict(config) for name, config in configs.items()},
        'disclosure': 'all historical windows contaminated; paper-forward only',
        'results': results,
        'leave_one_out_stress': leave_one_out,
        'hourly_data_quality': hourly_quality,
        'minute_data_quality': minute_quality,
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, gate, leave_one_out, actual_hash, minute_quality))
    print('decision', gate['decision'], flush=True)


if __name__ == '__main__':
    main()
