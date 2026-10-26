"""Book A risk overlay + indicator research ($250, $5/day goal)."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import (
    BookARiskOverlayConfig,
    indicator_research_frame,
    risk_overlay_variants,
)
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig
from .book_a_portfolio_sim import simulate_book_a
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


WARMUP, END = '2024-08-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')


def _summarize(sim, start, end):
    s = sim.summary.copy()
    mean_pnl, days = calendar_day_pnl(s['net_pnl'], start, end)
    s['mean_calendar_day_pnl'] = mean_pnl
    s['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
    return s


def _indicator_report(frame: pd.DataFrame) -> dict:
    """Correlation of indicators with forward 5d EW alt return."""
    target = frame['fwd5_ew_alt'].dropna()
    if target.empty:
        return {}
    out = {}
    for col in frame.columns:
        if col in ('fwd5_ew_alt', 'valid', 'btc_above_sma200', 'btc_above_sma50'):
            continue
        series = frame[col].reindex(target.index).dropna()
        aligned = target.reindex(series.index).dropna()
        if len(aligned) < 30:
            continue
        out[col] = float(np.corrcoef(series.loc[aligned.index], aligned)[0, 1])
    bull = frame[frame['btc_above_sma200'] > 0]
    bear = frame[frame['btc_above_sma200'] < 1]
    out['mean_fwd5_when_bull'] = float(bull['fwd5_ew_alt'].mean()) if len(bull) else np.nan
    out['mean_fwd5_when_bear'] = float(bear['fwd5_ew_alt'].mean()) if len(bear) else np.nan
    out['pct_days_bull'] = float((frame['btc_above_sma200'] > 0).mean())
    return out


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/book_a_risk_overlay'
    output.mkdir(parents=True, exist_ok=True)
    base_config = BookASmallTsmomConfig()

    protocol = {
        'strategy_id': 'BOOK_A_RISK_RESEARCH',
        'base': base_config.name,
        'windows': WINDOWS,
        'overlays': [v.name for v in risk_overlay_variants()],
        'daily_goal_usd': DAILY_GOAL_USD,
    }
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol, indent=2, default=str) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()

    minutes = {}
    for symbol in SYMBOLS:
        minutes[symbol], _, _ = load_archives(symbol, WARMUP, END, cache)
        print(symbol, 'ready', flush=True)

    from l1_filter.book_a_small_tsmom import build_daily_panel
    panel = build_daily_panel(minutes, base_config)
    ind_frame = indicator_research_frame(panel, base_config)
    ind_stats = _indicator_report(ind_frame)
    ind_frame.to_csv(output / 'daily_indicators.csv')
    (output / 'indicator_correlations.json').write_text(
        json.dumps(ind_stats, indent=2) + '\n')

    results = {'baseline': {}, 'overlays': {}}
    for window, bounds in WINDOWS.items():
        start = pd.Timestamp(bounds[0], tz='UTC')
        end = pd.Timestamp(bounds[1], tz='UTC')
        sim = simulate_book_a(minutes, base_config, start, end, 250.0, risk=None)
        results['baseline'][window] = _summarize(sim, start, end)
        for overlay in risk_overlay_variants():
            sim_r = simulate_book_a(
                minutes, base_config, start, end, 250.0, risk=overlay,
            )
            results['overlays'].setdefault(overlay.name, {})[window] = _summarize(
                sim_r, start, end,
            )

    (output / 'summary.json').write_text(json.dumps(results, indent=2, default=str) + '\n')

    lines = [
        '# Book A — risk overlay research',
        '',
        f'Hash: `{protocol_hash}`.',
        '',
        '## Wskaźniki vs forward 5d (equal-weight alty)',
        '',
    ]
    for key, val in sorted(ind_stats.items(), key=lambda x: abs(x[1]) if isinstance(x[1], float) else 0, reverse=True):
        lines.append(f'- `{key}`: {val:.4f}' if isinstance(val, float) and np.isfinite(val) else f'- `{key}`: {val}')
    lines.extend([
        '',
        f'Cel **${DAILY_GOAL_USD}/dzień** @ $250.',
        '',
        '| Wariant | Okno | PnL | $/dzień | Max DD | Gap $5 |',
        '|---|---|---:|---:|---:|---:|',
    ])
    for window, row in results['baseline'].items():
        lines.append(
            f'| baseline | {window} | ${row["net_pnl"]:.2f} | '
            f'${row["mean_calendar_day_pnl"]:.3f} | {row["max_drawdown_fraction"]:.1%} | '
            f'${row["gap_to_5_usd_day"]:.2f} |'
        )
    for name, windows in results['overlays'].items():
        for window, row in windows.items():
            lines.append(
                f'| {name} | {window} | ${row["net_pnl"]:.2f} | '
                f'${row["mean_calendar_day_pnl"]:.3f} | {row["max_drawdown_fraction"]:.1%} | '
                f'${row["gap_to_5_usd_day"]:.2f} |'
            )
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
