"""S83 quiet Donchian — dedicated report."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_b_quiet_breakout import BookBQuietBreakoutConfig, build_quiet_breakout_signals
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .run_s83_experiment_matrix import _exec_b, _load_minutes
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-01-01'),
}


def main() -> None:
    output = Path(__file__).resolve().parents[2] / 'docs/research/s83_quiet_breakout'
    output.mkdir(parents=True, exist_ok=True)
    cfg = BookBQuietBreakoutConfig()
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps({'strategy_id': cfg.name}, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    minutes = _load_minutes()
    results = {}
    for window, bounds in WINDOWS.items():
        st, en = pd.Timestamp(bounds[0], tz='UTC'), pd.Timestamp(bounds[1], tz='UTC')
        signals = {'BTCUSDT': build_quiet_breakout_signals(
            minutes['BTCUSDT'], minutes, 'BTCUSDT', cfg)}
        markets = {'BTCUSDT': (minutes['BTCUSDT'], load_archives(
            'BTCUSDT', '2025-04-01', '2026-01-01', '/tmp/sentinel-scalp-cache')[1])}
        summary = execute_cluster(
            markets, signals, _exec_b(cfg.execution()), st, en, 250, ('BTCUSDT',),
        )['summary']
        mean, _ = calendar_day_pnl(summary['net_pnl'], st, en)
        summary['mean_calendar_day_pnl'] = mean
        summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean
        results[window] = summary
    (output / 'summary.json').write_text(json.dumps(results, indent=2, default=str) + '\n')
    lines = ['# S83 Quiet Donchian', '', f'Hash `{protocol_hash}`.', '']
    for w, s in results.items():
        lines.append(
            f'- **{w}:** ${s["mean_calendar_day_pnl"]:.3f}/d, '
            f'PnL ${s["net_pnl"]:.2f}, trades {s["trades"]}, gap ${s["gap_to_5_usd_day"]:.2f}')
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
