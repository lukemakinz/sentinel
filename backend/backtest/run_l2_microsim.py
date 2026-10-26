"""L2-A/B/C re-tested on MICRO-SIM: true sub-second execution against
OKX's own mid price (no Binance reference, no 1-minute snap-delay). This
is the honest test of the original hypotheses that run_l2_hist_backtest
could not perform.

Signal definitions (SYMBOLS/DAYS/L2-A/B/C) come from l2_signals.py, the
single shared source -- not redefined here. This file adds only the
MICRO-SIM-specific piece: a volatility unit (stand-in for ATR, since
500ms bars carry a mid snapshot, not true OHLC) used to size the stop.

Volatility unit: rolling std of 60s (120-bar) cumulative log returns,
converted to a price distance. Stop = entry -+ 1.0x this unit.
"""
from pathlib import Path

import numpy as np

from .download_l2_hist import build_feature_bars, download_l2_day
from .l2_signals import DAYS, SYMBOLS
from .l2_signals import generate_signals as generate_l2_signals
from .micro_sim import MicroSimConfig, execute_l2_single_symbol

VOL_WINDOW = 120
STOP_VOL_MULT = 1.0


def compute_bars(symbol, day):
    path = download_l2_day(symbol, day)
    bars = build_feature_bars(path, bar_ms=500)
    Path(path).unlink(missing_ok=True)
    if bars.empty:
        return None
    # vol_unit calibrated from 60s cumulative log returns, not single-
    # 500ms-bar returns: single-bar realized vol (median ~0.27bps) was
    # checked first and found far too small to ever clear this project's
    # own 3x reward/cost filter at any realistic target_r -- a
    # calibration bug caught before reporting a spurious all-rejected
    # result, not a tuning-for-outcome choice.
    ret_60s = np.log(bars.mid).diff(120)
    bars['vol_unit'] = ret_60s.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * bars.mid
    return bars


def build_execution_signals(bars, symbol, mechanism):
    """Wraps the shared trigger list with MICRO-SIM's own stop/vol_unit --
    execution-specific fields the shared generator deliberately omits."""
    vol_unit_at = bars.vol_unit
    mid_at = bars.mid
    out = []
    for sig in generate_l2_signals(bars, symbol, mechanism):
        ts = sig['decision_ts']
        vu = vol_unit_at.loc[ts]
        if not np.isfinite(vu) or vu <= 0:
            continue
        entry = mid_at.loc[ts]
        side = sig['side']
        stop = entry - side * STOP_VOL_MULT * vu
        direction = 'long' if side == 1 else 'short'
        out.append({
            'timestamp': ts, 'side': side, 'stop': float(stop), 'vol_unit': float(vu),
            'setup_id': f'{mechanism}:v1:{symbol}:{direction}:{ts.isoformat()}',
        })
    return out


def main():
    all_bars = {}
    for symbol in SYMBOLS:
        for day in DAYS:
            print(f'downloading/parsing {symbol} {day}...', flush=True)
            bars = compute_bars(symbol, day)
            if bars is not None:
                all_bars[(symbol, day)] = bars

    for mechanism in ('L2A', 'L2B', 'L2C'):
        print(f'\n{"="*90}\n{mechanism} (MICRO-SIM, true sub-second execution)\n{"="*90}')
        total_trades = total_wins = 0
        total_net_base = total_net_stress = 0.0
        total_candidates = 0
        per_symbol_net = {s: 0.0 for s in SYMBOLS}
        for symbol in SYMBOLS:
            for day in DAYS:
                key = (symbol, day)
                if key not in all_bars:
                    continue
                bars = all_bars[key]
                signals = build_execution_signals(bars, symbol, mechanism)
                total_candidates += len(signals)

                base_cfg = MicroSimConfig(fee_bps=5.0, slippage_bps=2.0)
                stress_cfg = MicroSimConfig(fee_bps=8.0, slippage_bps=5.0)
                base = execute_l2_single_symbol(bars, signals, base_cfg, initial_capital=250)
                stress = execute_l2_single_symbol(bars, signals, stress_cfg, initial_capital=250)

                total_trades += base['summary']['trades']
                total_wins += base['summary']['wins']
                total_net_base += base['summary']['net_pnl']
                total_net_stress += stress['summary']['net_pnl']
                per_symbol_net[symbol] += base['summary']['net_pnl']

        print(f'  Total candidates: {total_candidates} ({total_candidates/len(DAYS):.2f}/day pooled)')
        print(f'  {mechanism} MICRO-SIM $250 RESULT across {len(DAYS)} days:')
        wr = total_wins / total_trades * 100 if total_trades else 0
        print(f'    trades={total_trades}  win_rate={wr:.1f}%')
        print(f'    net_pnl base=${total_net_base:.2f}  net_pnl stress=${total_net_stress:.2f}')
        print(f'    per_symbol net (base): {per_symbol_net}')


if __name__ == '__main__':
    main()
