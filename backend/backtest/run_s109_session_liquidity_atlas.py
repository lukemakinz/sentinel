"""Frozen S109 replay for named session/day/week liquidity anchors."""
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
from l1_filter.session_liquidity_atlas import (
    SessionLiquidityAtlasConfig,
    generate_session_atlas_signals,
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
    PRIMARY,
    PORTABILITY,
    START,
    SYMBOLS,
    UNIVERSES,
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
from .swing_data import load_interval_archives, regularize_interval


PROTOCOL_SHA256 = '8a54998c1e75db1fb2856cf29b41a3953dce99bb60bf547e2758bf2feaf849dd'
S108_STRESS_PNL = 1.5964011161114513
S108_SEVERE_PNL = 1.142401644881943


def _render_report(result: dict) -> str:
    days = (_utc(END) - _utc(START)).days
    lines = [
        '# S109 — session liquidity atlas', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Post-S108, selection-contaminated diagnostic. Live remains disabled.**', '',
        'S109 retains S108 flow, funding, stop, target and risk rules. It replaces '
        'the single rolling level with prior-day, prior-week and completed '
        '00:00–08:00 UTC Asia-session anchors, then waits up to 90 minutes for '
        'the same failed-auction confirmation.', '',
        '| Universe | Costs | Signals | Trades | WR | PF | PnL | $/month | DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for universe, record in result['universes'].items():
        signals = sum(record['signal_counts'].values())
        for scenario, row in record['replays'].items():
            lines.append(
                f'| {universe} | {scenario} | {signals} | {row["trades"]} | '
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
    failed = [name for name, value in result['historical_gate']['checks'].items()
              if not value]
    lines.extend([
        '', '## Attribution and frozen gate', '',
        f'- Combined stress direction: `{combined["stress_direction"]}`.',
        f'- Combined stress per symbol: `{combined["replays"]["stress"]["per_symbol"]}`.',
        f'- Leave-one-out: `{result["leave_one_out_stress_pnl"]}`.',
        f'- Monthly dispersion: `{combined["stress_monthly_dispersion"]}`.',
        f'- Bootstrap: `{combined["stress_bootstrap"]}`.',
        f'- S108 reference: stress `${S108_STRESS_PNL:.4f}`, severe '
        f'`${S108_SEVERE_PNL:.4f}`.',
        f'- Failed checks: `{failed}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'No historical pass can authorize live trading or guarantee profit.', '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s109_session_liquidity_atlas')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Frozen S109 protocol changed: {actual_hash}')
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

    atlas = SessionLiquidityAtlasConfig()
    strategy = atlas.failed_auction()
    signals, diagnostics = {}, {}
    for symbol in SYMBOLS:
        signals[symbol], diagnostics[symbol] = generate_session_atlas_signals(
            markets[symbol][0], metrics[symbol], markets[symbol][1],
            regimes, symbol, atlas)
        print(symbol, len(signals[symbol]), 'session-atlas signals', flush=True)

    result = {
        'protocol_sha256': actual_hash,
        'atlas_config': asdict(atlas),
        'strategy_config': asdict(strategy),
        'regime_config': asdict(regime_config),
        'universes': {},
        'leave_one_out_stress_pnl': {},
        'live_enabled': False,
    }
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
        result['universes'][universe] = record

    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        replay = _run(markets, signals, 'stress', kept)
        result['leave_one_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    combined = result['universes']['combined']
    stress = combined['replays']['stress']
    severe = combined['replays']['severe']
    directions = combined['stress_direction']
    slices = {
        name: combined['slices'][name]['stress']['net_pnl'] for name in WINDOWS}
    primary = result['universes']['primary']
    portability = result['universes']['portability']
    checks = {
        'combined_minimum_18_stress_fills': stress['trades'] >= 18,
        'stress_pnl_beats_s108': stress['net_pnl'] > S108_STRESS_PNL,
        'stress_pf_above_1_15': _numeric_pf(stress) > 1.15,
        'stress_dd_at_most_5pct': stress['max_drawdown_pct'] <= 5.0,
        'severe_pnl_beats_s108': severe['net_pnl'] > S108_SEVERE_PNL,
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
            sum(value > 0 for value in slices.values()) >= 3),
        'no_stress_slice_below_minus_1usd': min(slices.values()) >= -1.0,
        'positive_month_share_at_least_35pct': (
            combined['stress_monthly_dispersion']['positive_month_share'] >= 0.35),
        'bootstrap_p10_positive': (
            combined['stress_bootstrap']['p10_terminal_pnl'] > 0),
    }
    result['historical_gate'] = {
        'checks': checks,
        'passed': all(checks.values()),
        'stress_slice_pnl': slices,
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
