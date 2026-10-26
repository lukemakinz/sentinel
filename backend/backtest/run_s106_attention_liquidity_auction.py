"""Frozen S106 attention-sized liquidity-auction replay and portability check."""
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
from l1_filter.liquidity_auction_attention import (
    LiquidityAuctionAttentionConfig, apply_liquidity_auction_attention,
)
from .metrics_data import load_metrics, prefetch_metrics_archives
from .run_s97_dual_horizon_trend import _block_bootstrap, _slice_metrics
from .run_s103_fvg_ifvg_decision_tree import (
    COSTS, DAILY_WARMUP, INTRADAY_WARMUP, REGIME_SYMBOLS,
    _daily_pnl, _numeric_pf, _trade_breakdown, _window_trade_count,
)
from .swing_data import load_interval_archives, regularize_interval
from .swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


START, END = '2025-05-01', '2026-10-01'
PRIMARY = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
PORTABILITY = ('BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
UNIVERSES = {'primary': PRIMARY, 'portability': PORTABILITY}
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-01-01'),
    'retrospective': ('2026-01-01', '2026-09-01'),
    'opened_design_month': ('2026-09-01', '2026-10-01'),
}
PROTOCOL_SHA256 = '5496925187a86b1643411bafd1246b0deed3938a9cd2e2eff2350addc74e1fa1'


def frozen_variants():
    common = replace(
        FVGIFVGConfig(),
        max_zone_age_hours=24,
        min_micro_confluence=0,
        require_liquidity_sweep=True,
        minimum_stop_atr=2.0,
    )
    return {
        'fixed_control': common,
        'external_target': replace(
            common,
            require_liquidity_target=True,
            target_liquidity_lookback_bars=96,
            minimum_liquidity_target_r=1.5,
            maximum_liquidity_target_r=2.5,
        ),
    }


def _load_data(cache):
    manifest = {'daily': {}, 'intraday': {}, 'metrics': {}}
    daily = {}
    for symbol in REGIME_SYMBOLS:
        daily[symbol], _, manifest['daily'][symbol] = load_interval_archives(
            symbol, DAILY_WARMUP, END, cache, interval='1d')
    regime_config = AsymmetricRegimeConfig()
    regimes = asymmetric_global_regimes(daily, START, END, regime_config)

    prefetch_metrics_archives(
        (*PRIMARY, *PORTABILITY), INTRADAY_WARMUP, END, cache, workers=16)
    markets, metrics = {}, {}
    for symbol in (*PRIMARY, *PORTABILITY):
        prices, funding, manifest['intraday'][symbol] = load_interval_archives(
            symbol, INTRADAY_WARMUP, END, cache,
            interval='5m', allow_gaps=True)
        markets[symbol] = (
            regularize_interval(prices, INTRADAY_WARMUP, END, minutes=5),
            funding,
        )
        metrics[symbol], manifest['metrics'][symbol] = load_metrics(
            symbol, INTRADAY_WARMUP, END, cache,
            include_freshness=True,
            required_columns=('open_interest', 'taker_buy_sell_vol_ratio'))
    return markets, metrics, regimes, regime_config, manifest


def _signals(symbols, markets, metrics, regimes, strategy, attention):
    generated, diagnostics = {}, {}
    for symbol in symbols:
        raw, state = generate_fvg_ifvg_signals(
            markets[symbol][0], metrics[symbol], regimes, symbol, strategy)
        generated[symbol], overlay = apply_liquidity_auction_attention(
            raw, attention)
        diagnostics[symbol] = {'state_machine': state, 'attention': overlay}
    return generated, diagnostics


def _execution(scenario):
    fee, slippage = COSTS[scenario]
    return SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=fee, slippage_bps=slippage,
        leverage=5.0, risk_fraction=0.002, fixed_risk_usd=0.50,
        max_notional_equity=0.75, max_margin_fraction=0.15,
        min_stop_atr=0.50, max_stop_atr=4.0, max_hold_days=1,
        daily_loss_fraction=0.006, weekly_loss_fraction=0.018,
    )


def _run(markets, signals, scenario, symbols):
    return execute_swing_portfolio(
        {symbol: markets[symbol] for symbol in symbols},
        {symbol: signals[symbol] for symbol in symbols},
        {symbol: [] for symbol in symbols},
        {symbol: pd.DataFrame() for symbol in symbols},
        _execution(scenario), START, END, initial_capital=500.0,
        symbol_priority=symbols,
    )


def _evaluate(name, universe_name, symbols, markets, metrics, regimes, output):
    strategy = frozen_variants()[name]
    attention = LiquidityAuctionAttentionConfig()
    signals, diagnostics = _signals(
        symbols, markets, metrics, regimes, strategy, attention)
    record = {
        'strategy_config': asdict(strategy),
        'attention_config': asdict(attention),
        'raw_signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'diagnostics': diagnostics,
        'replays': {}, 'slices': {}, 'leave_one_out_stress_pnl': {},
    }
    replays = {}
    for scenario in ('base', 'stress', 'severe'):
        replay = _run(markets, signals, scenario, symbols)
        replays[scenario] = replay
        record['replays'][scenario] = replay['summary']
        daily = _daily_pnl(replay)
        for window, bounds in WINDOWS.items():
            row = _slice_metrics(daily, *bounds)
            row['trades'] = _window_trade_count(replay['trades'], *bounds)
            record['slices'].setdefault(window, {})[scenario] = row
        artifact = output / f'{name}_{universe_name}_{scenario}_trades.json.gz'
        artifact.write_bytes(gzip.compress(
            json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
        print(name, universe_name, scenario, replay['summary'], flush=True)

    stress = replays['stress']
    record['stress_breakdown'] = _trade_breakdown(stress['trades'])
    record['stress_block_bootstrap'] = _block_bootstrap(_daily_pnl(stress))
    for excluded in symbols:
        kept = tuple(symbol for symbol in symbols if symbol != excluded)
        record['leave_one_out_stress_pnl'][excluded] = _run(
            markets, signals, 'stress', kept)['summary']['net_pnl']
    return record


def _external_gate(record, universe_name):
    stress = record['replays']['stress']
    severe = record['replays']['severe']
    sides = record['stress_breakdown']
    if universe_name == 'primary':
        time_breadth = all(
            record['slices'][name]['stress']['net_pnl'] > 0
            for name in ('development', 'validation', 'retrospective'))
        return bool(
            stress['trades'] >= 24 and stress['net_pnl'] > 0
            and _numeric_pf(stress) > 1.10 and stress['max_drawdown_pct'] <= 5
            and severe['net_pnl'] > 0 and stress['represented_symbols'] >= 2
            and sides['LONG']['net_pnl'] >= 0
            and sides['SHORT']['net_pnl'] >= 0
            and sum(value > 0 for value in
                    record['leave_one_out_stress_pnl'].values()) >= 2
            and record['stress_block_bootstrap']['p10_terminal_pnl'] > 0
            and time_breadth)
    return bool(
        stress['trades'] >= 12 and stress['net_pnl'] > 0
        and _numeric_pf(stress) > 1.05 and severe['net_pnl'] > 0
        and stress['represented_symbols'] >= 2
        and sides['LONG']['net_pnl'] >= 0
        and sides['SHORT']['net_pnl'] >= 0)


def _report(result):
    days = (pd.Timestamp(END) - pd.Timestamp(START)).days
    lines = [
        '# S106 — attention liquidity auction', '',
        f'Frozen protocol: `{result["protocol_sha256"]}`.', '',
        '**Selection-contaminated research; live remains disabled.**', '',
        '| Variant | Universe | Costs | Trades | WR | PF | PnL | $/month | DD |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|',
    ]
    for variant, universes in result['variants'].items():
        for universe, record in universes.items():
            for scenario, row in record['replays'].items():
                lines.append(
                    f'| {variant} | {universe} | {scenario} | '
                    f'{row["trades"]} | {row["win_rate_pct"]:.1f}% | '
                    f'{row["profit_factor"]} | ${row["net_pnl"]:.2f} | '
                    f'${row["net_pnl"] / days * 30.4375:.2f} | '
                    f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', '## External-target diagnostics', ''])
    for universe, record in result['variants']['external_target'].items():
        lines.extend([
            f'### {universe}', '',
            f'- Signals: `{record["raw_signals"]}`.',
            f'- Stress attribution: `{record["stress_breakdown"]}`.',
            f'- Stress slices: `{record["slices"]}`.',
            f'- Leave-one-out: `{record["leave_one_out_stress_pnl"]}`.',
            f'- Bootstrap: `{record["stress_block_bootstrap"]}`.',
            f'- Gate pass: **{record["gate_pass"]}**.', '',
        ])
    lines.extend([
        f'**Overall decision: {result["decision"]}.**', '',
        'A historical pass could only start a new prospective paper clock.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output', default='docs/research/s106_attention_liquidity_auction')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    actual_hash = sha256((output / 'protocol.json').read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError('Frozen S106 protocol hash mismatch')

    markets, metrics, regimes, regime_config, manifest = _load_data(args.cache)
    result = {
        'protocol_sha256': actual_hash,
        'regime_config': asdict(regime_config),
        'variants': {}, 'live_enabled': False,
    }
    for variant in frozen_variants():
        result['variants'][variant] = {}
        for universe_name, symbols in UNIVERSES.items():
            result['variants'][variant][universe_name] = _evaluate(
                variant, universe_name, symbols,
                markets, metrics, regimes, output)

    external = result['variants']['external_target']
    for universe_name, record in external.items():
        record['gate_pass'] = _external_gate(record, universe_name)
    result['decision'] = (
        'START_PROSPECTIVE_PAPER_OBSERVATION_ONLY'
        if all(row['gate_pass'] for row in external.values())
        else 'REJECTED_AT_HISTORICAL_GATE')

    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
