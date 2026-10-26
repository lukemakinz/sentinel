"""Book A — frozen S73+BTC weekly TSMOM on available alt panel ($250)."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig
from .book_a_portfolio_sim import simulate_book_a
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


WARMUP, END = '2024-08-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
    'holdout': ('2025-10-01', END),
}
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')


def _run_window(minutes, start, end, config):
    start_ts = pd.Timestamp(start, tz='UTC')
    end_ts = pd.Timestamp(end, tz='UTC')
    result = simulate_book_a(minutes, config, start_ts, end_ts, initial_capital=250.0)
    summary = result.summary
    mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start_ts, end_ts)
    summary['mean_calendar_day_pnl'] = mean_pnl
    summary['calendar_days'] = days
    summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
    summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
    return summary


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/book_a_s73_btc'
    output.mkdir(parents=True, exist_ok=True)
    config = BookASmallTsmomConfig()
    risk = BOOK_A_RISK_DEFAULT
    protocol = {
        'strategy_id': config.name,
        'capital_usd': 250,
        'symbols': list(SYMBOLS),
        'windows': WINDOWS,
        'disclosure': 'Reduced alt panel vs scratchpad S73; same rules',
    }
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    minutes = {}
    for symbol in SYMBOLS:
        frame, _, _ = load_archives(symbol, WARMUP, END, cache)
        minutes[symbol] = frame
        print(symbol, 'ready', flush=True)

    results = {}
    for window, bounds in WINDOWS.items():
        results[window] = _run_window(minutes, bounds[0], bounds[1], config)
    results_rm = {}
    for window, bounds in WINDOWS.items():
        start_ts = pd.Timestamp(bounds[0], tz='UTC')
        end_ts = pd.Timestamp(bounds[1], tz='UTC')
        sim = simulate_book_a(minutes, config, start_ts, end_ts, 250.0, risk=risk)
        summary = sim.summary
        mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start_ts, end_ts)
        summary['mean_calendar_day_pnl'] = mean_pnl
        summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
        summary['hits_5_usd_day'] = mean_pnl >= DAILY_GOAL_USD
        results_rm[window] = summary

    (output / 'summary.json').write_text(json.dumps({
        'baseline': results,
        'with_rm_composite_v1': results_rm,
    }, indent=2, default=str) + '\n')

    lines = [
        '# Book A — S73+BTC (repo replay)',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Panel: BTC gate + ETH/SOL/XRP/DOGE/BNB (cache lokalny). Kapitał $250, rebalance '
        'poniedziałek, long-only gdy BTC > SMA200, top 6 momentum, min pozycja $15, 7 bps.',
        '',
        f'Cel portfela: **${DAILY_GOAL_USD}/dzień**.',
        '',
        '| Okno | PnL netto | Opłaty | $/dzień | Max DD | Gap do $5 | $5? |',
        '|---|---:|---:|---:|---:|---:|---|',
    ]
    for window, summary in results.items():
        lines.append(
            f'| {window} (baseline) | ${summary["net_pnl"]:.2f} | ${summary["fees_paid"]:.2f} | '
            f'${summary["mean_calendar_day_pnl"]:.3f} | {summary["max_drawdown_fraction"]:.1%} | '
            f'${summary["gap_to_5_usd_day"]:.2f} | '
            f'{"yes" if summary["hits_5_usd_day"] else "no"} |'
        )
    for window, summary in results_rm.items():
        lines.append(
            f'| {window} (+RM) | ${summary["net_pnl"]:.2f} | ${summary["fees_paid"]:.2f} | '
            f'${summary["mean_calendar_day_pnl"]:.3f} | {summary["max_drawdown_fraction"]:.1%} | '
            f'${summary["gap_to_5_usd_day"]:.2f} | '
            f'{"yes" if summary["hits_5_usd_day"] else "no"} |'
        )
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
