"""Frozen S103 replay: FVG defense versus IFVG inversion decision tree."""
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
from .swing_data import load_interval_archives, regularize_interval
from .swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


PROTOCOL_SHA256 = 'eeb17ddc8daad4dcd1a83acf42a34f503388b7a90f9d84f6819d0b4cd51aca2a'
TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
REGIME_SYMBOLS = (
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT',
)
DAILY_WARMUP = '2024-01-01'
INTRADAY_WARMUP = '2025-01-01'
START, END = '2025-05-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-01-01'),
    'retrospective_evaluation': ('2026-01-01', END),
}
COSTS = {
    'base': (5.0, 2.0),
    'stress': (8.0, 5.0),
    'severe': (10.0, 10.0),
}


def _utc(value):
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _execution(scenario: str) -> SwingExecutionConfig:
    fee, slippage = COSTS[scenario]
    return SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=fee, slippage_bps=slippage,
        leverage=5.0, risk_fraction=0.002, fixed_risk_usd=0.50,
        max_notional_equity=0.75, max_margin_fraction=0.15,
        min_stop_atr=0.50, max_stop_atr=4.0,
        max_hold_days=1, daily_loss_fraction=0.006,
        weekly_loss_fraction=0.018,
    )


def _run(markets, signals, scenario, symbols=TRADED):
    selected = tuple(symbols)
    return execute_swing_portfolio(
        {symbol: markets[symbol] for symbol in selected},
        {symbol: signals[symbol] for symbol in selected},
        {symbol: [] for symbol in selected},
        {symbol: pd.DataFrame() for symbol in selected},
        _execution(scenario), START, END, initial_capital=500.0,
        symbol_priority=selected,
    )


def _daily_pnl(replay) -> pd.Series:
    equity = pd.Series(replay['daily_equity'], dtype=float)
    equity.index = pd.to_datetime(equity.index, utc=True)
    equity = equity.sort_index()
    pnl = equity.diff()
    if len(pnl):
        pnl.iloc[0] = equity.iloc[0] - 500.0
    return pnl


def _numeric_pf(summary) -> float:
    value = summary['profit_factor']
    return float('inf') if value == 'Infinity' else float(value or 0.0)


def _trade_breakdown(trades) -> dict:
    groups = {
        'DEFENSE': [trade for trade in trades if trade['setup'].endswith('defense')],
        'IFVG': [trade for trade in trades if trade['setup'].endswith('ifvg')],
        'LONG': [trade for trade in trades if trade['side'] == 'LONG'],
        'SHORT': [trade for trade in trades if trade['side'] == 'SHORT'],
    }
    return {
        name: {
            'trades': len(rows),
            'net_pnl': float(sum(row['pnl'] for row in rows)),
            'wins': int(sum(row['pnl'] > 0 for row in rows)),
        }
        for name, rows in groups.items()
    }


def _window_trade_count(trades, start, end) -> int:
    start, end = _utc(start), _utc(end)
    return sum(start <= pd.Timestamp(row['opened_at']) < end for row in trades)


def _render_report(result: dict) -> str:
    stress = result['continuous_replays']['stress']
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S103 — FVG defense / IFVG inversion decision tree', '',
        f'Frozen protocol: `{result["protocol_sha256"]}`.', '',
        '**Historical research only. Live trading remains disabled.**', '',
        'A touch is never an entry. The model waits for closed-candle evidence '
        'of either defense or inversion, then enters at the next 5m open.', '',
        '| Full replay | Trades | WR | PF | PnL | Return | $/month | DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for scenario, row in result['continuous_replays'].items():
        lines.append(
            f'| {scenario} | {row["trades"]} | {row["win_rate_pct"]:.1f}% | '
            f'{row["profit_factor"]} | ${row["net_pnl"]:.2f} | '
            f'{row["return_pct"]:.2f}% | '
            f'${row["net_pnl"] / days * 30.4375:.2f} | '
            f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['',
        '| Period | Costs | Trades | PnL | Return on start NAV | $/month | DD | Sharpe |',
        '|---|---|---:|---:|---:|---:|---:|---:|',
    ])
    for period, scenarios in result['slices'].items():
        period_days = (_utc(WINDOWS[period][1]) - _utc(WINDOWS[period][0])).days
        for scenario, row in scenarios.items():
            lines.append(
                f'| {period} | {scenario} | {row["trades"]} | '
                f'${row["net_pnl"]:.2f} | {row["return_on_start_nav_pct"]:.2f}% | '
                f'${row["net_pnl"] / period_days * 30.4375:.2f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["annualized_sharpe"]:.2f} |')
    lines.extend(['', '## Attribution and robustness', '',
        f'- Stress route/direction breakdown: `{result["stress_breakdown"]}`.',
        f'- Raw state-machine diagnostics: `{result["signal_diagnostics"]}`.',
        f'- Leave-one-symbol-out stress PnL: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Micro-confluence neighbors stress PnL: '
        f'`{result["micro_score_neighbor_stress_pnl"]}`.',
        f'- Target neighbors stress PnL: `{result["target_neighbor_stress_pnl"]}`.',
        f'- 28-day bootstrap: `{result["stress_block_bootstrap"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        f'Stress historical average on $500: '
        f'**${stress["net_pnl"] / days * 30.4375:.2f}/month**. '
        'This is a replay estimate, not a forecast or guarantee.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output', default='docs/research/s103_fvg_ifvg_decision_tree')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(
            f'Protocol changed after freeze: {actual_hash} != {PROTOCOL_SHA256}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    daily = {}
    for symbol in REGIME_SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, args.cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    markets, metrics, data_quality = {}, {}, {}
    for symbol in TRADED:
        prices, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, args.cache,
            interval='5m', allow_gaps=True)
        expected = pd.date_range(
            INTRADAY_WARMUP, END, freq='5min', inclusive='left', tz='UTC')
        missing = expected.difference(prices.index)
        prices = regularize_interval(
            prices, INTRADAY_WARMUP, END, minutes=5)
        markets[symbol] = prices, funding
        metrics[symbol], manifest['metrics'][symbol] = load_metrics(
            symbol, INTRADAY_WARMUP, END, args.cache,
            include_freshness=True,
            required_columns=(
                'open_interest', 'taker_buy_sell_vol_ratio'))
        data_quality[symbol] = {
            'expected_5m_bars': len(expected),
            'observed_5m_bars': len(expected) - len(missing),
            'mtm_only_synthetic_bars': len(missing),
            'first_missing': [str(timestamp) for timestamp in missing[:20]],
        }
        print(symbol, 'data ready;', len(missing), 'synthetic MTM bars', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(
        json.dumps(data_quality, indent=2) + '\n')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')

    strategy = FVGIFVGConfig()
    signals, diagnostics = {}, {}
    for symbol in TRADED:
        signals[symbol], diagnostics[symbol] = generate_fvg_ifvg_signals(
            markets[symbol][0], metrics[symbol], regimes, symbol, strategy)
        print(symbol, len(signals[symbol]), 'deduplicated signals', flush=True)

    result = {
        'protocol_sha256': actual_hash,
        'strategy_config': asdict(strategy),
        'regime_config': asdict(regime_config),
        'signal_diagnostics': diagnostics,
        'raw_signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'continuous_replays': {}, 'slices': {},
        'leave_one_out_stress_pnl': {},
        'micro_score_neighbor_stress_pnl': {},
        'target_neighbor_stress_pnl': {},
    }
    replays = {}
    for scenario in COSTS:
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

    for excluded in TRADED:
        kept = tuple(symbol for symbol in TRADED if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    for threshold in (1, 3):
        neighbor = replace(strategy, min_micro_confluence=threshold)
        neighbor_signals = {
            symbol: generate_fvg_ifvg_signals(
                markets[symbol][0], metrics[symbol], regimes, symbol, neighbor)[0]
            for symbol in TRADED
        }
        replay = _run(markets, neighbor_signals, 'stress')
        result['micro_score_neighbor_stress_pnl'][str(threshold)] = (
            replay['summary']['net_pnl'])

    for target_r in (2.0, 3.0):
        neighbor_signals = {
            symbol: [{**row, 'target_r': target_r} for row in rows]
            for symbol, rows in signals.items()
        }
        replay = _run(markets, neighbor_signals, 'stress')
        result['target_neighbor_stress_pnl'][str(target_r)] = (
            replay['summary']['net_pnl'])

    stress_summary = result['continuous_replays']['stress']
    severe_summary = result['continuous_replays']['severe']
    validation = result['slices']['validation']['stress']
    breakdown = result['stress_breakdown']
    core_pass = (
        stress_summary['trades'] >= 30
        and stress_summary['net_pnl'] > 0
        and _numeric_pf(stress_summary) > 1.05
        and stress_summary['max_drawdown_pct'] <= 10.0
        and validation['net_pnl'] > 0 and validation['trades'] >= 8
        and breakdown['DEFENSE']['trades'] > 0
        and breakdown['IFVG']['trades'] > 0
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
    if core_pass and robustness_pass:
        result['paper_forward'] = {
            't0': '2026-10-20T00:00:00Z',
            'minimum_calendar_days': 180,
            'minimum_trades': 30,
            'no_early_live_promotion': True,
        }
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
