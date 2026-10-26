"""Blind September 2026 holdout for the exact frozen S105 geometry variant."""
import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, asymmetric_global_regimes,
)
from .metrics_data import load_metrics
from .run_s103_fvg_ifvg_decision_tree import (
    COSTS, DAILY_WARMUP, INTRADAY_WARMUP, REGIME_SYMBOLS, TRADED,
)
from .run_s105_liquidity_auction_ablation import _signals, variants
from .swing_data import load_interval_archives, regularize_interval
from .swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


START = '2026-09-01'
END = '2026-10-01'
PROTOCOL_SHA256 = '09cbf4caac0908063f2eee9bb04c1acdd0336beec75edf276976a721db7daa9c'


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


def _execution(scenario):
    fee, slippage = COSTS[scenario]
    return SwingExecutionConfig(
        exit_policy='initial_sl_only', fee_bps=fee, slippage_bps=slippage,
        leverage=5.0, risk_fraction=0.002, fixed_risk_usd=0.50,
        max_notional_equity=0.75, max_margin_fraction=0.15,
        min_stop_atr=0.50, max_stop_atr=4.0, max_hold_days=1,
        daily_loss_fraction=0.006, weekly_loss_fraction=0.018,
    )


def _run(markets, signals, scenario):
    return execute_swing_portfolio(
        markets, signals, {symbol: [] for symbol in TRADED},
        {symbol: pd.DataFrame() for symbol in TRADED},
        _execution(scenario), START, END, initial_capital=500.0,
        symbol_priority=TRADED,
    )


def _report(result):
    lines = [
        '# S105 geometry — blind September 2026 holdout', '',
        f'Frozen protocol: `{result["protocol_sha256"]}`.', '',
        '**Unseen historical holdout; live trading remains disabled.**', '',
        '| Costs | Signals | Trades | WR | PF | PnL | DD |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    signals = sum(result['raw_signals'].values())
    for scenario, row in result['replays'].items():
        lines.append(
            f'| {scenario} | {signals} | {row["summary"]["trades"]} | '
            f'{row["summary"]["win_rate_pct"]:.1f}% | '
            f'{row["summary"]["profit_factor"]} | '
            f'${row["summary"]["net_pnl"]:.2f} | '
            f'{row["summary"]["max_drawdown_pct"]:.2f}% |')
    lines.extend([
        '', f'**Interpretation: {result["interpretation"]}.**', '',
        'This holdout cannot reverse the failed S105 historical robustness gate.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output', default='docs/research/s105_blind_september_holdout')
    args = parser.parse_args()
    output = Path(args.output)
    actual_hash = sha256((output / 'protocol.json').read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError('Frozen holdout protocol hash mismatch')

    markets, metrics, regimes, regime_config, manifest = _load_data(args.cache)
    config = variants()['geometry']
    signals, diagnostics = _signals(markets, metrics, regimes, config)
    result = {
        'protocol_sha256': actual_hash,
        'config': asdict(config),
        'regime_config': asdict(regime_config),
        'raw_signals': {symbol: len(rows) for symbol, rows in signals.items()},
        'signal_diagnostics': diagnostics,
        'replays': {},
        'live_enabled': False,
    }
    for scenario in ('base', 'stress', 'severe'):
        replay = _run(markets, signals, scenario)
        result['replays'][scenario] = {'summary': replay['summary']}
        (output / f'{scenario}_trades.json.gz').write_bytes(gzip.compress(
            json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
    stress = result['replays']['stress']['summary']
    if stress['trades'] < 4:
        result['interpretation'] = 'INCONCLUSIVE_TINY_SAMPLE'
    elif stress['net_pnl'] <= 0:
        result['interpretation'] = 'NEGATIVE_FALSIFICATION'
    else:
        result['interpretation'] = 'POSITIVE_NEW_EVIDENCE_NOT_PROMOTION'

    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))
    print(result['interpretation'], result['raw_signals'], flush=True)


if __name__ == '__main__':
    main()
