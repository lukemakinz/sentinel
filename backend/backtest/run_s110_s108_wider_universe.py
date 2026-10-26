"""Frozen S110 scalability replay of the unchanged S108 strategy."""
import argparse
from concurrent.futures import ThreadPoolExecutor
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
from .metrics_data import load_metrics, prefetch_metrics_archives
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
    WINDOWS,
    _breakdown,
    _run,
    _utc,
)
from .run_s97_dual_horizon_trend import (
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import _archive, load_interval_archives, regularize_interval


PROTOCOL_SHA256 = '2dd89884ef61758e5876d746ae6e12379dc4e0601e95caf02b1550c334bd63f7'
ORIGINAL = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
EXTENSION = ('ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT', 'DOTUSDT')
COMBINED = ORIGINAL + EXTENSION
UNIVERSES = {
    'original_control': ORIGINAL,
    'extension': EXTENSION,
    'combined': COMBINED,
}
CONTROL = {
    'stress_trades': 8,
    'stress_net_pnl': 1.5964011161114513,
    'severe_net_pnl': 1.142401644881943,
    'tolerance': 1e-9,
}


def _prefetch_monthly_archives(cache, workers):
    """Populate independent monthly inputs concurrently before parsing them."""
    daily_months = pd.period_range(
        pd.Timestamp(DAILY_WARMUP), pd.Timestamp(END) - pd.Timedelta(days=1), freq='M')
    intraday_months = pd.period_range(
        pd.Timestamp(INTRADAY_WARMUP), pd.Timestamp(END) - pd.Timedelta(days=1), freq='M')
    tasks = set()
    for symbol in ORIGINAL:
        for month in daily_months:
            tasks.add((symbol, str(month), 'klines', cache, '1d'))
            tasks.add((symbol, str(month), 'fundingRate', cache, '5m'))
    for symbol in COMBINED:
        for month in intraday_months:
            tasks.add((symbol, str(month), 'klines', cache, '5m'))
            tasks.add((symbol, str(month), 'fundingRate', cache, '5m'))

    def fetch(task):
        symbol, month, kind, cache_path, interval = task
        return _archive(symbol, month, kind, cache_path, interval)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(fetch, sorted(tasks)))
    return len(tasks)


def _universe_record(markets, signals, diagnostics, symbols, output, name):
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
        for slice_name, bounds in WINDOWS.items():
            row = _slice_metrics(daily_pnl, *bounds)
            row['trades'] = _window_trade_count(replay['trades'], *bounds)
            record['slices'].setdefault(slice_name, {})[scenario] = row
        artifact = output / f'{name}_{scenario}_trades.json.gz'
        artifact.write_bytes(gzip.compress(
            json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        print(name, scenario, replay['summary'], flush=True)
    stress_daily = _daily_pnl(replays['stress'])
    record['stress_direction'] = _breakdown(replays['stress']['trades'])
    record['stress_bootstrap'] = _block_bootstrap(stress_daily)
    record['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    return record, replays


def _historical_gate(result):
    original = result['universes']['original_control']
    extension = result['universes']['extension']
    combined = result['universes']['combined']
    original_stress = original['replays']['stress']
    original_severe = original['replays']['severe']
    extension_stress = extension['replays']['stress']
    extension_severe = extension['replays']['severe']
    extension_direction = extension['stress_direction']
    stress = combined['replays']['stress']
    severe = combined['replays']['severe']
    direction = combined['stress_direction']
    slices = {
        name: combined['slices'][name]['stress']['net_pnl'] for name in WINDOWS}
    tolerance = CONTROL['tolerance']
    checks = {
        'original_control_exact_regression': (
            original_stress['trades'] == CONTROL['stress_trades']
            and abs(original_stress['net_pnl'] - CONTROL['stress_net_pnl']) <= tolerance
            and abs(original_severe['net_pnl'] - CONTROL['severe_net_pnl']) <= tolerance),
        'extension_minimum_10_stress_fills': extension_stress['trades'] >= 10,
        'extension_stress_positive': extension_stress['net_pnl'] > 0,
        'extension_stress_pf_above_1_15': _numeric_pf(extension_stress) > 1.15,
        'extension_severe_positive': extension_severe['net_pnl'] > 0,
        'extension_at_least_three_longs_and_shorts': (
            extension_direction['LONG']['trades'] >= 3
            and extension_direction['SHORT']['trades'] >= 3),
        'extension_long_and_short_non_negative': (
            extension_direction['LONG']['net_pnl'] >= 0
            and extension_direction['SHORT']['net_pnl'] >= 0),
        'extension_at_least_three_symbols': extension_stress['represented_symbols'] >= 3,
        'extension_bootstrap_p10_positive': (
            extension['stress_bootstrap']['p10_terminal_pnl'] > 0),
        'combined_minimum_18_stress_fills': stress['trades'] >= 18,
        'combined_stress_improves_s108': stress['net_pnl'] > CONTROL['stress_net_pnl'],
        'combined_stress_pf_above_1_15': _numeric_pf(stress) > 1.15,
        'combined_stress_dd_at_most_5pct': stress['max_drawdown_pct'] <= 5.0,
        'combined_severe_improves_s108': severe['net_pnl'] > CONTROL['severe_net_pnl'],
        'combined_at_least_five_longs_and_shorts': (
            direction['LONG']['trades'] >= 5 and direction['SHORT']['trades'] >= 5),
        'combined_long_and_short_non_negative': (
            direction['LONG']['net_pnl'] >= 0 and direction['SHORT']['net_pnl'] >= 0),
        'combined_at_least_six_symbols': stress['represented_symbols'] >= 6,
        'eight_of_twelve_leave_one_out_positive': (
            sum(value > 0 for value in result['leave_one_out_stress_pnl'].values()) >= 8),
        'three_of_four_positive_stress_slices': sum(value > 0 for value in slices.values()) >= 3,
        'no_stress_slice_below_minus_1usd': min(slices.values()) >= -1.0,
        'at_least_35pct_positive_months': (
            combined['stress_monthly_dispersion']['positive_month_share'] >= 0.35),
        'combined_bootstrap_p10_positive': (
            combined['stress_bootstrap']['p10_terminal_pnl'] > 0),
    }
    return {'checks': checks, 'passed': all(checks.values()), 'stress_slice_pnl': slices}


def _render_report(result):
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S110 — S108 wider-universe scalability test', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Selection-contaminated historical diagnostic. Live remains disabled.**', '',
        'No signal, regime, risk or execution parameter from S108 was changed. '
        'Only six predeclared markets were added.', '',
        '| Universe | Costs | Signals | Trades | Long/short | PF | PnL | $/month | DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, record in result['universes'].items():
        signal_count = sum(record['signal_counts'].values())
        for scenario, row in record['replays'].items():
            if scenario == 'stress':
                breakdown = record['stress_direction']
                directions = f'{breakdown["LONG"]["trades"]}/{breakdown["SHORT"]["trades"]}'
            else:
                directions = '-'
            lines.append(
                f'| {name} | {scenario} | {signal_count} | {row["trades"]} | '
                f'{directions} | {row["profit_factor"]} | ${row["net_pnl"]:.2f} | '
                f'${row["net_pnl"] / days * 30.4375:.2f} | {row["max_drawdown_pct"]:.2f}% |')
    combined = result['universes']['combined']
    lines.extend(['', '## Combined stress slices', '',
                  '| Slice | Trades | PnL | $/month | DD |',
                  '|---|---:|---:|---:|---:|'])
    for name in WINDOWS:
        row = combined['slices'][name]['stress']
        slice_days = (_utc(WINDOWS[name][1]) - _utc(WINDOWS[name][0])).days
        lines.append(
            f'| {name} | {row["trades"]} | ${row["net_pnl"]:.2f} | '
            f'${row["net_pnl"] / max(1, slice_days) * 30.4375:.2f} | '
            f'{row["max_continuous_drawdown_pct"]:.2f}% |')
    failed = [name for name, passed in result['historical_gate']['checks'].items() if not passed]
    lines.extend([
        '', '## Frozen gate', '',
        f'- Original-control regression: `{result["control_regression"]}`.',
        f'- Stress direction by universe: `{result["stress_direction_by_universe"]}`.',
        f'- Combined leave-one-symbol-out PnL: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Combined stress bootstrap: `{combined["stress_bootstrap"]}`.',
        f'- Combined monthly dispersion: `{combined["stress_monthly_dispersion"]}`.',
        f'- Failed checks: `{failed}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'A historical pass could only start a fresh paper-forward clock. It cannot '
        'authorize live trading or guarantee profit.', '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s110_s108_wider_universe')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Frozen S110 protocol changed: {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    monthly_count = _prefetch_monthly_archives(args.cache, args.workers)
    print('prefetched', monthly_count, 'monthly archives', flush=True)
    daily = {}
    for symbol in ORIGINAL:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, args.cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    archive_count = prefetch_metrics_archives(
        COMBINED, INTRADAY_WARMUP, END, args.cache, workers=args.workers)
    print('prefetched', archive_count, 'metrics archives', flush=True)

    markets, metrics, data_quality = {}, {}, {}
    for symbol in COMBINED:
        prices, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, args.cache, interval='5m', allow_gaps=True)
        expected = pd.date_range(
            INTRADAY_WARMUP, END, freq='5min', inclusive='left', tz='UTC')
        missing = expected.difference(prices.index)
        prices = regularize_interval(prices, INTRADAY_WARMUP, END, minutes=5)
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
    for symbol in COMBINED:
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
    for name, symbols in UNIVERSES.items():
        record, _ = _universe_record(
            markets, signals, diagnostics, symbols, output, name)
        result['universes'][name] = record

    for excluded in COMBINED:
        kept = tuple(symbol for symbol in COMBINED if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    original = result['universes']['original_control']
    result['control_regression'] = {
        'stress_trades': original['replays']['stress']['trades'],
        'stress_net_pnl': original['replays']['stress']['net_pnl'],
        'severe_net_pnl': original['replays']['severe']['net_pnl'],
    }
    result['stress_direction_by_universe'] = {
        name: record['stress_direction'] for name, record in result['universes'].items()}
    result['historical_gate'] = _historical_gate(result)
    result['decision'] = (
        'START_PAPER_FORWARD_ONLY' if result['historical_gate']['passed']
        else 'REJECTED_AT_HISTORICAL_GATE')
    result['paper_forward'] = {
        'minimum_calendar_days': 180,
        'minimum_fills': 30,
        'requires_both_directions': True,
        'live_enabled': False,
    }

    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(json.dumps(data_quality, indent=2) + '\n')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
