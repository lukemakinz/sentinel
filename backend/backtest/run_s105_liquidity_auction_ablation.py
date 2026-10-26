"""Frozen S105 ablation: geometry, reset flow and liquidity target space."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.fvg_ifvg_decision_tree import (
    FVGIFVGConfig, generate_fvg_ifvg_signals,
)
from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, asymmetric_global_regimes,
)
from .metrics_data import load_metrics
from .run_s97_dual_horizon_trend import (
    _block_bootstrap, _monthly_dispersion, _slice_metrics,
)
from .run_s103_fvg_ifvg_decision_tree import (
    DAILY_WARMUP, END, INTRADAY_WARMUP, REGIME_SYMBOLS, START, TRADED,
    WINDOWS, _daily_pnl, _numeric_pf, _run, _trade_breakdown,
    _window_trade_count, _utc,
)
from .swing_data import load_interval_archives, regularize_interval


PROTOCOL_SHA256 = '334965e1c62494a1a32d6a62269ac8fea0243985159cbfe2eb751f9a174bb6cc'


def variants():
    geometry = replace(
        FVGIFVGConfig(), require_liquidity_sweep=True,
        max_zone_age_hours=24, minimum_stop_atr=2.0)
    return {
        'geometry': geometry,
        'geometry_reset': replace(
            geometry, require_liquidity_reset=True,
            min_micro_confluence=1),
        'geometry_target': replace(
            geometry, require_liquidity_target=True),
        'full': replace(
            geometry, require_liquidity_reset=True,
            require_liquidity_target=True, min_micro_confluence=1),
    }


def _signals(markets, metrics, regimes, config):
    generated, diagnostics = {}, {}
    for symbol in TRADED:
        generated[symbol], diagnostics[symbol] = generate_fvg_ifvg_signals(
            markets[symbol][0], metrics[symbol], regimes, symbol, config)
    return generated, diagnostics


def _load_data(cache):
    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    daily = {}
    for symbol in REGIME_SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)
    markets, metrics = {}, {}
    for symbol in TRADED:
        price, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, cache,
            interval='5m', allow_gaps=True)
        markets[symbol] = (
            regularize_interval(price, INTRADAY_WARMUP, END, minutes=5),
            funding,
        )
        metrics[symbol], manifest['metrics'][symbol] = load_metrics(
            symbol, INTRADAY_WARMUP, END, cache,
            include_freshness=True,
            required_columns=('open_interest', 'taker_buy_sell_vol_ratio'))
    return markets, metrics, regimes, regime_config, manifest


def _evaluate_variant(name, config, markets, metrics, regimes, output):
    signals, diagnostics = _signals(markets, metrics, regimes, config)
    record = {
        'config': asdict(config),
        'raw_signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'signal_diagnostics': diagnostics,
        'continuous_replays': {}, 'slices': {},
        'leave_one_out_stress_pnl': {},
    }
    replays = {}
    for scenario in ('base', 'stress', 'severe'):
        replay = _run(markets, signals, scenario)
        replays[scenario] = replay
        record['continuous_replays'][scenario] = replay['summary']
        daily = _daily_pnl(replay)
        for window, bounds in WINDOWS.items():
            row = _slice_metrics(daily, *bounds)
            row['trades'] = _window_trade_count(replay['trades'], *bounds)
            record['slices'].setdefault(window, {})[scenario] = row
        (output / f'{name}_{scenario}_trades.json.gz').write_bytes(gzip.compress(
            json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        print(name, scenario, replay['summary'], flush=True)
    stress = replays['stress']
    stress_daily = _daily_pnl(stress)
    record['stress_breakdown'] = _trade_breakdown(stress['trades'])
    record['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    record['stress_block_bootstrap'] = _block_bootstrap(stress_daily)
    pd.DataFrame({
        scenario: _daily_pnl(replay) for scenario, replay in replays.items()
    }).to_csv(output / f'{name}_daily_pnl.csv', index_label='timestamp')
    for excluded in TRADED:
        kept = tuple(symbol for symbol in TRADED if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        record['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress_summary = record['continuous_replays']['stress']
    severe_summary = record['continuous_replays']['severe']
    validation = record['slices']['validation']['stress']
    breakdown = record['stress_breakdown']
    core = (
        stress_summary['trades'] >= 12
        and stress_summary['net_pnl'] > 0
        and _numeric_pf(stress_summary) > 1.05
        and stress_summary['max_drawdown_pct'] <= 10
        and validation['trades'] >= 4 and validation['net_pnl'] > 0
        and severe_summary['net_pnl'] > 0
        and stress_summary['represented_symbols'] >= 2
        and breakdown['LONG']['net_pnl'] >= 0
        and breakdown['SHORT']['net_pnl'] >= 0)
    robust = (
        sum(value > 0 for value in
            record['leave_one_out_stress_pnl'].values()) >= 2
        and record['stress_block_bootstrap']['p10_terminal_pnl'] > 0)
    record['gate_components'] = {'core_pass': bool(core), 'robustness_pass': bool(robust)}
    record['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core and robust else 'REJECTED_AT_HISTORICAL_GATE')
    return record


def _neighbor(markets, metrics, regimes, config):
    signals, _ = _signals(markets, metrics, regimes, config)
    summary = _run(markets, signals, 'stress')['summary']
    return {
        'signals': sum(len(rows) for rows in signals.values()),
        'trades': summary['trades'], 'net_pnl': summary['net_pnl'],
        'profit_factor': summary['profit_factor'],
        'max_drawdown_pct': summary['max_drawdown_pct'],
    }


def _report(result):
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S105 — liquidity auction ablation', '',
        f'Frozen protocol: `{result["protocol_sha256"]}`.', '',
        '**Post-S104, selection-contaminated research. Live remains disabled.**', '',
        '| Variant | Costs | Trades | WR | PF | PnL | $/month | DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|',
    ]
    for name, record in result['variants'].items():
        for scenario, row in record['continuous_replays'].items():
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | '
                f'{row["win_rate_pct"]:.1f}% | {row["profit_factor"]} | '
                f'${row["net_pnl"]:.2f} | '
                f'${row["net_pnl"] / days * 30.4375:.2f} | '
                f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', '## Stress slices', '',
        '| Variant | Development | Validation | Retrospective |',
        '|---|---:|---:|---:|'])
    for name, record in result['variants'].items():
        lines.append(
            f'| {name} | '
            f'${record["slices"]["development"]["stress"]["net_pnl"]:.2f} | '
            f'${record["slices"]["validation"]["stress"]["net_pnl"]:.2f} | '
            f'${record["slices"]["retrospective_evaluation"]["stress"]["net_pnl"]:.2f} |')
    lines.extend(['', '## Frozen diagnostics', ''])
    for name, record in result['variants'].items():
        lines.extend([
            f'### {name}', '',
            f'- Signals: `{record["raw_signals"]}`.',
            f'- Stress attribution: `{record["stress_breakdown"]}`.',
            f'- Leave-one-out: `{record["leave_one_out_stress_pnl"]}`.',
            f'- Bootstrap: `{record["stress_block_bootstrap"]}`.',
            f'- Decision: **{record["decision"]}**.', '',
        ])
    lines.extend([
        f'- Geometry stop neighbors: `{result["geometry_stop_neighbors"]}`.',
        f'- Geometry age neighbors: `{result["geometry_age_neighbors"]}`.', '',
        f'**Overall decision: {result["decision"]}.**', '',
        'No historical pass is live approval; it can only start a new prospective paper clock.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output', default='docs/research/s105_liquidity_auction_ablation')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    actual_hash = sha256((output / 'protocol.json').read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError('Frozen S105 protocol hash mismatch')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    markets, metrics, regimes, regime_config, manifest = _load_data(args.cache)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    result = {
        'protocol_sha256': actual_hash,
        'regime_config': asdict(regime_config),
        'variants': {}, 'geometry_stop_neighbors': {},
        'geometry_age_neighbors': {},
    }
    frozen_variants = variants()
    for name, config in frozen_variants.items():
        result['variants'][name] = _evaluate_variant(
            name, config, markets, metrics, regimes, output)

    geometry = frozen_variants['geometry']
    for minimum in (1.75, 2.25):
        result['geometry_stop_neighbors'][str(minimum)] = _neighbor(
            markets, metrics, regimes,
            replace(geometry, minimum_stop_atr=minimum))
    for hours in (12, 36):
        result['geometry_age_neighbors'][str(hours)] = _neighbor(
            markets, metrics, regimes,
            replace(geometry, max_zone_age_hours=hours))

    passed = [name for name, row in result['variants'].items()
              if row['decision'].startswith('HISTORICAL_GATE_PASSED')]
    result['passed_variants'] = passed
    result['decision'] = (
        'START_PROSPECTIVE_PAPER_FORWARD_ONLY'
        if passed else 'ALL_VARIANTS_REJECTED_AT_HISTORICAL_GATE')
    result['live_enabled'] = False
    if passed:
        result['paper_forward'] = {
            't0': '2026-10-21T00:00:00Z',
            'minimum_days': 180, 'minimum_fills': 30,
            'variants': passed, 'no_early_promotion': True,
        }
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], passed, flush=True)


if __name__ == '__main__':
    main()
