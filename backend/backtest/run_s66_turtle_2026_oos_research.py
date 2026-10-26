"""S66: 2026 OOS of frozen S64 daily turtle. No retune."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.daily_turtle_swing import (
    DailyTurtleConfig,
    daily_turtle_features,
    generate_daily_turtle_signals,
)
from .run_s64_day_swing_research import (
    TRADED,
    _run_window,
    _numeric_pf,
)
from .scalp_data import load_archives


WARMUP, START, END = '2025-12-01', '2026-01-01', '2026-09-01'


def main():
    cache = Path('/tmp/sentinel-scalp-cache')
    output = Path(__file__).resolve().parents[2] / 'docs/research/s66_turtle_2026_oos'
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / 'protocol.json'
    protocol = {
        'strategy_id': 'S66_TURTLE_2026_OOS',
        'parent': 'S64_daily_turtle_20',
        'traded': list(TRADED),
        'window': {'oos': (START, END)},
        'retune': False,
        'disclosure': 'genuine 2026 OOS of frozen S64 turtle; not live approval',
    }
    protocol_path.write_text(json.dumps(protocol, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    data = {}
    for symbol in TRADED:
        minutes, funding, manifest = load_archives(
            symbol, WARMUP, END, str(cache), repair_from_daily=True)
        data[symbol] = minutes, funding
        print(symbol, 'ready', len(minutes), flush=True)

    config = DailyTurtleConfig()
    markets = {symbol: data[symbol] for symbol in TRADED}
    raw = {
        symbol: generate_daily_turtle_signals(
            daily_turtle_features(data[symbol][0], config), config, symbol)
        for symbol in TRADED
    }
    results = {}
    for scenario in ('base', 'stress', 'severe'):
        summary = _run_window(markets, raw, config, scenario, START, END)
        results[scenario] = summary
        print(
            'turtle_2026', scenario, summary['trades'],
            summary['profit_factor'], f'${summary["net_pnl"]:.2f}',
            f'${summary["mean_calendar_day_pnl"]:.2f}/d',
            flush=True,
        )
    base = results['base']
    if base['trades'] < 8 or base['net_pnl'] <= 0 or _numeric_pf(base) < 1.0:
        decision = 'REJECTED_ON_2026_OOS'
    else:
        decision = 'SURVIVED_2026_OOS_NOT_APPROVED_FOR_LIVE'
    start_ts = pd.Timestamp(START, tz='UTC')
    end_ts = pd.Timestamp(END, tz='UTC')
    raw_n = sum(
        start_ts <= signal['timestamp'] < end_ts
        for signals in raw.values() for signal in signals
    )

    lines = [
        '# S66 — 2026 OOS zamrożonego S64 turtle',
        '',
        f'Hash protokołu: `{protocol_hash}`.',
        '',
        'Bez strojenia. To samo DailyTurtleConfig co S64. '
        'Okno 2026-01-01–2026-09-01 nie brało udziału w S64/S65.',
        '',
        '| Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for scenario, summary in results.items():
        pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
        lines.append(
            f'| {scenario} | {summary["trades"]} | '
            f'{summary["win_rate_pct"]:.1f}% | {pf} | '
            f'${summary["net_pnl"]:.2f} | '
            f'${summary["mean_calendar_day_pnl"]:.2f} | '
            f'{summary["max_drawdown_pct"]:.3f}% | '
            f'{summary["mean_net_r"]:.3f} |'
        )
    lines.extend([
        '',
        f'- Decyzja: **{decision}**.',
        f'- Kandydaty surowe: {raw_n}.',
        '',
        'Nie jest to zgoda na live.',
        '',
    ])

    (output / 'summary.json').write_text(
        json.dumps({
            'protocol_sha256': protocol_hash,
            'decision': decision,
            'results': results,
        }, indent=2, allow_nan=False, default=str) + '\n')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(decision)


if __name__ == '__main__':
    main()
