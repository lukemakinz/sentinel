"""Frozen S111 cost-breakeven risk overlay for S108 signals."""
import argparse
from dataclasses import asdict, replace
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
    build_failed_auction_features,
    generate_failed_auction_signals_from_bars,
)
from .metrics_data import load_metrics
from .run_s103_fvg_ifvg_decision_tree import (
    _daily_pnl,
    _numeric_pf,
    _window_trade_count,
)
from .run_s108_failed_auction_sweep import (
    DAILY_WARMUP,
    END,
    INTRADAY_WARMUP,
    START,
    SYMBOLS,
    WINDOWS,
    _breakdown,
    _execution as s108_execution,
    _utc,
)
from .run_s97_dual_horizon_trend import (
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import load_interval_archives, regularize_interval
from .swing_portfolio import execute_swing_portfolio


PROTOCOL_SHA256 = 'ffebc088c600ff172f40869b3d1c214239ecc4876a3349c29fe462a1ac936ec6'
S108 = {
    'stress_trades': 8,
    'stress_net_pnl': 1.5964011161114513,
    'stress_profit_factor': 3.1331481102869208,
    'stress_max_drawdown_pct': 0.18329711843448893,
    'stress_bootstrap_p10': 0.23052250500251165,
    'severe_net_pnl': 1.142401644881943,
}


def _run(markets, signals, management, scenario, policy):
    config = s108_execution(scenario)
    config = replace(
        config,
        exit_policy=policy,
        breakeven_trigger_r=1.0,
    )
    active_management = (
        management if policy == 'delayed_cost_be'
        else {symbol: pd.DataFrame() for symbol in SYMBOLS})
    return execute_swing_portfolio(
        markets,
        signals,
        {symbol: [] for symbol in SYMBOLS},
        active_management,
        config,
        START,
        END,
        initial_capital=500.0,
        symbol_priority=SYMBOLS,
    )


def _record(replays):
    record = {'replays': {}, 'slices': {}}
    for scenario, replay in replays.items():
        record['replays'][scenario] = replay['summary']
        daily = _daily_pnl(replay)
        for name, bounds in WINDOWS.items():
            row = _slice_metrics(daily, *bounds)
            row['trades'] = _window_trade_count(replay['trades'], *bounds)
            record['slices'].setdefault(name, {})[scenario] = row
    stress_daily = _daily_pnl(replays['stress'])
    record['stress_direction'] = _breakdown(replays['stress']['trades'])
    record['stress_bootstrap'] = _block_bootstrap(stress_daily)
    record['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    return record


def _gate(result):
    control = result['policies']['initial_sl_only']
    candidate = result['policies']['delayed_cost_be_1r']
    control_stress = control['replays']['stress']
    control_severe = control['replays']['severe']
    stress = candidate['replays']['stress']
    severe = candidate['replays']['severe']
    directions = candidate['stress_direction']
    slices = {
        name: candidate['slices'][name]['stress']['net_pnl'] for name in WINDOWS}
    checks = {
        'nine_raw_s108_signals': result['raw_signal_count'] == 9,
        's108_control_exact_regression': (
            control_stress['trades'] == S108['stress_trades']
            and abs(control_stress['net_pnl'] - S108['stress_net_pnl']) <= 1e-9
            and abs(control_severe['net_pnl'] - S108['severe_net_pnl']) <= 1e-9),
        'minimum_18_stress_fills': stress['trades'] >= 18,
        'at_least_five_longs_and_shorts': (
            directions['LONG']['trades'] >= 5 and directions['SHORT']['trades'] >= 5),
        'stress_improves_by_at_least_0_25usd': (
            stress['net_pnl'] >= S108['stress_net_pnl'] + 0.25),
        'severe_improves_by_at_least_0_25usd': (
            severe['net_pnl'] >= S108['severe_net_pnl'] + 0.25),
        'stress_pf_improves': _numeric_pf(stress) > S108['stress_profit_factor'],
        'stress_dd_not_worse': (
            stress['max_drawdown_pct'] <= S108['stress_max_drawdown_pct']),
        'both_directions_non_negative': (
            directions['LONG']['net_pnl'] >= 0 and directions['SHORT']['net_pnl'] >= 0),
        'three_of_four_positive_stress_slices': sum(value > 0 for value in slices.values()) >= 3,
        'no_stress_slice_below_minus_0_50usd': min(slices.values()) >= -0.50,
        'bootstrap_p10_improves': (
            candidate['stress_bootstrap']['p10_terminal_pnl']
            > S108['stress_bootstrap_p10']),
    }
    return {'checks': checks, 'passed': all(checks.values()), 'stress_slice_pnl': slices}


def _report(result):
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S111 — S108 with close-confirmed 1R cost breakeven', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Post-S110, selection-contaminated diagnostic. Live remains disabled.**', '',
        'Entries, initial stops, targets and sizing are unchanged. The candidate '
        'moves the stop to a cost-covering breakeven only after a completed 15m '
        'close reaches +1R; the update applies to the next 5m candle.', '',
        '| Policy | Costs | Trades | Long/short | WR | PF | PnL | $/month | DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, record in result['policies'].items():
        for scenario, row in record['replays'].items():
            breakdown = record['stress_direction'] if scenario == 'stress' else None
            direction = (
                f'{breakdown["LONG"]["trades"]}/{breakdown["SHORT"]["trades"]}'
                if breakdown else '-')
            lines.append(
                f'| {name} | {scenario} | {row["trades"]} | {direction} | '
                f'{row["win_rate_pct"]:.1f}% | {row["profit_factor"]} | '
                f'${row["net_pnl"]:.2f} | ${row["net_pnl"] / days * 30.4375:.2f} | '
                f'{row["max_drawdown_pct"]:.3f}% |')
    candidate = result['policies']['delayed_cost_be_1r']
    failed = [name for name, passed in result['historical_gate']['checks'].items() if not passed]
    lines.extend([
        '', '## Candidate diagnostics', '',
        f'- Raw signals: `{result["raw_signal_count"]}`; setup IDs: `{result["raw_setup_ids"]}`.',
        f'- Stress directions: `{candidate["stress_direction"]}`.',
        f'- Stress slices: `{result["historical_gate"]["stress_slice_pnl"]}`.',
        f'- Stress bootstrap: `{candidate["stress_bootstrap"]}`.',
        f'- Stress stop updates: `{result["stress_stop_update_audit"]}`.',
        f'- Failed checks: `{failed}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'Historical improvement is not a profit guarantee and cannot authorize live trading.', '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s111_s108_cost_breakeven')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    actual_hash = sha256((output / 'protocol.json').read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Frozen S111 protocol changed: {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    daily = {}
    for symbol in SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, args.cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    markets, signals, management, diagnostics, data_quality = {}, {}, {}, {}, {}
    strategy = FailedAuctionConfig()
    for symbol in SYMBOLS:
        prices, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, args.cache, interval='5m', allow_gaps=True)
        expected = pd.date_range(
            INTRADAY_WARMUP, END, freq='5min', inclusive='left', tz='UTC')
        missing = expected.difference(prices.index)
        prices = regularize_interval(prices, INTRADAY_WARMUP, END, minutes=5)
        metrics, manifest['metrics'][symbol] = load_metrics(
            symbol, INTRADAY_WARMUP, END, args.cache,
            include_freshness=True,
            required_columns=('open_interest', 'taker_buy_sell_vol_ratio'))
        markets[symbol] = prices, funding
        bars = build_failed_auction_features(prices, metrics, funding, strategy)
        signals[symbol], diagnostics[symbol] = generate_failed_auction_signals_from_bars(
            bars, regimes, symbol, strategy)
        management[symbol] = bars[['high', 'low', 'close', 'atr']].copy()
        data_quality[symbol] = {
            'expected_5m_bars': len(expected),
            'observed_5m_bars': len(expected) - len(missing),
            'mtm_only_synthetic_bars': len(missing),
        }
        print(symbol, len(signals[symbol]), 'signals;', len(missing), 'synthetic bars', flush=True)

    raw_setup_ids = sorted(
        signal['setup_id'] for records in signals.values() for signal in records)
    result = {
        'protocol_sha256': actual_hash,
        'strategy_config': asdict(strategy),
        'regime_config': asdict(regime_config),
        'raw_signal_count': len(raw_setup_ids),
        'raw_setup_ids': raw_setup_ids,
        'signal_diagnostics': diagnostics,
        'policies': {},
        'live_enabled': False,
    }
    policy_replays = {}
    for name, policy in (
        ('initial_sl_only', 'initial_sl_only'),
        ('delayed_cost_be_1r', 'delayed_cost_be'),
    ):
        replays = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = _run(markets, signals, management, scenario, policy)
            replays[scenario] = replay
            artifact = output / f'{name}_{scenario}_trades.json.gz'
            artifact.write_bytes(gzip.compress(
                json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
            print(name, scenario, replay['summary'], flush=True)
        policy_replays[name] = replays
        result['policies'][name] = _record(replays)

    stress_trades = policy_replays['delayed_cost_be_1r']['stress']['trades']
    updates = [update for trade in stress_trades for update in trade['stop_updates']]
    result['stress_stop_update_audit'] = {
        'trades_with_updates': sum(bool(trade['stop_updates']) for trade in stress_trades),
        'updates': len(updates),
        'minimum_closed_bar_r': min(
            (update['closed_bar_r'] for update in updates), default=None),
        'reasons': sorted({reason for update in updates for reason in update['reasons']}),
    }
    result['historical_gate'] = _gate(result)
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
    (output / 'data_quality.json').write_text(json.dumps(data_quality, indent=2) + '\n')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
