"""Frozen historical characterization of S100 global regime + OI swing."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.global_direction_oi import (
    GlobalDirectionConfig,
    OIExecutionConfig,
    evaluate_regime_forward_returns,
    global_direction_series,
    regime_oi_targets,
)
from .metrics_data import load_metrics, prefetch_metrics_archives
from .run_s97_dual_horizon_trend import (
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import TrendPortfolioCosts, simulate_trend_portfolio


PROTOCOL_SHA256 = '8b06a9a2704de0f8a1e6b38a69298358b07eaf090fde12c6f1554c831da64c39'
REGIME_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
TRADED_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
PRICE_WARMUP = '2022-04-04'
OI_WARMUP = '2024-01-01'
START = '2024-08-01'
END = '2026-09-01'
SLICES = {
    'development': ('2024-08-01', '2025-05-01'),
    'validation': ('2025-05-01', '2026-01-01'),
    'retrospective_evaluation': ('2026-01-01', END),
}
COSTS = {
    'base': TrendPortfolioCosts(5.0, 2.0),
    'stress': TrendPortfolioCosts(8.0, 5.0),
    'severe': TrendPortfolioCosts(10.0, 10.0),
}


def _daily_open_interest(metrics: pd.DataFrame) -> pd.Series:
    fresh = metrics.loc[
        (metrics.metrics_age_minutes <= 10) & (metrics.open_interest > 0),
        'open_interest',
    ]
    result = fresh.groupby(fresh.index.normalize()).last().astype(float)
    if result.empty or result.index.has_duplicates or (result <= 0).any():
        raise ValueError('Invalid daily open-interest series')
    return result


def _daily_profit_factor(daily_pnl: pd.Series) -> float:
    positive = float(daily_pnl[daily_pnl > 0].sum())
    negative = float(-daily_pnl[daily_pnl < 0].sum())
    return positive / negative if negative > 0 else (float('inf') if positive > 0 else 0.0)


def _direction_pnl(daily_pnl: pd.Series, targets: list[dict]) -> dict:
    regimes = pd.Series(
        {pd.Timestamp(target['timestamp']): target['regime'] for target in targets},
        dtype=object,
    ).sort_index()
    aligned = regimes.reindex(daily_pnl.index, method='ffill').fillna('SIDEWAYS')
    return {
        'long_up_regime': float(daily_pnl.loc[aligned == 'UP'].sum()),
        'short_down_regime': float(daily_pnl.loc[aligned == 'DOWN'].sum()),
        'sideways_or_unclassified': float(daily_pnl.loc[aligned == 'SIDEWAYS'].sum()),
    }


def _target_counts(targets: list[dict]) -> dict:
    return {
        'decisions': len(targets),
        'invested_decisions': sum(bool(target['weights']) for target in targets),
        'long_decisions': sum(any(weight > 0 for weight in target['weights'].values())
                              for target in targets),
        'short_decisions': sum(any(weight < 0 for weight in target['weights'].values())
                               for target in targets),
        'cash_decisions': sum(not target['weights'] for target in targets),
        'sideways_decisions': sum(target['regime'] == 'SIDEWAYS' for target in targets),
    }


def _render_report(result: dict) -> str:
    lines = [
        '# S100 — global direction + OI pullback swing', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Discovery-contaminated historical characterization; not live approval.**', '',
        'Layer 1 emits UP / DOWN / SIDEWAYS. Layer 2 trades EMA20 pullbacks with '
        'rising OI: long only in UP, short only in DOWN, cash in SIDEWAYS.', '',
        f'Target audit: `{result["target_counts"]}`.', '',
        '## Global direction diagnostic', '',
        f'20-day BTC forward returns by regime: `{result["regime_forward_diagnostic"]}`.', '',
        '## Portfolio replay', '',
        '| Period | Costs | PnL | Return | $/month | DD | Sharpe | Positive months |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for period, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {period} | {scenario} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_start_nav_pct"]:.2f}% | '
                f'${row["usd_per_calendar_day"] * 30.4375:.2f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["annualized_sharpe"]:.2f} | {row["positive_month_share"]:.1%} |')
    lines.extend(['',
        '| Full replay | PnL | Return | DD | Sharpe | Daily-PnL PF | Funding |',
        '|---|---:|---:|---:|---:|---:|---:|'])
    for scenario, row in result['continuous_replays'].items():
        lines.append(
            f'| {scenario} | ${row["net_pnl"]:.2f} | {row["return_pct"]:.2f}% | '
            f'{row["max_drawdown_pct"]:.2f}% | {row["annualized_sharpe"]:.2f} | '
            f'{row["daily_profit_factor"]:.3f} | ${row["funding_pnl"]:.2f} |')
    lines.extend(['', '## Direction and robustness', '',
        f'- Stress PnL by direction: `{result["stress_direction_pnl"]}`.',
        f'- OI threshold neighbors: `{result["oi_threshold_neighbor_stress_pnl"]}`.',
        f'- Decision phase offsets: `{result["phase_stress_pnl"]}`.',
        f'- Leave one traded symbol out: `{result["leave_one_out_stress_pnl"]}`.',
        f'- 28-day bootstrap: `{result["stress_block_bootstrap"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'No parameter was changed after observing the replay. A historical pass '
        'would authorize paper-forward observation only.', ''])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s100_global_regime_oi_swing')
    parser.add_argument('--download-workers', type=int, default=16)
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(
            f'Protocol changed after freeze: expected {PROTOCOL_SHA256}, got {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    daily, funding, manifest = {}, {}, {'prices': {}, 'metrics': {}}
    for symbol in REGIME_SYMBOLS:
        daily[symbol], funding[symbol], manifest['prices'][symbol] = load_interval_archives(
            symbol, PRICE_WARMUP, END, args.cache, interval='1d')
        print(symbol, len(daily[symbol]), 'verified daily candles', flush=True)

    archive_count = prefetch_metrics_archives(
        TRADED_SYMBOLS, OI_WARMUP, END, args.cache, args.download_workers)
    print(archive_count, 'metrics archives cached and checksum-verified', flush=True)
    open_interest = {}
    for symbol in TRADED_SYMBOLS:
        metrics, metrics_manifest = load_metrics(
            symbol, OI_WARMUP, END, args.cache,
            include_freshness=True, required_columns=('open_interest',))
        open_interest[symbol] = _daily_open_interest(metrics)
        manifest['metrics'][symbol] = metrics_manifest
        print(symbol, len(open_interest[symbol]), 'verified daily OI closes', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    regime_config = GlobalDirectionConfig()
    execution_config = OIExecutionConfig()
    regimes = global_direction_series(daily, START, END, regime_config)
    targets = regime_oi_targets(
        daily, open_interest, funding, regimes, START, END,
        execution_config, symbol_order=TRADED_SYMBOLS)
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in TRADED_SYMBOLS}

    result = {
        'protocol_sha256': actual_hash,
        'global_direction_config': asdict(regime_config),
        'execution_config': asdict(execution_config),
        'target_counts': _target_counts(targets),
        'regime_occupancy': regimes.regime.value_counts(normalize=True).to_dict(),
        'regime_forward_diagnostic': evaluate_regime_forward_returns(
            regimes, daily['BTCUSDT']),
        'continuous_replays': {}, 'slices': {},
        'oi_threshold_neighbor_stress_pnl': {},
        'phase_stress_pnl': {}, 'leave_one_out_stress_pnl': {},
    }
    replays = {}
    for scenario, costs in COSTS.items():
        replay = simulate_trend_portfolio(markets, targets, START, END, 500.0, costs)
        replays[scenario] = replay
        summary = dict(replay['summary'])
        summary['daily_profit_factor'] = _daily_profit_factor(replay['daily_pnl'])
        result['continuous_replays'][scenario] = summary
        for name, bounds in SLICES.items():
            result['slices'].setdefault(name, {})[scenario] = _slice_metrics(
                replay['daily_pnl'], *bounds)
        print(scenario, summary, flush=True)

    stress_daily = replays['stress']['daily_pnl']
    result['stress_direction_pnl'] = _direction_pnl(stress_daily, targets)
    result['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    result['stress_block_bootstrap'] = _block_bootstrap(stress_daily)
    pd.DataFrame({name: replay['daily_pnl'] for name, replay in replays.items()}).to_csv(
        output / 'daily_pnl.csv', index_label='timestamp')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')

    for threshold in (0.0, 0.10):
        neighbor = replace(execution_config, minimum_oi_oscillator_pct=threshold)
        neighbor_targets = regime_oi_targets(
            daily, open_interest, funding, regimes, START, END,
            neighbor, symbol_order=TRADED_SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['oi_threshold_neighbor_stress_pnl'][str(threshold)] = (
            replay['summary']['net_pnl'])

    for offset in (1, 2):
        phase_start = str(pd.Timestamp(START) + pd.Timedelta(days=offset))
        phase_targets = regime_oi_targets(
            daily, open_interest, funding, regimes, phase_start, END,
            execution_config, symbol_order=TRADED_SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, phase_targets, START, END, 500.0, COSTS['stress'])
        result['phase_stress_pnl'][str(offset)] = replay['summary']['net_pnl']

    for excluded in TRADED_SYMBOLS:
        kept = tuple(symbol for symbol in TRADED_SYMBOLS if symbol != excluded)
        subset_targets = regime_oi_targets(
            daily,
            {symbol: open_interest[symbol] for symbol in kept},
            funding, regimes, START, END, execution_config, symbol_order=kept)
        replay = simulate_trend_portfolio(
            {symbol: markets[symbol] for symbol in kept}, subset_targets,
            START, END, 500.0, COSTS['stress'])
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress = result['continuous_replays']['stress']
    severe = result['continuous_replays']['severe']
    monthly = result['stress_monthly_dispersion']
    slices = result['slices']
    direction = result['stress_direction_pnl']
    core_pass = (
        stress['net_pnl'] > 0 and stress['annualized_sharpe'] >= 0.50
        and stress['max_drawdown_pct'] <= 15.0
        and stress['daily_profit_factor'] > 1.05
        and monthly['positive_month_share'] >= 0.40
        and direction['long_up_regime'] >= 0
        and direction['short_down_regime'] >= 0
        and slices['development']['stress']['net_pnl'] > 0
        and slices['validation']['stress']['net_pnl'] > 0
        and slices['retrospective_evaluation']['stress']['net_pnl'] >= 0
        and severe['net_pnl'] > 0)
    robustness_pass = (
        all(value > 0 for value in result['oi_threshold_neighbor_stress_pnl'].values())
        and all(value > 0 for value in result['phase_stress_pnl'].values())
        and sum(value > 0 for value in result['leave_one_out_stress_pnl'].values()) >= 2
        and result['stress_block_bootstrap']['p10_terminal_pnl'] > 0)
    result['gate_components'] = {
        'core_pass': bool(core_pass), 'robustness_pass': bool(robustness_pass)}
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core_pass and robustness_pass else 'REJECTED_AT_HISTORICAL_GATE')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
