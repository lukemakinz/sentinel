"""Frozen S108 replay for strong-level failed-auction liquidity sweeps."""
import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig,
    asymmetric_global_regimes,
)
from l1_filter.liquidity_sweep_failed_auction import (
    FailedAuctionConfig,
    generate_failed_auction_signals,
)
from .metrics_data import load_metrics
from .run_s103_fvg_ifvg_decision_tree import (
    COSTS,
    _daily_pnl,
    _numeric_pf,
    _window_trade_count,
)
from .run_s97_dual_horizon_trend import (
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import load_interval_archives, regularize_interval
from .swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


PROTOCOL_SHA256 = 'be2455c8ee6bdd7012aa21dd88dbde6fa9205d94b2086474fe0101f9666c0932'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
PRIMARY = SYMBOLS[:3]
PORTABILITY = SYMBOLS[3:]
UNIVERSES = {'combined': SYMBOLS, 'primary': PRIMARY, 'portability': PORTABILITY}
DAILY_WARMUP = '2024-01-01'
INTRADAY_WARMUP = '2025-01-01'
START, END = '2025-05-01', '2026-10-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'former_validation_now_diagnostic': ('2025-10-01', '2026-01-01'),
    'retrospective': ('2026-01-01', '2026-09-01'),
    'opened_design_month': ('2026-09-01', END),
}


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _execution(scenario: str) -> SwingExecutionConfig:
    fee, slippage = COSTS[scenario]
    return SwingExecutionConfig(
        exit_policy='initial_sl_only',
        fee_bps=fee,
        slippage_bps=slippage,
        leverage=5.0,
        risk_fraction=0.002,
        fixed_risk_usd=0.50,
        max_notional_equity=0.75,
        max_margin_fraction=0.15,
        min_stop_atr=1.0,
        max_stop_atr=4.0,
        max_hold_days=1,
        daily_loss_fraction=0.006,
        weekly_loss_fraction=0.018,
    )


def _run(markets, signals, scenario: str, symbols) -> dict:
    selected = tuple(symbols)
    return execute_swing_portfolio(
        {symbol: markets[symbol] for symbol in selected},
        {symbol: signals[symbol] for symbol in selected},
        {symbol: [] for symbol in selected},
        {symbol: pd.DataFrame() for symbol in selected},
        _execution(scenario),
        START,
        END,
        initial_capital=500.0,
        symbol_priority=selected,
    )


def _breakdown(trades: list[dict]) -> dict:
    groups = {
        'LONG': [trade for trade in trades if trade['side'] == 'LONG'],
        'SHORT': [trade for trade in trades if trade['side'] == 'SHORT'],
    }
    return {
        name: {
            'trades': len(rows),
            'wins': sum(row['pnl'] > 0 for row in rows),
            'net_pnl': float(sum(row['pnl'] for row in rows)),
            'mean_r': (
                float(sum(row['r_multiple'] for row in rows) / len(rows))
                if rows else 0.0),
        }
        for name, rows in groups.items()
    }


def _render_report(result: dict) -> str:
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S108 — strong-level failed-auction liquidity sweep', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Selection-contaminated historical diagnostic. Live remains disabled.**', '',
        'A strong 15m level is swept under expanding OI and aggressive flow. '
        'The strategy waits for a later failed-auction break and enters at the '
        'next 5m open; the stop stays beyond the sweep extreme.', '',
        '| Universe | Costs | Signals | Trades | WR | PF | PnL | $/month | DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for universe, record in result['universes'].items():
        signal_count = sum(record['signal_counts'].values())
        for scenario, row in record['replays'].items():
            lines.append(
                f'| {universe} | {scenario} | {signal_count} | {row["trades"]} | '
                f'{row["win_rate_pct"]:.1f}% | {row["profit_factor"]} | '
                f'${row["net_pnl"]:.2f} | '
                f'${row["net_pnl"] / days * 30.4375:.2f} | '
                f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', '## Combined stress slices', '',
                  '| Slice | Trades | PnL | $/month | DD | Sharpe |',
                  '|---|---:|---:|---:|---:|---:|'])
    combined = result['universes']['combined']
    for name, scenarios in combined['slices'].items():
        row = scenarios['stress']
        slice_days = (_utc(WINDOWS[name][1]) - _utc(WINDOWS[name][0])).days
        lines.append(
            f'| {name} | {row["trades"]} | ${row["net_pnl"]:.2f} | '
            f'${row["net_pnl"] / max(1, slice_days) * 30.4375:.2f} | '
            f'{row["max_continuous_drawdown_pct"]:.2f}% | '
            f'{row["annualized_sharpe"]:.2f} |')
    failed = [name for name, passed in result['historical_gate']['checks'].items()
              if not passed]
    lines.extend([
        '', '## Attribution and frozen gate', '',
        f'- Combined stress direction: `{combined["stress_direction"]}`.',
        f'- Combined stress per symbol: `{combined["replays"]["stress"]["per_symbol"]}`.',
        f'- Leave-one-symbol-out stress PnL: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Combined stress bootstrap: `{combined["stress_bootstrap"]}`.',
        f'- Signal diagnostics: `{combined["signal_diagnostics"]}`.',
        f'- Failed gate checks: `{failed}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'A historical pass can only start a fresh paper-forward clock; it cannot '
        'authorize live trading or guarantee profit.', '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s108_failed_auction_sweep')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Frozen S108 protocol changed: {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    daily = {}
    for symbol in SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, args.cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    markets, metrics, data_quality = {}, {}, {}
    for symbol in SYMBOLS:
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
            required_columns=('open_interest', 'taker_buy_sell_vol_ratio'))
        data_quality[symbol] = {
            'expected_5m_bars': len(expected),
            'observed_5m_bars': len(expected) - len(missing),
            'mtm_only_synthetic_bars': len(missing),
            'first_missing': [str(timestamp) for timestamp in missing[:20]],
        }
        print(symbol, 'data ready;', len(missing), 'synthetic MTM bars', flush=True)

    strategy = FailedAuctionConfig()
    signals, diagnostics = {}, {}
    for symbol in SYMBOLS:
        signals[symbol], diagnostics[symbol] = generate_failed_auction_signals(
            markets[symbol][0], metrics[symbol], markets[symbol][1],
            regimes, symbol, strategy)
        print(symbol, len(signals[symbol]), 'failed-auction signals', flush=True)

    result = {
        'protocol_sha256': actual_hash,
        'strategy_config': asdict(strategy),
        'regime_config': asdict(regime_config),
        'regime_occupancy': {
            str(key): float(value)
            for key, value in regimes.regime.value_counts(normalize=True).items()},
        'universes': {},
        'leave_one_out_stress_pnl': {},
        'live_enabled': False,
    }
    universe_replays = {}
    for universe, symbols in UNIVERSES.items():
        record = {
            'symbols': symbols,
            'signal_counts': {symbol: len(signals[symbol]) for symbol in symbols},
            'signal_diagnostics': {symbol: diagnostics[symbol] for symbol in symbols},
            'replays': {},
            'slices': {},
        }
        replays = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = _run(markets, signals, scenario, symbols)
            replays[scenario] = replay
            record['replays'][scenario] = replay['summary']
            daily_pnl = _daily_pnl(replay)
            for name, bounds in WINDOWS.items():
                row = _slice_metrics(daily_pnl, *bounds)
                row['trades'] = _window_trade_count(replay['trades'], *bounds)
                record['slices'].setdefault(name, {})[scenario] = row
            artifact = output / f'{universe}_{scenario}_trades.json.gz'
            artifact.write_bytes(gzip.compress(
                json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
            print(universe, scenario, replay['summary'], flush=True)
        stress_daily = _daily_pnl(replays['stress'])
        record['stress_direction'] = _breakdown(replays['stress']['trades'])
        record['stress_bootstrap'] = _block_bootstrap(stress_daily)
        record['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
        universe_replays[universe] = replays
        result['universes'][universe] = record

    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    combined = result['universes']['combined']
    stress = combined['replays']['stress']
    severe = combined['replays']['severe']
    directions = combined['stress_direction']
    stress_slices = {
        name: combined['slices'][name]['stress']['net_pnl'] for name in WINDOWS}
    primary = result['universes']['primary']
    portability = result['universes']['portability']
    checks = {
        'combined_minimum_18_stress_fills': stress['trades'] >= 18,
        'combined_stress_positive': stress['net_pnl'] > 0,
        'combined_stress_pf_above_1_15': _numeric_pf(stress) > 1.15,
        'combined_stress_dd_at_most_5pct': stress['max_drawdown_pct'] <= 5.0,
        'combined_severe_positive': severe['net_pnl'] > 0,
        'at_least_five_longs_and_shorts': (
            directions['LONG']['trades'] >= 5 and directions['SHORT']['trades'] >= 5),
        'long_and_short_non_negative': (
            directions['LONG']['net_pnl'] >= 0 and directions['SHORT']['net_pnl'] >= 0),
        'at_least_three_symbols': stress['represented_symbols'] >= 3,
        'four_of_six_leave_one_out_positive': (
            sum(value > 0 for value in result['leave_one_out_stress_pnl'].values()) >= 4),
        'primary_and_portability_minimum_six_stress_fills': (
            primary['replays']['stress']['trades'] >= 6
            and portability['replays']['stress']['trades'] >= 6),
        'primary_and_portability_stress_non_negative': (
            primary['replays']['stress']['net_pnl'] >= 0
            and portability['replays']['stress']['net_pnl'] >= 0),
        'primary_and_portability_severe_non_negative': (
            primary['replays']['severe']['net_pnl'] >= 0
            and portability['replays']['severe']['net_pnl'] >= 0),
        'three_of_four_positive_stress_slices': (
            sum(value > 0 for value in stress_slices.values()) >= 3),
        'no_stress_slice_below_minus_1usd': min(stress_slices.values()) >= -1.0,
        'bootstrap_p10_positive': (
            combined['stress_bootstrap']['p10_terminal_pnl'] > 0),
    }
    result['historical_gate'] = {
        'checks': checks,
        'passed': all(checks.values()),
        'stress_slice_pnl': stress_slices,
    }
    result['decision'] = (
        'START_PAPER_FORWARD_ONLY' if result['historical_gate']['passed']
        else 'REJECTED_AT_HISTORICAL_GATE')
    result['paper_forward'] = {
        'minimum_calendar_days': 180,
        'minimum_fills': 24,
        'requires_both_directions': True,
        'live_enabled': False,
    }

    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(
        json.dumps(data_quality, indent=2) + '\n')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
