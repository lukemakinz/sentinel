"""Frozen historical characterization of S101 asymmetric regime trend + OI."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.global_direction_oi import evaluate_regime_forward_returns
from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig,
    RegimeTrendOIConfig,
    asymmetric_global_regimes,
    weekly_regime_trend_oi_targets,
)
from .metrics_data import load_metrics, prefetch_metrics_archives
from .run_s100_global_regime_oi_swing import (
    _daily_open_interest,
    _daily_profit_factor,
    _direction_pnl,
    _target_counts,
)
from .run_s97_dual_horizon_trend import (
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import TrendPortfolioCosts, simulate_trend_portfolio


PROTOCOL_SHA256 = 'f6c6717dccfb9a26257cea0aff57bea6dc56d5ad9632dc51be93dd31f1f906e7'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
OI_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
PRICE_WARMUP, OI_WARMUP = '2022-04-04', '2024-01-01'
START, END = '2024-08-01', '2026-09-01'
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


def _render_report(result):
    lines = [
        '# S101 — asymmetric global regime + trend/OI execution', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Post-S100, discovery-contaminated diagnostic; not live approval.**', '',
        f'Target audit: `{result["target_counts"]}`.',
        f'Regime occupancy: `{result["regime_occupancy"]}`.',
        f'20-day BTC diagnostic: `{result["regime_forward_diagnostic"]}`.', '',
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
    lines.extend(['',
        f'- Stress PnL by direction: `{result["stress_direction_pnl"]}`.',
        f'- Volatility-risk neighbors: `{result["risk_neighbor_stress_pnl"]}`.',
        f'- Weekly phase offsets: `{result["phase_stress_pnl"]}`.',
        f'- Leave-one-traded-asset-out: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Bootstrap: `{result["stress_block_bootstrap"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'No S101 parameter was changed after its protocol was hashed.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s101_asymmetric_regime_trend_oi')
    parser.add_argument('--download-workers', type=int, default=16)
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Protocol hash mismatch: {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    daily, funding, manifest = {}, {}, {'prices': {}, 'metrics': {}}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], manifest['prices'][symbol] = load_interval_archives(
            symbol, PRICE_WARMUP, END, args.cache, interval='1d')
    prefetch_metrics_archives(
        OI_SYMBOLS, OI_WARMUP, END, args.cache, args.download_workers)
    open_interest = {}
    for symbol in OI_SYMBOLS:
        metrics, manifest['metrics'][symbol] = load_metrics(
            symbol, OI_WARMUP, END, args.cache,
            include_freshness=True, required_columns=('open_interest',))
        open_interest[symbol] = _daily_open_interest(metrics)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    regime_config = AsymmetricRegimeConfig()
    execution_config = RegimeTrendOIConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)
    targets = weekly_regime_trend_oi_targets(
        daily, funding, open_interest, regimes, START, END,
        execution_config, symbol_order=SYMBOLS)
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS}
    result = {
        'protocol_sha256': actual_hash,
        'regime_config': asdict(regime_config),
        'execution_config': asdict(execution_config),
        'target_counts': _target_counts(targets),
        'regime_occupancy': regimes.regime.value_counts(normalize=True).to_dict(),
        'regime_forward_diagnostic': evaluate_regime_forward_returns(
            regimes, daily['BTCUSDT']),
        'continuous_replays': {}, 'slices': {},
        'risk_neighbor_stress_pnl': {}, 'phase_stress_pnl': {},
        'leave_one_out_stress_pnl': {},
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

    for long_target, short_target in ((0.125, 0.0625), (0.175, 0.0875)):
        neighbor = replace(
            execution_config, long_vol_target_annual=long_target,
            short_vol_target_annual=short_target)
        neighbor_targets = weekly_regime_trend_oi_targets(
            daily, funding, open_interest, regimes, START, END,
            neighbor, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['risk_neighbor_stress_pnl'][f'{long_target}_{short_target}'] = (
            replay['summary']['net_pnl'])
    for offset in (2, 4):
        phase_start = str(pd.Timestamp(START) + pd.Timedelta(days=offset))
        phase_targets = weekly_regime_trend_oi_targets(
            daily, funding, open_interest, regimes, phase_start, END,
            execution_config, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, phase_targets, START, END, 500.0, COSTS['stress'])
        result['phase_stress_pnl'][str(offset)] = replay['summary']['net_pnl']
    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        kept_daily = {symbol: daily[symbol] for symbol in kept}
        kept_funding = {symbol: funding[symbol] for symbol in kept}
        kept_oi = {symbol: open_interest[symbol] for symbol in OI_SYMBOLS if symbol in kept}
        subset_targets = weekly_regime_trend_oi_targets(
            kept_daily, kept_funding, kept_oi, regimes, START, END,
            execution_config, symbol_order=kept)
        replay = simulate_trend_portfolio(
            {symbol: markets[symbol] for symbol in kept}, subset_targets,
            START, END, 500.0, COSTS['stress'])
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress, severe = result['continuous_replays']['stress'], result['continuous_replays']['severe']
    monthly, slices = result['stress_monthly_dispersion'], result['slices']
    direction = result['stress_direction_pnl']
    core_pass = (
        stress['net_pnl'] > 0 and stress['annualized_sharpe'] >= 0.50
        and stress['max_drawdown_pct'] <= 15.0 and stress['daily_profit_factor'] > 1.05
        and monthly['positive_month_share'] >= 0.40
        and result['target_counts']['short_decisions'] >= 5
        and direction['long_up_regime'] >= 0 and direction['short_down_regime'] >= 0
        and slices['development']['stress']['net_pnl'] > 0
        and slices['validation']['stress']['net_pnl'] > 0
        and slices['retrospective_evaluation']['stress']['net_pnl'] >= 0
        and severe['net_pnl'] > 0)
    robustness_pass = (
        all(value > 0 for value in result['risk_neighbor_stress_pnl'].values())
        and all(value > 0 for value in result['phase_stress_pnl'].values())
        and sum(value > 0 for value in result['leave_one_out_stress_pnl'].values()) >= 5
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
