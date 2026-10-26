"""S82 — macro burst + Book B shared risk (vol/breadth/A-throttle)."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.book_b_macro_burst import (
    BookBMacroBurstConfig,
    generate_macro_burst_signals,
    macro_burst_features,
)
from l1_filter.book_b_shared_risk import (
    BookBSharedRiskConfig,
    apply_shared_risk_to_signals,
    daily_indicator_table,
)
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig
from .cluster_scalp_simulator import execute_cluster
from .run_s67_dual_daytrade_research import DAILY_GOAL_USD, calendar_day_pnl
from .scalp_data import load_archives


TRADED = ('BTCUSDT', 'ETHUSDT')
WARMUP, END = '2024-08-01', '2026-01-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', END),
}


def _execution(config: BookBMacroBurstConfig, scenario: str):
    base = config.execution()
    base = replace(
        base,
        drawdown_halt_fraction=0.28,
        drawdown_risk_scale_fraction=0.12,
        daily_loss_fraction=0.05,
        consecutive_loss_halt=3,
        fixed_risk_usd=8.0,
    )
    if scenario == 'stress':
        return replace(base, fee_bps=20.0, maker_fee_bps=20.0, slippage_bps=6.0)
    return base


def _raw_signals(data, config, start, end):
    start_ts = pd.Timestamp(start, tz='UTC')
    end_ts = pd.Timestamp(end, tz='UTC')
    return {
        symbol: generate_macro_burst_signals(
            macro_burst_features(data[symbol][0], config),
            config,
            symbol,
            start_ts,
            end_ts,
        )
        for symbol in TRADED
    }


def main() -> None:
    cache = '/tmp/sentinel-scalp-cache'
    output = Path(__file__).resolve().parents[2] / 'docs/research/s82_book_b_macro_rm'
    output.mkdir(parents=True, exist_ok=True)
    macro_cfg = BookBMacroBurstConfig(fixed_risk_usd=8.0)
    risk_cfg = BookBSharedRiskConfig()
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps({
        'strategy_id': 'S82_MACRO_RM',
        'macro': macro_cfg.name,
        'risk': risk_cfg.name,
        'windows': WINDOWS,
    }, indent=2) + '\n')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()

    minutes_map = {}
    data = {}
    for symbol in TRADED:
        m, f, _ = load_archives(symbol, WARMUP, END, cache)
        data[symbol] = (m, f)
        minutes_map[symbol] = m
        print(symbol, 'ready', flush=True)

    gate_cfg = BookASmallTsmomConfig()
    minutes_map.update({
        s: load_archives(s, WARMUP, END, cache)[0]
        for s in gate_cfg.alt_symbols()
    })
    indicators = daily_indicator_table(minutes_map, gate_cfg)

    results = {'S80_raw': {}, 'S82_rm': {}}
    for window, bounds in WINDOWS.items():
        start_ts = pd.Timestamp(bounds[0], tz='UTC')
        end_ts = pd.Timestamp(bounds[1], tz='UTC')
        markets = {s: data[s] for s in TRADED}
        for label, signals in (
            ('S80_raw', _raw_signals(data, macro_cfg, bounds[0], bounds[1])),
            ('S82_rm', {
                s: apply_shared_risk_to_signals(
                    _raw_signals(data, macro_cfg, bounds[0], bounds[1])[s],
                    indicators,
                    risk_cfg,
                )
                for s in TRADED
            }),
        ):
            summary = execute_cluster(
                markets, signals, _execution(macro_cfg, 'base'),
                start_ts, end_ts, 250, TRADED,
            )['summary']
            mean_pnl, days = calendar_day_pnl(summary['net_pnl'], start_ts, end_ts)
            summary['mean_calendar_day_pnl'] = mean_pnl
            summary['gap_to_5_usd_day'] = DAILY_GOAL_USD - mean_pnl
            summary['signals_after_rm'] = sum(len(signals[s]) for s in TRADED)
            results[label][window] = summary
            print(label, window, mean_pnl, summary['net_pnl'], flush=True)

    (output / 'summary.json').write_text(json.dumps(results, indent=2, default=str) + '\n')
    lines = [
        '# S82 — macro + shared risk',
        '',
        f'Hash: `{protocol_hash}`.',
        '',
        f'Cel ${DAILY_GOAL_USD}/dzień. Base risk $8, DD halt 28%, daily loss 5%.',
        '',
        '| Wariant | Okno | Tradów | PnL | $/dzień | Gap $5 |',
        '|---|---|---:|---:|---:|---:|',
    ]
    for label, windows in results.items():
        for window, s in windows.items():
            lines.append(
                f'| {label} | {window} | {s.get("trades", 0)} | '
                f'${s.get("net_pnl", 0):.2f} | ${s.get("mean_calendar_day_pnl", 0):.3f} | '
                f'${s.get("gap_to_5_usd_day", 0):.2f} |'
            )
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('REPORT', output / 'REPORT.md')


if __name__ == '__main__':
    main()
