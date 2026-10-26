"""Full selected-history replay for S102 ETH-only short regime router."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.global_direction_oi import evaluate_regime_forward_returns
from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, RegimeTrendOIConfig,
    asymmetric_global_regimes, weekly_regime_trend_oi_targets,
)
from .metrics_data import load_metrics
from .run_s100_global_regime_oi_swing import (
    _daily_open_interest, _daily_profit_factor, _direction_pnl, _target_counts,
)
from .run_s101_asymmetric_regime_trend_oi import (
    COSTS, END, OI_SYMBOLS, OI_WARMUP, PRICE_WARMUP, SLICES, START, SYMBOLS,
)
from .run_s97_dual_horizon_trend import (
    _block_bootstrap, _monthly_dispersion, _slice_metrics,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import simulate_trend_portfolio


PROTOCOL_SHA256 = 'e97a9e5b495f52097215414c55ba0e0fd67c407f61f2ba026213e1e2e8e23094'
SHORT_SYMBOLS = ('ETHUSDT',)


def _make_targets(daily, funding, oi, regimes, start, config):
    return weekly_regime_trend_oi_targets(
        daily, funding, oi, regimes, start, END, config,
        symbol_order=SYMBOLS, short_symbols=SHORT_SYMBOLS)


def _render_report(result):
    stress = result['continuous_replays']['stress']
    days = (pd.Timestamp(END) - pd.Timestamp(START)).days
    lines = [
        '# S102 — ETH-only short regime router', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Selected after S101 ablation: positive history can authorize paper-forward only.**', '',
        f'Target audit: `{result["target_counts"]}`.',
        f'Global regime diagnostic: `{result["regime_forward_diagnostic"]}`.', '',
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
        f'- Stress average: **${stress["net_pnl"] / days * 30.4375:.2f}/month** '
        f'on the selected ${stress["initial_capital"]:.0f} history.',
        f'- Stress PnL by direction: `{result["stress_direction_pnl"]}`.',
        f'- Risk neighbors: `{result["risk_neighbor_stress_pnl"]}`.',
        f'- OI threshold neighbors: `{result["oi_threshold_neighbor_stress_pnl"]}`.',
        f'- Weekly phase offsets: `{result["phase_stress_pnl"]}`.',
        f'- Bootstrap: `{result["stress_block_bootstrap"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'Live remains disabled. The prospective clock starts on 2026-10-19.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s102_eth_short_regime_router')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Protocol hash mismatch: {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    daily, funding = {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], _ = load_interval_archives(
            symbol, PRICE_WARMUP, END, args.cache, interval='1d')
    open_interest = {}
    for symbol in OI_SYMBOLS:
        metrics, _ = load_metrics(
            symbol, OI_WARMUP, END, args.cache,
            include_freshness=True, required_columns=('open_interest',))
        open_interest[symbol] = _daily_open_interest(metrics)
    regime_config = AsymmetricRegimeConfig()
    config = RegimeTrendOIConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)
    targets = _make_targets(daily, funding, open_interest, regimes, START, config)
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS}

    result = {
        'protocol_sha256': actual_hash, 'regime_config': asdict(regime_config),
        'execution_config': asdict(config), 'short_symbols': SHORT_SYMBOLS,
        'target_counts': _target_counts(targets),
        'regime_forward_diagnostic': evaluate_regime_forward_returns(
            regimes, daily['BTCUSDT']),
        'continuous_replays': {}, 'slices': {},
        'risk_neighbor_stress_pnl': {},
        'oi_threshold_neighbor_stress_pnl': {}, 'phase_stress_pnl': {},
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
            config, long_vol_target_annual=long_target,
            short_vol_target_annual=short_target)
        neighbor_targets = _make_targets(
            daily, funding, open_interest, regimes, START, neighbor)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['risk_neighbor_stress_pnl'][f'{long_target}_{short_target}'] = (
            replay['summary']['net_pnl'])
    for threshold in (0.0, 0.10):
        neighbor = replace(config, minimum_short_oi_oscillator_pct=threshold)
        neighbor_targets = _make_targets(
            daily, funding, open_interest, regimes, START, neighbor)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['oi_threshold_neighbor_stress_pnl'][str(threshold)] = (
            replay['summary']['net_pnl'])
    for offset in (2, 4):
        phase_start = str(pd.Timestamp(START) + pd.Timedelta(days=offset))
        phase_targets = _make_targets(
            daily, funding, open_interest, regimes, phase_start, config)
        replay = simulate_trend_portfolio(
            markets, phase_targets, START, END, 500.0, COSTS['stress'])
        result['phase_stress_pnl'][str(offset)] = replay['summary']['net_pnl']

    historical_positive = (
        all(row['net_pnl'] > 0 for row in result['continuous_replays'].values())
        and result['stress_direction_pnl']['short_down_regime'] > 0
        and result['target_counts']['short_decisions'] >= 15)
    result['decision'] = (
        'HISTORICAL_POSITIVE_SELECTED_PAPER_CHALLENGER'
        if historical_positive else 'REJECTED_BEFORE_PAPER_FORWARD')
    result['paper_forward'] = {
        't0': '2026-10-19', 'minimum_days': 180,
        'minimum_weekly_decisions': 26, 'live_enabled': False,
    }
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    (output / 'paper_forward_protocol.json').write_text(json.dumps({
        'strategy_id': 'S102_ETH_SHORT_REGIME_ROUTER',
        'frozen_protocol_sha256': actual_hash,
        't0': '2026-10-19T00:00:00Z', 'minimum_calendar_days': 180,
        'minimum_weekly_decisions': 26,
        'promotion': 'No live promotion without a fresh post-T0 decision.',
        'live_enabled': False,
    }, indent=2) + '\n')
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
