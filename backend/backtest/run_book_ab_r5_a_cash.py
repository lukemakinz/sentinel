"""Reproduce the selected paper baseline: corrected Book A $250 + $250 cash."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from .book_a_portfolio_sim import simulate_book_a
from .run_bench_ab_r3 import COSTS, END, SLICES, START, SYMBOLS, WARMUP, _slice_summary
from .scalp_data import load_archives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/book_ab_r5_a_cash')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')
    minutes, manifest = {}, {}
    for symbol in SYMBOLS:
        minutes[symbol], _, manifest[symbol] = load_archives(
            symbol, WARMUP, END, args.cache)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    start, end = pd.Timestamp(START, tz='UTC'), pd.Timestamp(END, tz='UTC')
    result = {'protocol_sha256': protocol_hash, 'full': {}, 'slices': {}}
    for scenario, cost in COSTS.items():
        book_a = simulate_book_a(
            minutes, replace(BOOK_A_ALT_RM, taker_fee_bps=cost['a']),
            start, end, 250.0, risk=BOOK_A_RISK_DEFAULT)
        daily = book_a.daily_pnl
        result['full'][scenario] = _slice_summary(daily, START, END, initial=500.0)
        result['full'][scenario].update({
            'book_a_pnl': book_a.summary['net_pnl'],
            'cash_reserve_pnl': 0.0,
        })
        for name, bounds in SLICES.items():
            result['slices'].setdefault(name, {})[scenario] = _slice_summary(
                daily, *bounds, initial=500.0)
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = [
        '# Book A+B R5 — Book A + cash reserve', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        'Selected from contaminated development; prospective paper baseline only.', '',
        '| Slice | Costs | PnL | Return | $/day | DD | ES95 daily |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {name} | {scenario} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_slice_start_pct"]:.2f}% | ${row["usd_per_calendar_day"]:.3f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["expected_shortfall_95_daily_return_pct"]:.3f}% |')
    lines.extend(['', 'Book B v2 remains shadow-only until its prospective promotion rule passes.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
