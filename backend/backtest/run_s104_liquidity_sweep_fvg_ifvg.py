"""S104: isolate liquidity-sweep-qualified stop placement in S103."""
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


PROTOCOL_SHA256 = '922478096156e9ecdded970cffc629f57839a50e96899cdaab40762fcdf744ee'


def _signals(markets, metrics, regimes, config):
    generated, diagnostics = {}, {}
    for symbol in TRADED:
        generated[symbol], diagnostics[symbol] = generate_fvg_ifvg_signals(
            markets[symbol][0], metrics[symbol], regimes, symbol, config)
    return generated, diagnostics


def _report(result):
    stress = result['continuous_replays']['stress']
    baseline = result['s103_reference_stress']
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S104 — liquidity-sweep-anchored FVG/IFVG', '',
        f'Frozen protocol: `{result["protocol_sha256"]}`.', '',
        '**Only the sweep qualification and stop anchor changed from S103.**',
        'All history is contaminated; live remains disabled.', '',
        '| Replay | Trades | WR | PF | PnL | $/month | DD |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for scenario, row in result['continuous_replays'].items():
        lines.append(
            f'| S104 {scenario} | {row["trades"]} | {row["win_rate_pct"]:.1f}% | '
            f'{row["profit_factor"]} | ${row["net_pnl"]:.2f} | '
            f'${row["net_pnl"] / days * 30.4375:.2f} | '
            f'{row["max_drawdown_pct"]:.2f}% |')
    lines.append(
        f'| S103 stress reference | {baseline["trades"]} | '
        f'{baseline["win_rate_pct"]:.1f}% | {baseline["profit_factor"]} | '
        f'${baseline["net_pnl"]:.2f} | '
        f'${baseline["net_pnl"] / days * 30.4375:.2f} | '
        f'{baseline["max_drawdown_pct"]:.2f}% |')
    lines.extend(['',
        '| Period | Costs | Trades | PnL | $/month | DD | Sharpe |',
        '|---|---|---:|---:|---:|---:|---:|',
    ])
    for period, scenarios in result['slices'].items():
        period_days = (_utc(WINDOWS[period][1]) - _utc(WINDOWS[period][0])).days
        for scenario, row in scenarios.items():
            lines.append(
                f'| {period} | {scenario} | {row["trades"]} | '
                f'${row["net_pnl"]:.2f} | '
                f'${row["net_pnl"] / period_days * 30.4375:.2f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["annualized_sharpe"]:.2f} |')
    lines.extend(['', '## Diagnostics', '',
        f'- Stress route/direction: `{result["stress_breakdown"]}`.',
        f'- Raw candidates: `{result["raw_signals"]}`.',
        f'- State machine: `{result["signal_diagnostics"]}`.',
        f'- Lookback neighbors: `{result["lookback_neighbor_stress"]}`.',
        f'- Stop-buffer neighbors: `{result["buffer_neighbor_stress"]}`.',
        f'- Leave-one-out: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Bootstrap: `{result["stress_block_bootstrap"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        f'S104 stress average on $500: '
        f'**${stress["net_pnl"] / days * 30.4375:.2f}/month**. '
        'This is a historical simulation, not a forecast.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output', default='docs/research/s104_liquidity_sweep_fvg_ifvg')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError('Frozen S104 protocol hash mismatch')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    daily, manifest = {}, {'daily': {}, 'intraday': {}, 'metrics': {}}
    for symbol in REGIME_SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, args.cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    markets, metrics = {}, {}
    for symbol in TRADED:
        price, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, args.cache,
            interval='5m', allow_gaps=True)
        price = regularize_interval(
            price, INTRADAY_WARMUP, END, minutes=5)
        markets[symbol] = price, funding
        metrics[symbol], manifest['metrics'][symbol] = load_metrics(
            symbol, INTRADAY_WARMUP, END, args.cache,
            include_freshness=True,
            required_columns=('open_interest', 'taker_buy_sell_vol_ratio'))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    config = replace(FVGIFVGConfig(), require_liquidity_sweep=True)
    signals, diagnostics = _signals(markets, metrics, regimes, config)
    result = {
        'protocol_sha256': actual_hash,
        'config': asdict(config),
        'regime_config': asdict(regime_config),
        'raw_signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'signal_diagnostics': diagnostics,
        'continuous_replays': {}, 'slices': {},
        'lookback_neighbor_stress': {}, 'buffer_neighbor_stress': {},
        'leave_one_out_stress_pnl': {},
    }
    baseline_path = output.parent / 's103_fvg_ifvg_decision_tree' / 'summary.json'
    result['s103_reference_stress'] = json.loads(
        baseline_path.read_text())['continuous_replays']['stress']

    replays = {}
    for scenario in ('base', 'stress', 'severe'):
        replay = _run(markets, signals, scenario)
        replays[scenario] = replay
        result['continuous_replays'][scenario] = replay['summary']
        daily_pnl = _daily_pnl(replay)
        for window, bounds in WINDOWS.items():
            row = _slice_metrics(daily_pnl, *bounds)
            row['trades'] = _window_trade_count(replay['trades'], *bounds)
            result['slices'].setdefault(window, {})[scenario] = row
        (output / f'{scenario}_trades.json.gz').write_bytes(gzip.compress(
            json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        print(scenario, replay['summary'], flush=True)

    stress = replays['stress']
    stress_daily = _daily_pnl(stress)
    result['stress_breakdown'] = _trade_breakdown(stress['trades'])
    result['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    result['stress_block_bootstrap'] = _block_bootstrap(stress_daily)
    pd.DataFrame({
        scenario: _daily_pnl(replay) for scenario, replay in replays.items()
    }).to_csv(output / 'daily_pnl.csv', index_label='timestamp')

    for lookback in (12, 32):
        neighbor = replace(config, liquidity_lookback_bars=lookback)
        neighbor_signals, _ = _signals(markets, metrics, regimes, neighbor)
        summary = _run(markets, neighbor_signals, 'stress')['summary']
        result['lookback_neighbor_stress'][str(lookback)] = {
            'signals': sum(map(len, neighbor_signals.values())),
            'trades': summary['trades'], 'net_pnl': summary['net_pnl'],
            'profit_factor': summary['profit_factor'],
        }
    for buffer in (0.10, 0.20):
        neighbor = replace(config, stop_buffer_atr=buffer)
        neighbor_signals, _ = _signals(markets, metrics, regimes, neighbor)
        summary = _run(markets, neighbor_signals, 'stress')['summary']
        result['buffer_neighbor_stress'][str(buffer)] = {
            'signals': sum(map(len, neighbor_signals.values())),
            'trades': summary['trades'], 'net_pnl': summary['net_pnl'],
            'profit_factor': summary['profit_factor'],
        }
    for excluded in TRADED:
        kept = tuple(symbol for symbol in TRADED if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress_summary = result['continuous_replays']['stress']
    severe_summary = result['continuous_replays']['severe']
    validation = result['slices']['validation']['stress']
    breakdown = result['stress_breakdown']
    core_pass = (
        stress_summary['trades'] >= 20
        and stress_summary['net_pnl'] > 0
        and _numeric_pf(stress_summary) > 1.05
        and stress_summary['max_drawdown_pct'] <= 10
        and validation['trades'] >= 6 and validation['net_pnl'] > 0
        and breakdown['DEFENSE']['trades'] >= 3
        and breakdown['IFVG']['trades'] >= 3
        and breakdown['LONG']['trades'] > 0
        and breakdown['SHORT']['trades'] > 0
        and breakdown['LONG']['net_pnl'] >= 0
        and breakdown['SHORT']['net_pnl'] >= 0
        and stress_summary['represented_symbols'] >= 2)
    robustness_pass = (
        severe_summary['net_pnl'] > 0
        and sum(value > 0 for value in
                result['leave_one_out_stress_pnl'].values()) >= 2
        and result['stress_block_bootstrap']['p10_terminal_pnl'] > 0)
    result['gate_components'] = {
        'core_pass': bool(core_pass),
        'robustness_pass': bool(robustness_pass),
    }
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core_pass and robustness_pass else 'REJECTED_AT_HISTORICAL_GATE')
    result['live_enabled'] = False
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
