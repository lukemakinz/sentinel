"""Book A under funding and KuCoin contract sizes; Book B BTC lot rounding check."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig
from .bench_ab_r2_replay import book_b_signals, load_market
from .book_a_portfolio_sim import simulate_book_a
from .cluster_scalp_simulator import execute_cluster
from .run_bench_ab_r2 import COSTS

MONTHLY_END, END = '2026-10-01', '2026-10-27'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', '2026-09-01'),
    'oos_2026_09_10': ('2026-09-01', END),
}
KUCOIN_STEPS = {'SOLUSDT': 0.1, 'XRPUSDT': 10.0, 'DOGEUSDT': 100.0, 'BNBUSDT': 0.01,
                'ETHUSDT': 0.01, 'BTCUSDT': 0.001}
KUCOIN_FUNDING_MULTIPLIER = 1.6
VARIANTS = {
    'V0_frozen': dict(capital=250.0),
    'V1_binance_funding': dict(capital=250.0, funding=True),
    'V2_kucoin_funding': dict(capital=250.0, funding=True, mult=KUCOIN_FUNDING_MULTIPLIER),
    'V3_kucoin_250': dict(capital=250.0, funding=True, mult=KUCOIN_FUNDING_MULTIPLIER, lots=True),
    'V4_kucoin_500': dict(capital=500.0, funding=True, mult=KUCOIN_FUNDING_MULTIPLIER, lots=True),
    'V5_kucoin_1000': dict(capital=1000.0, funding=True, mult=KUCOIN_FUNDING_MULTIPLIER, lots=True),
}


def _ts(value):
    return pd.Timestamp(value, tz='UTC')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/book_a_execution_realism')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    minutes, funding, _ = load_market(args.cache, MONTHLY_END, END)
    config = replace(BOOK_A_ALT_RM, taker_fee_bps=COSTS['stress']['a'])
    results = {'protocol_sha256': protocol_hash, 'book_a': {}, 'book_b_lots': {}}
    for window, (start, end) in WINDOWS.items():
        days = (_ts(end) - _ts(start)).days
        results['book_a'][window] = {}
        for name, v in VARIANTS.items():
            run = simulate_book_a(
                minutes, config, _ts(start), _ts(end), v['capital'], risk=BOOK_A_RISK_DEFAULT,
                funding=funding if v.get('funding') else None,
                funding_multiplier=v.get('mult', 1.0),
                quantity_steps=KUCOIN_STEPS if v.get('lots') else None)
            s = run.summary
            results['book_a'][window][name] = {
                'capital': v['capital'], 'net_pnl': s['net_pnl'],
                'return_pct': s['net_pnl'] / v['capital'] * 100,
                'usd_per_day': s['net_pnl'] / days,
                'usd_per_day_per_250': s['net_pnl'] / days * 250 / v['capital'],
                'funding_paid': s['funding_paid'], 'fees_paid': s['fees_paid'],
                'max_drawdown_pct': -s['max_drawdown_fraction'] * 100,
            }
            print(window, name, round(s['net_pnl'], 2), round(s['funding_paid'], 2), flush=True)

    # Book B: how far is each BTC position from a whole number of 0.001 BTC contracts?
    cost = COSTS['stress']
    config_b = replace(BookBQuietBreakoutConfig().execution(), fee_bps=cost['fee'],
                       maker_fee_bps=cost['fee'], slippage_bps=cost['slip'], fixed_risk_usd=6.0,
                       drawdown_halt_fraction=0.28, daily_loss_fraction=0.05,
                       consecutive_loss_halt=3)
    signals_b = book_b_signals(minutes)
    for window, (start, end) in WINDOWS.items():
        replay = execute_cluster({'BTCUSDT': (minutes['BTCUSDT'], funding['BTCUSDT'])},
                                 signals_b, config_b, _ts(start), _ts(end), 250.0, ('BTCUSDT',))
        contracts = np.array([t['quantity'] / KUCOIN_STEPS['BTCUSDT'] for t in replay['trades']])
        if len(contracts):
            rounded = np.maximum(np.round(contracts), 1)
            error = np.abs(rounded - contracts) / contracts * 100
            results['book_b_lots'][window] = {
                'trades': int(len(contracts)),
                'median_contracts': float(np.median(contracts)),
                'min_contracts': float(contracts.min()),
                'median_size_error_pct': float(np.median(error)),
                'max_size_error_pct': float(error.max()),
                'median_notional_usd': float(np.median([t['quantity'] * t['entry'] for t in replay['trades']])),
            }
        else:
            results['book_b_lots'][window] = {'trades': 0}

    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = ['# Book A execution realism — funding and KuCoin contract sizes', '',
             f'Protocol hash: `{protocol_hash}`. Stress costs, rules unchanged.', '',
             '| Window | Variant | Capital | PnL | Return | $/day | $/day per $250 | Funding paid | Max DD |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for window, variants in results['book_a'].items():
        for name, r in variants.items():
            lines.append(f"| {window} | {name} | ${r['capital']:.0f} | ${r['net_pnl']:.2f} | "
                         f"{r['return_pct']:.2f}% | ${r['usd_per_day']:.3f} | "
                         f"${r['usd_per_day_per_250']:.3f} | ${r['funding_paid']:.2f} | "
                         f"{r['max_drawdown_pct']:.2f}% |")
    lines += ['', '## Book B (BTC, $6 fixed risk) vs 0.001 BTC contracts', '',
              '| Window | Trades | Median contracts | Min | Median size error | Max error | Median notional |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for window, r in results['book_b_lots'].items():
        if r['trades']:
            lines.append(f"| {window} | {r['trades']} | {r['median_contracts']:.1f} | "
                         f"{r['min_contracts']:.1f} | {r['median_size_error_pct']:.1f}% | "
                         f"{r['max_size_error_pct']:.1f}% | ${r['median_notional_usd']:.0f} |")
        else:
            lines.append(f'| {window} | 0 | — | — | — | — | — |')
    lines += ['', f'KuCoin funding = Binance x{KUCOIN_FUNDING_MULTIPLIER} '
              '(30-day ratio, sensitivity only).', '']
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
