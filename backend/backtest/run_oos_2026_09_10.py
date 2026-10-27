"""OOS replay of frozen BENCH_AB_R2 on data no study used (2026-09-01 onward)."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .bench_ab_r2_replay import book_b_signals, load_market, replay
from .run_bench_ab_r2 import COSTS, _daily_summary
from .sharpe_stats import deflated_sharpe

MONTHLY_END, END = '2026-10-01', '2026-10-27'
WINDOWS = {
    'oos_september': ('2026-09-01', '2026-10-01'),
    'oos_full': ('2026-09-01', END),
}
PRIOR_STUDIES = 133
TARGET_USD_PER_DAY = 5.0


def _summary(daily: pd.Series, initial: float) -> dict:
    daily = daily.copy()
    daily.index = pd.to_datetime(daily.index, utc=True)
    return _daily_summary(daily, initial)


def _returns(daily: pd.Series, initial: float) -> pd.Series:
    equity_before = initial + daily.sort_index().cumsum().shift(fill_value=0.0)
    return daily.sort_index() / equity_before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/oos_2026_09_10')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    minutes, funding, manifest = load_market(args.cache, MONTHLY_END, END)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, default=str) + '\n')

    signals_b = book_b_signals(minutes)
    results = {'protocol_sha256': protocol_hash, 'windows': {}}
    for window, (start, end) in WINDOWS.items():
        results['windows'][window] = {}
        for scenario in COSTS:
            run = replay(minutes, funding, signals_b, start, end, scenario)
            daily, daily_b = run['daily'], run['daily_b']
            summary = _daily_summary(daily)
            summary['gap_to_target_usd_per_day'] = TARGET_USD_PER_DAY - summary['usd_per_calendar_day']
            summary['book_a'] = _summary(run['daily_a'], 250.0)
            summary['book_b'] = {**_summary(daily_b, 250.0), 'trades': run['trades_b']}
            summary['sharpe'] = deflated_sharpe(_returns(daily, 500.0), PRIOR_STUDIES)
            results['windows'][window][scenario] = summary
            print(window, scenario, round(summary['net_pnl'], 2),
                  round(summary['usd_per_calendar_day'], 3), flush=True)

    stress = results['windows']['oos_full']['stress']
    consistent = stress['net_pnl'] > 0 and stress['max_drawdown_pct'] <= 10.0
    results['decision'] = (
        'CONSISTENT_PROCEED_TO_DAILY_PAPER_FORWARD' if consistent
        else 'INCONSISTENT_NO_CAPITAL')
    (output / 'summary.json').write_text(json.dumps(results, indent=2, default=str) + '\n')

    lines = ['# OOS 2026-09/10 — frozen BENCH_AB_R2 on untouched data', '',
             f'Protocol hash: `{protocol_hash}`.', '',
             '| Window | Costs | A PnL | B PnL (trades) | Total | $/day | Gap to $5/day | Return | Max DD | Sharpe/yr | PSR>0 | DSR (N=133) |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for window, scenarios in results['windows'].items():
        for scenario, row in scenarios.items():
            s = row['sharpe']
            fmt = lambda v: '—' if v is None else f'{v:.2f}'  # noqa: E731
            lines.append(
                f"| {window} | {scenario} | ${row['book_a']['net_pnl']:.2f} | "
                f"${row['book_b']['net_pnl']:.2f} ({row['book_b']['trades']}) | "
                f"${row['net_pnl']:.2f} | ${row['usd_per_calendar_day']:.3f} | "
                f"${row['gap_to_target_usd_per_day']:.2f} | {row['return_pct']:.2f}% | "
                f"{row['max_drawdown_pct']:.2f}% | {s['sr_annualized']:.2f} | "
                f"{fmt(s['psr_vs_zero'])} | {fmt(s['dsr'])} |")
    lines.extend(['', 'Historical stress $/day: development 0.178, validation 0.105, '
                  'retrospective evaluation 0.160.', '',
                  f"**Decision: {results['decision']}.**", '',
                  '56 days can falsify but not prove an edge. Untouched-data replay, not live.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
