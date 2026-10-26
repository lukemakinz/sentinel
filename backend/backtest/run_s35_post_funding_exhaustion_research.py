"""Run the frozen S35 post-funding exhaustion research protocol."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.post_funding_exhaustion import (
    PFEConfig,
    PFECosts,
    build_post_funding_candidates,
    simulate_post_funding_exhaustion,
)
from backtest.s35_data import load_s35_universe


SYMBOLS = ('SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT')
DATA_START, END = '2021-07-01', '2026-09-01'
WINDOWS = {
    'development': ('2022-01-01', '2023-07-01'),
    'validation': ('2023-07-01', '2024-07-01'),
    'retrospective_evaluation': ('2024-07-01', END),
}
INITIAL_CAPITAL = 250.0
BOOTSTRAP_SAMPLES = 10_000


def _profit_factor(trades):
    pnls = np.asarray([float(row['pnl']) for row in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    return gains / losses if losses else ('Infinity' if gains else None)


def _week_key(timestamp):
    iso = pd.Timestamp(timestamp).isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _trade_mean_block_bootstrap_lower(trades, seed=35):
    if not trades:
        return None
    groups = {}
    for trade in trades:
        groups.setdefault(_week_key(trade['closed_at']), []).append(
            float(trade['pnl']))
    blocks = list(groups.values())
    generator = np.random.default_rng(seed)
    means = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for sample in range(BOOTSTRAP_SAMPLES):
        chosen = generator.integers(0, len(blocks), size=len(blocks))
        values = [value for index in chosen for value in blocks[index]]
        means[sample] = np.mean(values)
    return float(np.quantile(means, .025))


def _calendar_daily(result, start, end):
    index = pd.date_range(start, end, freq='D', inclusive='left', tz='UTC')
    values = pd.Series(0.0, index=index)
    for day, pnl in result['summary']['daily_pnl'].items():
        timestamp = pd.Timestamp(day, tz='UTC')
        if timestamp in values.index:
            values.at[timestamp] += float(pnl)
    return values


def _daily_block_bootstrap_lower(daily, seed=350):
    frame = daily.to_frame('pnl')
    frame['week'] = [
        _week_key(timestamp) for timestamp in frame.index]
    blocks = [group.pnl.to_numpy(dtype=float)
              for _, group in frame.groupby('week', sort=True)]
    generator = np.random.default_rng(seed)
    means = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for sample in range(BOOTSTRAP_SAMPLES):
        chosen = generator.integers(0, len(blocks), size=len(blocks))
        values = np.concatenate([blocks[index] for index in chosen])
        means[sample] = float(values.mean())
    return float(np.quantile(means, .025))


def _daily_diagnostics(result, start, end):
    daily = _calendar_daily(result, start, end)
    monthly = daily.groupby(
        daily.index.tz_localize(None).to_period('M')).sum()
    mean = float(daily.mean())
    return {
        'calendar_days': int(len(daily)),
        'mean_daily_pnl_usd': mean,
        'median_daily_pnl_usd': float(daily.median()),
        'share_days_at_least_25_pct': float((daily >= 25).mean() * 100),
        'worst_day_pnl_usd': float(daily.min()),
        'lower_95_week_block_bootstrap_mean_daily_pnl_usd':
            _daily_block_bootstrap_lower(daily),
        'monthly_pnl_usd': {
            str(month): float(value) for month, value in monthly.items()},
        'linear_capital_for_25_usd_day_diagnostic': (
            INITIAL_CAPITAL * 25 / mean if mean > 0 else None),
        'linear_warning': 'diagnostic only; fixed risk cap and market capacity make scaling non-linear',
    }


def _combined_concentration(trades):
    per_symbol = {}
    total_positive = sum(max(float(row['pnl']), 0) for row in trades)
    for symbol in SYMBOLS:
        selected = [row for row in trades if row['symbol'] == symbol]
        positive = sum(max(float(row['pnl']), 0) for row in selected)
        per_symbol[symbol] = {
            'trades': len(selected),
            'net_pnl': float(sum(float(row['pnl']) for row in selected)),
            'positive_gross_pnl': float(positive),
            'trade_share_pct': len(selected) / len(trades) * 100 if trades else 0.0,
            'positive_gross_share_pct': (
                positive / total_positive * 100 if total_positive else None),
        }
    leave_one_out = {}
    for symbol in SYMBOLS:
        remaining = [row for row in trades if row['symbol'] != symbol]
        leave_one_out[symbol] = {
            'trades': len(remaining),
            'net_pnl': float(sum(float(row['pnl']) for row in remaining)),
            'profit_factor': _profit_factor(remaining),
        }
    return {'per_symbol': per_symbol, 'leave_one_out': leave_one_out}


def _edge_decision(results):
    stress = results['stress']
    reasons = []
    thresholds = {
        'development': (40, 1.20),
        'validation': (25, 1.10),
        'retrospective_evaluation': (25, 1.10),
    }
    for window, (minimum_trades, minimum_pf) in thresholds.items():
        summary = stress[window]['summary']
        pf = summary['profit_factor']
        numeric_pf = float('inf') if pf == 'Infinity' else (pf or 0.0)
        if summary['trades'] < minimum_trades:
            reasons.append(f'{window}:trades<{minimum_trades}')
        if summary['net_pnl'] <= 0:
            reasons.append(f'{window}:net<=0')
        if numeric_pf < minimum_pf:
            reasons.append(f'{window}:PF<{minimum_pf}')
        if summary['max_drawdown_pct'] > 4 or summary['risk_fail']:
            reasons.append(f'{window}:risk_gate')

    validation_evaluation = (
        stress['validation']['trades']
        + stress['retrospective_evaluation']['trades'])
    bootstrap_lower = _trade_mean_block_bootstrap_lower(validation_evaluation)
    if bootstrap_lower is None or bootstrap_lower <= 0:
        reasons.append('validation_evaluation:bootstrap_lower<=0')

    all_trades = [
        row for window in WINDOWS for row in stress[window]['trades']]
    long_count = sum(row['side'] == 'LONG' for row in all_trades)
    short_count = sum(row['side'] == 'SHORT' for row in all_trades)
    if (not all_trades or long_count / len(all_trades) < .20
            or short_count / len(all_trades) < .20):
        reasons.append('direction_balance<20pct')

    concentration = _combined_concentration(validation_evaluation)
    eligible_positive = sum(
        row['trades'] >= 5 and row['net_pnl'] > 0
        for row in concentration['per_symbol'].values())
    if eligible_positive < 3:
        reasons.append('fewer_than_3_positive_symbols_with_5_trades')
    for symbol, row in concentration['per_symbol'].items():
        if row['trade_share_pct'] > 40:
            reasons.append(f'{symbol}:trade_share>40pct')
        if (row['positive_gross_share_pct'] is not None
                and row['positive_gross_share_pct'] > 40):
            reasons.append(f'{symbol}:positive_gross_share>40pct')
    for symbol, row in concentration['leave_one_out'].items():
        pf = row['profit_factor']
        numeric_pf = float('inf') if pf == 'Infinity' else (pf or 0.0)
        if row['net_pnl'] <= 0 or numeric_pf < 1:
            reasons.append(f'leave_out_{symbol}:net_or_PF_fail')
    return {
        'status': 'EDGE_PASS' if not reasons else 'EDGE_FAIL',
        'reasons': reasons,
        'validation_evaluation_trade_mean_bootstrap_lower_95': bootstrap_lower,
        'validation_evaluation_concentration': concentration,
    }


def _income_decision(daily_diagnostics):
    reasons = []
    for window in ('validation', 'retrospective_evaluation'):
        row = daily_diagnostics['stress'][window]
        if row['mean_daily_pnl_usd'] < 25:
            reasons.append(f'{window}:mean_daily<25')
        if row['lower_95_week_block_bootstrap_mean_daily_pnl_usd'] < 25:
            reasons.append(f'{window}:bootstrap_lower<25')
    return {
        'status': 'INCOME_TARGET_PASS' if not reasons else 'INCOME_TARGET_FAIL',
        'target_usd_per_calendar_day': 25,
        'reasons': reasons,
    }


def _report(results, daily, edge, income, protocol_hash):
    lines = [
        '# S35 — post-funding exhaustion', '',
        f'Frozen protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | Trades | WR | PF | Net | Avg/day | Median/day | Days >=$25 | DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress'):
            summary = results[scenario][window]['summary']
            diagnostic = daily[scenario][window]
            lines.append(
                f'| {window} | {scenario} | {summary["trades"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {summary["profit_factor"]} | '
                f'${summary["net_pnl"]:.2f} | '
                f'${diagnostic["mean_daily_pnl_usd"]:.4f} | '
                f'${diagnostic["median_daily_pnl_usd"]:.4f} | '
                f'{diagnostic["share_days_at_least_25_pct"]:.2f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% |')
    lines.extend([
        '', f'Edge decision: **{edge["status"]}**.',
        f'Income-target decision: **{income["status"]}**.', '',
        'The $25 target is evaluated over every calendar day, including days '
        'with no position. EDGE and INCOME_TARGET are deliberately separate. '
        'No failing result may be rescued by increasing leverage or risk.', '',
        '## Edge failure reasons', '',
    ])
    lines.extend(f'- {reason}' for reason in edge['reasons'])
    lines.extend(['', '## Income-target failure reasons', ''])
    lines.extend(f'- {reason}' for reason in income['reasons'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s35-cache')
    parser.add_argument(
        '--output', default='docs/research/s35_post_funding_exhaustion')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    if actual_hash != recorded_hash:
        raise ValueError('Frozen S35 protocol hash mismatch')

    markets, manifest = load_s35_universe(
        SYMBOLS, DATA_START, END, args.cache,
        download_missing=args.download, workers=args.workers)
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    print('S35 public 5m universe ready', flush=True)

    stress = PFEConfig()
    base = replace(stress, costs=PFECosts(
        taker_fee_bps_per_side=5, slippage_bps_per_side=1))
    if base.costs.round_trip_bps != 12 or stress.costs.round_trip_bps != 30:
        raise AssertionError('Frozen S35 costs changed')
    candidates = build_post_funding_candidates(
        markets, WINDOWS['development'][0], END, stress)
    print('S35 deterministic candidates', len(candidates), flush=True)
    results = {'base': {}, 'stress': {}}
    daily = {'base': {}, 'stress': {}}
    for scenario, config in {'base': base, 'stress': stress}.items():
        for window, bounds in WINDOWS.items():
            replay = simulate_post_funding_exhaustion(
                markets, *bounds, config=config,
                initial_capital=INITIAL_CAPITAL,
                precomputed_candidates=candidates)
            # Full 5m equity paths are useful in-memory for DD but excessively
            # large and redundant in the durable JSON artifact.
            replay.pop('equity_curve', None)
            results[scenario][window] = replay
            daily[scenario][window] = _daily_diagnostics(
                replay, *bounds)
            summary = replay['summary']
            print(scenario, window, 'trades', summary['trades'],
                  'net', f'${summary["net_pnl"]:.2f}', flush=True)

    edge = _edge_decision(results)
    income = _income_decision(daily)
    payload = {
        'protocol_sha256': actual_hash,
        'edge_decision': edge,
        'income_target_decision': income,
        'configs': {'base': asdict(base), 'stress': asdict(stress)},
        'daily_diagnostics': daily,
        'results': results,
        'disclosure': 'retrospective public-data replay; genuine OOS begins after code freeze',
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, daily, edge, income, actual_hash))


if __name__ == '__main__':
    main()
