"""Run the frozen S36 funding-regime-switch research protocol."""

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.funding_regime_switch import (
    FundingRegimeConfig,
    build_funding_regime_candidates,
)
from backtest.funding_regime_switch_portfolio import (
    FRSCosts,
    FRSPortfolioConfig,
    simulate_funding_regime_switch_portfolio,
)
from backtest.s36_data import load_s36_universe


SYMBOLS = ('SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT')
REGIMES = ('FADE', 'CONTINUATION')
DIRECTIONS = ('LONG', 'SHORT')
DATA_START, END = '2021-07-01', '2026-09-01'
WINDOWS = {
    'development': ('2022-01-01', '2023-07-01'),
    'validation': ('2023-07-01', '2024-07-01'),
    'retrospective_evaluation': ('2024-07-01', END),
}
INITIAL_CAPITAL = 250.0
INCOME_TARGET_USD = 25.0
BOOTSTRAP_SAMPLES = 10_000


def _verify_protocol_hash(output: Path) -> str:
    """Fail before any market-data load when the frozen protocol changed."""
    protocol = output / 'protocol.json'
    recorded_path = output / 'protocol.sha256'
    actual = sha256(protocol.read_bytes()).hexdigest()
    recorded = recorded_path.read_text().split()[0]
    if actual != recorded:
        raise ValueError('Frozen S36 protocol hash mismatch')
    return actual


def _profit_factor(trades):
    pnls = np.asarray([float(row['pnl']) for row in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    return gains / losses if losses else ('Infinity' if gains else None)


def _numeric_profit_factor(value) -> float:
    if value == 'Infinity':
        return float('inf')
    return float(value) if value is not None else 0.0


def _week_key(timestamp) -> str:
    iso = pd.Timestamp(timestamp).isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _trade_mean_block_bootstrap_lower(
        trades, seed: int = 36, samples: int = BOOTSTRAP_SAMPLES):
    """Lower 95% bound of mean trade dollars, resampling UTC-week blocks."""
    if not trades:
        return None
    groups = {}
    for trade in trades:
        groups.setdefault(_week_key(trade['closed_at']), []).append(
            float(trade['pnl']))
    blocks = list(groups.values())
    generator = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for sample in range(samples):
        chosen = generator.integers(0, len(blocks), size=len(blocks))
        values = [value for index in chosen for value in blocks[index]]
        means[sample] = float(np.mean(values))
    return float(np.quantile(means, .025))


def _calendar_daily(result, start, end) -> pd.Series:
    """Return every UTC calendar day, explicitly retaining zero-trade days."""
    index = pd.date_range(start, end, freq='D', inclusive='left', tz='UTC')
    daily = pd.Series(0.0, index=index, dtype=float)
    for day, pnl in result['summary'].get('daily_pnl', {}).items():
        timestamp = pd.Timestamp(day)
        timestamp = (timestamp.tz_localize('UTC') if timestamp.tzinfo is None
                     else timestamp.tz_convert('UTC'))
        if timestamp in daily.index:
            daily.at[timestamp] += float(pnl)
    return daily


def _daily_block_bootstrap_lower(
        daily: pd.Series, seed: int = 360,
        samples: int = BOOTSTRAP_SAMPLES) -> float | None:
    """Lower 95% daily-mean bound resampling whole UTC ISO-week blocks."""
    if daily.empty:
        return None
    frame = daily.to_frame('pnl')
    frame['week'] = [_week_key(timestamp) for timestamp in frame.index]
    blocks = [group.pnl.to_numpy(dtype=float)
              for _, group in frame.groupby('week', sort=True)]
    generator = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for sample in range(samples):
        chosen = generator.integers(0, len(blocks), size=len(blocks))
        values = np.concatenate([blocks[index] for index in chosen])
        means[sample] = float(values.mean())
    return float(np.quantile(means, .025))


def _daily_diagnostics(result, start, end) -> dict:
    daily = _calendar_daily(result, start, end)
    monthly = daily.groupby(
        daily.index.tz_localize(None).to_period('M')).sum()
    mean = float(daily.mean()) if len(daily) else 0.0
    return {
        'calendar_days': int(len(daily)),
        'mean_daily_pnl_usd': mean,
        'median_daily_pnl_usd': float(daily.median()) if len(daily) else 0.0,
        'share_days_at_least_25_pct': float(
            (daily >= INCOME_TARGET_USD).mean() * 100) if len(daily) else 0.0,
        'worst_day_pnl_usd': float(daily.min()) if len(daily) else 0.0,
        'lower_95_week_block_bootstrap_mean_daily_pnl_usd':
            _daily_block_bootstrap_lower(daily),
        'monthly_pnl_usd': {
            str(month): float(value) for month, value in monthly.items()},
        'linear_capital_for_25_usd_day_diagnostic': (
            INITIAL_CAPITAL * INCOME_TARGET_USD / mean if mean > 0 else None),
        'linear_warning': (
            'diagnostic only; fixed risk cap, execution costs and market '
            'capacity make scaling non-linear'),
    }


def _cohort(trades) -> dict:
    pnls = np.asarray([float(row['pnl']) for row in trades], dtype=float)
    positive = float(np.maximum(pnls, 0).sum()) if len(pnls) else 0.0
    return {
        'trades': int(len(trades)),
        'wins': int((pnls > 0).sum()) if len(pnls) else 0,
        'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
        'net_pnl': float(pnls.sum()) if len(pnls) else 0.0,
        'positive_gross_pnl': positive,
        'profit_factor': _profit_factor(trades),
        'mean_net_r': float(np.mean([
            float(row['r_multiple']) for row in trades])) if trades else 0.0,
    }


def _breakdown(trades) -> dict:
    """Auditable performance cohorts required by the frozen protocol."""
    return {
        'overall': _cohort(trades),
        'per_symbol': {
            symbol: _cohort([
                row for row in trades if row['symbol'] == symbol])
            for symbol in SYMBOLS
        },
        'per_regime': {
            regime: _cohort([
                row for row in trades if row['regime'] == regime])
            for regime in REGIMES
        },
        'per_direction': {
            direction: _cohort([
                row for row in trades if row['side'] == direction])
            for direction in DIRECTIONS
        },
    }


def _candidate_breakdown(result) -> dict:
    candidates = result.get('candidates', [])
    invalidated = result.get('invalidated_candidates', [])
    return {
        'qualified': len(candidates),
        'invalidated_missing_holding_data': len(invalidated),
        'per_symbol': {
            symbol: sum(row['symbol'] == symbol for row in candidates)
            for symbol in SYMBOLS
        },
        'per_regime': {
            regime: sum(row['regime'] == regime for row in candidates)
            for regime in REGIMES
        },
        'per_direction': {
            direction: sum(row['side'] == direction for row in candidates)
            for direction in DIRECTIONS
        },
    }


def _all_window_trades(stress_results, windows) -> list[dict]:
    return [trade for window in windows
            for trade in stress_results[window]['trades']]


def _edge_decision(results) -> dict:
    """Evaluate only the EDGE clauses frozen in the S36 protocol."""
    stress = results['stress']
    reasons = []
    thresholds = {
        'development': (60, 1.15),
        'validation': (40, 1.10),
        'retrospective_evaluation': (60, 1.10),
    }
    for window, (minimum_trades, minimum_pf) in thresholds.items():
        summary = stress[window]['summary']
        if int(summary['trades']) < minimum_trades:
            reasons.append(f'{window}:trades<{minimum_trades}')
        if float(summary['net_pnl']) <= 0:
            reasons.append(f'{window}:net<=0')
        if _numeric_profit_factor(summary.get('profit_factor')) < minimum_pf:
            reasons.append(f'{window}:PF<{minimum_pf}')
        if (float(summary['max_drawdown_pct']) > 4
                or bool(summary.get('risk_fail', False))):
            reasons.append(f'{window}:risk_gate')

    validation_evaluation = _all_window_trades(
        stress, ('validation', 'retrospective_evaluation'))
    combined_mean_r = float(np.mean([
        float(row['r_multiple']) for row in validation_evaluation
    ])) if validation_evaluation else 0.0
    bootstrap_lower = _trade_mean_block_bootstrap_lower(
        validation_evaluation)
    if combined_mean_r < .05:
        reasons.append('validation_evaluation:mean_net_R<0.05')
    if bootstrap_lower is None or bootstrap_lower <= 0:
        reasons.append('validation_evaluation:bootstrap_mean_trade_pnl<=0')

    all_trades = _all_window_trades(stress, WINDOWS)
    all_breakdown = _breakdown(all_trades)
    for regime, row in all_breakdown['per_regime'].items():
        if row['trades'] < 25:
            reasons.append(f'{regime}:trades<25')
        if row['net_pnl'] <= 0:
            reasons.append(f'{regime}:net<=0')
        if _numeric_profit_factor(row['profit_factor']) < 1:
            reasons.append(f'{regime}:PF<1.00')

    validation_breakdown = _breakdown(validation_evaluation)
    eligible_symbols = sum(
        row['trades'] >= 10 and row['net_pnl'] > 0
        for row in validation_breakdown['per_symbol'].values())
    if eligible_symbols < 3:
        reasons.append('fewer_than_3_positive_symbols_with_10_trades')
    total_trades = len(validation_evaluation)
    total_positive = sum(
        row['positive_gross_pnl']
        for row in validation_breakdown['per_symbol'].values())
    for symbol, row in validation_breakdown['per_symbol'].items():
        if total_trades and row['trades'] / total_trades > .50:
            reasons.append(f'{symbol}:trade_share>50pct')
        if total_positive and row['positive_gross_pnl'] / total_positive > .50:
            reasons.append(f'{symbol}:positive_gross_share>50pct')

    for direction, row in all_breakdown['per_direction'].items():
        if not all_trades or row['trades'] / len(all_trades) < .20:
            reasons.append(f'{direction}:trade_share<20pct')

    return {
        'status': 'EDGE_PASS' if not reasons else 'EDGE_FAIL',
        'reasons': reasons,
        'validation_evaluation_mean_net_r': combined_mean_r,
        'validation_evaluation_trade_mean_pnl_bootstrap_lower_95':
            bootstrap_lower,
        'all_windows_breakdown': all_breakdown,
        'validation_evaluation_breakdown': validation_breakdown,
    }


def _income_decision(daily_diagnostics) -> dict:
    reasons = []
    for window in ('validation', 'retrospective_evaluation'):
        row = daily_diagnostics['stress'][window]
        lower = row['lower_95_week_block_bootstrap_mean_daily_pnl_usd']
        if row['mean_daily_pnl_usd'] < INCOME_TARGET_USD:
            reasons.append(f'{window}:mean_daily<25')
        if lower is None or lower < INCOME_TARGET_USD:
            reasons.append(f'{window}:bootstrap_lower<25')
    return {
        'status': 'INCOME_TARGET_PASS' if not reasons
                  else 'INCOME_TARGET_FAIL',
        'target_usd_per_calendar_day': INCOME_TARGET_USD,
        'reasons': reasons,
    }


def _result_diagnostics(results) -> dict:
    output = {'base': {}, 'stress': {}}
    for scenario in output:
        for window in WINDOWS:
            replay = results[scenario][window]
            output[scenario][window] = {
                'execution': replay['summary'].get('diagnostics', {}),
                'candidates': _candidate_breakdown(replay),
                'trades': _breakdown(replay['trades']),
            }
    return output


def _format_pf(value) -> str:
    return str(value) if value in (None, 'Infinity') else f'{float(value):.3f}'


def _append_breakdown_table(lines, title, breakdown):
    lines.extend([
        '', f'## {title}', '',
        '| Cohort | Trades | WR | PF | Net | Mean R |',
        '|---|---:|---:|---:|---:|---:|',
    ])
    groups = (
        [('symbol/' + key, value)
         for key, value in breakdown['per_symbol'].items()]
        + [('regime/' + key, value)
           for key, value in breakdown['per_regime'].items()]
        + [('direction/' + key, value)
           for key, value in breakdown['per_direction'].items()]
    )
    for label, row in groups:
        lines.append(
            f'| {label} | {row["trades"]} | {row["win_rate_pct"]:.1f}% | '
            f'{_format_pf(row["profit_factor"])} | ${row["net_pnl"]:.2f} | '
            f'{row["mean_net_r"]:.3f} |')


def _report(results, daily, edge, income, diagnostics, protocol_hash) -> str:
    lines = [
        '# S36 — funding regime switch', '',
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
                f'{summary["win_rate_pct"]:.1f}% | '
                f'{_format_pf(summary["profit_factor"])} | '
                f'${summary["net_pnl"]:.2f} | '
                f'${diagnostic["mean_daily_pnl_usd"]:.4f} | '
                f'${diagnostic["median_daily_pnl_usd"]:.4f} | '
                f'{diagnostic["share_days_at_least_25_pct"]:.2f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% |')
    lines.extend([
        '', f'Edge decision: **{edge["status"]}**.',
        f'Income-target decision: **{income["status"]}**.', '',
        'The $25 target is measured over every UTC calendar day, including '
        'zero-trade days. EDGE and INCOME_TARGET are independent. A failed '
        'gate may not be rescued by increasing risk or leverage.',
    ])
    _append_breakdown_table(
        lines, 'Stress cohorts — all windows',
        edge['all_windows_breakdown'])
    _append_breakdown_table(
        lines, 'Stress cohorts — validation plus retrospective evaluation',
        edge['validation_evaluation_breakdown'])
    lines.extend(['', '## Execution diagnostics', ''])
    for scenario in ('base', 'stress'):
        for window in WINDOWS:
            row = diagnostics[scenario][window]
            lines.append(
                f'- `{scenario}/{window}`: '
                f'candidates={row["candidates"]["qualified"]}, '
                f'invalidated={row["candidates"]["invalidated_missing_holding_data"]}, '
                f'execution={json.dumps(row["execution"], sort_keys=True)}')
    lines.extend(['', '## Edge failure reasons', ''])
    lines.extend(f'- {reason}' for reason in edge['reasons'])
    if not edge['reasons']:
        lines.append('- None.')
    lines.extend(['', '## Income-target failure reasons', ''])
    lines.extend(f'- {reason}' for reason in income['reasons'])
    if not income['reasons']:
        lines.append('- None.')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s35-cache')
    parser.add_argument(
        '--output', default='docs/research/s36_regime_switch')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()

    output = Path(args.output)
    # This must remain the first operation that can fail in the research run.
    protocol_hash = _verify_protocol_hash(output)

    markets, manifest = load_s36_universe(
        SYMBOLS, DATA_START, END, args.cache,
        download_missing=args.download, workers=args.workers)
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    print('S36 public 5m universe ready', flush=True)

    signal_config = FundingRegimeConfig()
    candidates = build_funding_regime_candidates(
        markets, WINDOWS['development'][0], END, signal_config)
    print('S36 deterministic candidates', len(candidates), flush=True)

    stress = FRSPortfolioConfig()
    base = replace(stress, costs=FRSCosts(
        taker_fee_bps_per_side=5,
        slippage_bps_per_side=1,
    ))
    if base.costs.round_trip_bps != 12 or stress.costs.round_trip_bps != 30:
        raise AssertionError('Frozen S36 cost scenarios changed')

    results = {'base': {}, 'stress': {}}
    daily = {'base': {}, 'stress': {}}
    for scenario, config in (('base', base), ('stress', stress)):
        for window, bounds in WINDOWS.items():
            replay = simulate_funding_regime_switch_portfolio(
                markets, candidates, *bounds,
                config=config, initial_capital=INITIAL_CAPITAL)
            # Keep high-frequency equity in memory for the simulator's DD,
            # but not in the durable result artifact.
            replay.pop('equity_curve', None)
            results[scenario][window] = replay
            daily[scenario][window] = _daily_diagnostics(replay, *bounds)
            summary = replay['summary']
            print(
                scenario, window, 'trades', summary['trades'],
                'net', f'${summary["net_pnl"]:.2f}', flush=True)

    edge = _edge_decision(results)
    income = _income_decision(daily)
    diagnostics = _result_diagnostics(results)
    payload = {
        'protocol_sha256': protocol_hash,
        'edge_decision': edge,
        'income_target_decision': income,
        'configs': {
            'signal': asdict(signal_config),
            'base_portfolio': asdict(base),
            'stress_portfolio': asdict(stress),
        },
        'daily_diagnostics': daily,
        'result_diagnostics': diagnostics,
        'results': results,
        'disclosure': (
            'retrospective public-data replay; genuine OOS begins only after '
            'protocol and implementation hashes are frozen'),
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, daily, edge, income, diagnostics, protocol_hash))


if __name__ == '__main__':
    main()
