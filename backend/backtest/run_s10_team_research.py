"""Offline retrospective for the team-designed S10 SMT/OB strategy.

The command refuses to fetch data.  BTC is a reference market only; ETH, SOL
and BNB are the tradable symbols currently present in the verified local
archive cache.  All available months were seen by earlier research, so this is
explicitly a retrospective diagnostic, not a fresh holdout.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict, replace
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.liquidity_delivery_scalp import (
    LiquidityDeliveryConfig,
    liquidity_delivery_features,
    liquidity_delivery_signals,
)
from .scalp_data import load_archives
from .scalp_simulator import execute


REFERENCE = 'BTCUSDT'
TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
ALL_SYMBOLS = (REFERENCE, *TRADED)
START, END = '2025-08-01', '2026-09-01'
WARMUP = '2025-07-01'


def _assert_offline_cache(cache: Path) -> None:
    months = pd.period_range(WARMUP, pd.Timestamp(END) - pd.Timedelta(minutes=1), freq='M')
    missing = []
    for symbol in ALL_SYMBOLS:
        for month in months:
            for kind, relative in (
                ('klines', cache / 'klines' / symbol / '1m' / f'{symbol}-1m-{month}.zip'),
                ('funding', cache / 'fundingRate' / symbol / f'{symbol}-fundingRate-{month}.zip'),
            ):
                if not relative.exists() or not Path(f'{relative}.CHECKSUM').exists():
                    missing.append(f'{kind}:{symbol}:{month}')
    if missing:
        raise FileNotFoundError(
            'Offline mode: required archives are absent; refusing network access: '
            + ', '.join(missing[:12]))


def _select_one_alt_per_raid(candidates: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Consume a raid at its first eligible timestamp, with fixed tie-breaks."""
    priority = {symbol: rank for rank, symbol in enumerate(TRADED)}
    flat = [(signal['timestamp'], signal['raid_id'], priority[symbol], symbol, signal)
            for symbol, rows in candidates.items() for signal in rows]
    by_time: dict[pd.Timestamp, list[tuple]] = defaultdict(list)
    for item in flat:
        by_time[item[0]].append(item)

    selected = {symbol: [] for symbol in TRADED}
    consumed: set[str] = set()
    for timestamp in sorted(by_time):
        by_raid: dict[str, list[tuple]] = defaultdict(list)
        for item in by_time[timestamp]:
            if item[1] not in consumed:
                by_raid[item[1]].append(item)
        for raid_id, choices in by_raid.items():
            # All values are known at this timestamp.  Target-to-friction wins;
            # ETH>SOL>BNB is the deterministic liquidity tie-break.
            pick = max(choices, key=lambda x: (x[4]['selection_score'], -x[2]))
            selected[pick[3]].append(pick[4])
            consumed.add(raid_id)
    return selected


def _portfolio_summary(results: dict[str, dict], initial_capital: float) -> dict:
    trades = sorted(
        [dict(trade, symbol=symbol) for symbol, result in results.items()
         for trade in result['trades']],
        key=lambda trade: trade['opened_at'],
    )
    pnls = np.array([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    equity = initial_capital + np.r_[0.0, np.cumsum(pnls)]
    drawdown = (1 - equity / np.maximum.accumulate(equity)) * 100
    monthly = defaultdict(lambda: {'trades': 0, 'pnl': 0.0})
    for trade in trades:
        month = str(pd.Timestamp(trade['opened_at']).to_period('M'))
        monthly[month]['trades'] += 1
        monthly[month]['pnl'] += float(trade['pnl'])
    return {
        'trades': len(trades),
        'wins': int((pnls > 0).sum()),
        'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
        'profit_factor': gains / losses if losses else None,
        'net_pnl': float(pnls.sum()) if len(pnls) else 0.0,
        'return_pct': float(pnls.sum() / initial_capital * 100) if len(pnls) else 0.0,
        'max_drawdown_pct': float(drawdown.max()),
        'per_symbol': {symbol: result['summary'] for symbol, result in results.items()},
        'per_month': dict(sorted(monthly.items())),
        'trades_detail': trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s10_team_strategy')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    _assert_offline_cache(cache)
    output.mkdir(parents=True, exist_ok=True)

    config = LiquidityDeliveryConfig('S10_smt_first_mitigation_central')
    (output / 'protocol.json').write_text(json.dumps({
        'status': 'retrospective_only_all_months_previously_seen',
        'strategy': asdict(config),
        'reference_market_not_traded': REFERENCE,
        'traded_symbols_available_offline': TRADED,
        'window': [START, END],
        'capital': 250,
        'risk': 'fixed $0.75 per trade (0.30% of starting equity), costs included in sizing',
        'portfolio_constraints': 'one alt per BTC raid; at most one raid per side/session; 20x isolated cap; 5% margin cap',
        'causality': 'closed 5m bars; frozen ET session ranges; BTC raid -> alt non-confirmation -> later MSS/displacement -> exact-event OB first mitigation',
        'execution': 'post-only style limit, 2 bps penetration, maker 2 bps; taker exit 5 bps + 2 bps slippage; stop-first ambiguous bars',
        'success_rule_for_future_oos': '>=100 trades, PF>1.15 base and >1.05 stress, positive median month, max DD<6%, >=70% positive weekly bootstrap blocks',
        'disclosure': 'No result in this folder is an untouched holdout. A genuine test requires new data or a frozen 12-week paper-forward run.',
    }, indent=2) + '\n')

    data, features, manifest = {}, {}, {}
    for symbol in ALL_SYMBOLS:
        minutes, funding, manifest[symbol] = load_archives(
            symbol, WARMUP, END, str(cache))
        data[symbol] = minutes, funding
        features[symbol] = liquidity_delivery_features(minutes, 5)
        features[symbol].attrs['symbol'] = symbol

    raw = {symbol: liquidity_delivery_signals(
        features[symbol], features[REFERENCE], config) for symbol in TRADED}
    selected = _select_one_alt_per_raid(raw)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    scenarios = {
        'base': config.execution(),
        'stress': replace(config.execution(), maker_fee_bps=5.0, fee_bps=8.0, slippage_bps=5.0),
    }
    summaries = {}
    for scenario, execution in scenarios.items():
        # A fixed budget makes the three per-symbol replays equivalent to one
        # non-compounding $250 portfolio because raid selection prevents
        # simultaneous correlated entries.
        execution = replace(execution, fixed_risk_usd=0.75, fixed_margin_usd=12.50)
        results = {}
        for symbol in TRADED:
            minutes, funding = data[symbol]
            result = execute(minutes, funding, selected[symbol], features[symbol],
                             execution, START, END, initial_capital=250)
            results[symbol] = result
            payload = json.dumps(result, allow_nan=False).encode()
            (output / f'{scenario}_{symbol}.json.gz').write_bytes(gzip.compress(payload, mtime=0))
        summaries[scenario] = _portfolio_summary(results, 250)
        summary = summaries[scenario]
        print(f'{scenario}: n={summary["trades"]} WR={summary["win_rate_pct"]:.1f}% '
              f'PF={summary["profit_factor"]} PnL={summary["net_pnl"]:.2f} '
              f'DD={summary["max_drawdown_pct"]:.2f}%', flush=True)

    (output / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')


if __name__ == '__main__':
    main()
