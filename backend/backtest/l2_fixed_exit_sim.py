"""Fixed-5s-exit $ execution engine for L2A-5S / L2B-REV-5S. No
stop-loss, no target, no trailing -- exit is always decision_ts + 5s,
at the real executable bid/ask, exactly as pre-registered in
docs/research/l2_oos_stage1_protocol.md. vol_unit is used only to size
positions (risk-normalization unit), never as an exit trigger.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZON_5S_NS = 5_000_000_000


@dataclass
class FixedExitConfig:
    latency_ms: int = 250
    fee_bps: float = 5.0          # taker, one side
    extra_slippage_bps: float = 0.0  # beyond the real crossed bid/ask (0 = base, >0 = stress)
    fixed_risk_usd: float = 0.50
    risk_fraction: float = 0.0020
    # Same leverage/margin-cap convention as MicroSimConfig -- omitted from
    # an earlier version of this file, which let qty = risk_usd / vol_unit
    # size an UNCAPPED notional whenever vol_unit was small relative to
    # price (median implied notional was $1378 on a $250 book, ~5.5x
    # leverage, fees alone median $1.38 vs a $0.50 risk budget -- fees
    # structurally exceeded the entire risk budget on most trades,
    # regardless of signal quality). Caught before reporting a result.
    leverage: float = 5.0
    max_margin_fraction: float = 0.10


def asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, target_i8):
    pos = np.searchsorted(tob_idx_i8, target_i8, side='right') - 1
    if pos < 0:
        return None
    return tob_bid[pos], tob_ask[pos], tob_mid[pos]


def run_fixed_exit_sim(bars, tob, signals, config: FixedExitConfig, initial_capital: float = 250.0) -> dict:
    """`signals`: list of {'decision_ts', 'side', 'vol_unit'}.
    One open position at a time -- a signal while a position is open is
    skipped (not queued), matching MICRO-SIM's discipline.
    """
    tob_idx_i8 = tob.index.asi8
    tob_bid = tob.best_bid.to_numpy()
    tob_ask = tob.best_ask.to_numpy()
    tob_mid = tob.mid.to_numpy()

    fee = config.fee_bps / 10_000
    slip = config.extra_slippage_bps / 10_000

    cash = initial_capital
    equity_curve = [(None, cash)]
    trades = []
    open_until = None
    diagnostics = {'signals': 0, 'blocked_open_position': 0, 'blocked_no_tob': 0, 'blocked_no_volunit': 0, 'fills': 0}

    for sig in sorted(signals, key=lambda s: s['decision_ts']):
        diagnostics['signals'] += 1
        ts = sig['decision_ts']
        if open_until is not None and ts < open_until:
            diagnostics['blocked_open_position'] += 1
            continue

        vu = sig.get('vol_unit')
        if vu is None or not np.isfinite(vu) or vu <= 0:
            diagnostics['blocked_no_volunit'] += 1
            continue

        if cash <= 0:
            diagnostics['blocked_no_capital'] = diagnostics.get('blocked_no_capital', 0) + 1
            continue

        side = sig['side']
        decision_i8 = ts.value
        entry_target_i8 = decision_i8 + config.latency_ms * 1_000_000
        # exit is +5s from the DECISION point (protocol wording), not from
        # the latency-delayed entry -- the two only differ by latency_ms
        # (<=1s here) but the spec is explicit, so match it exactly.
        exit_target_i8 = decision_i8 + HORIZON_5S_NS

        entry_row = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, entry_target_i8)
        exit_row = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, exit_target_i8)
        if entry_row is None or exit_row is None:
            diagnostics['blocked_no_tob'] += 1
            continue

        entry_bid, entry_ask, _ = entry_row
        exit_bid, exit_ask, _ = exit_row
        raw_entry = entry_ask if side == 1 else entry_bid
        raw_exit = exit_bid if side == 1 else exit_ask
        # extra_slippage: applied AGAINST the trader on both legs (0 at base --
        # the real bid/ask crossing already IS the fill, no double-counted spread)
        entry_price = raw_entry * (1 + side * slip)
        exit_price = raw_exit * (1 - side * slip)

        risk_usd = min(cash * config.risk_fraction, config.fixed_risk_usd)
        qty = risk_usd / vu
        notional = qty * entry_price
        margin = notional / config.leverage
        if margin > cash * config.max_margin_fraction:
            # same cap as MicroSimConfig: when vol_unit is small relative to
            # price, risk_usd/vol_unit alone would imply unbounded notional
            # -- cap qty by margin and recompute risk_usd to match, so R
            # multiples stay internally consistent.
            qty = (cash * config.max_margin_fraction * config.leverage) / entry_price
            risk_usd = qty * vu

        gross = side * (exit_price - entry_price) * qty
        fees = (entry_price + exit_price) * qty * fee
        pnl = gross - fees
        cash += pnl
        equity_curve.append((ts, cash))
        gross_bps = side * (exit_price / entry_price - 1.0) * 10_000
        net_bps = gross_bps - config.fee_bps * 2  # both legs' taker fee, same convention as run_l2_edge_audit.py

        trades.append({
            'decision_ts': ts, 'side': 'LONG' if side == 1 else 'SHORT',
            'entry': entry_price, 'exit': exit_price, 'gross_pnl': gross, 'fees': fees, 'pnl': pnl,
            'gross_bps': gross_bps, 'net_bps': net_bps,
            'r_multiple': pnl / risk_usd, 'gross_r': gross / risk_usd, 'risk_usd': risk_usd,
        })
        diagnostics['fills'] += 1
        open_until = ts + pd.Timedelta(seconds=5)

    pnls = np.array([t['pnl'] for t in trades])
    gross_pnls = np.array([t['gross_pnl'] for t in trades])
    equity = np.array([e[1] for e in equity_curve])
    running_max = np.maximum.accumulate(equity)
    max_dd_usd = float((running_max - equity).max()) if len(equity) else 0.0
    max_dd_pct = float(((running_max - equity) / running_max).max() * 100) if len(equity) else 0.0

    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    gross_gains = float(gross_pnls[gross_pnls > 0].sum()) if len(gross_pnls) else 0.0
    gross_losses = float(-gross_pnls[gross_pnls < 0].sum()) if len(gross_pnls) else 0.0

    return {
        'trades': trades,
        'diagnostics': diagnostics,
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'net_pf': (gains / losses) if losses else (float('inf') if gains > 0 else float('nan')),
            'gross_pf': (gross_gains / gross_losses) if gross_losses else (float('inf') if gross_gains > 0 else float('nan')),
            'net_pnl': float(cash - initial_capital),
            'mean_net_r': float(np.mean([t['r_multiple'] for t in trades])) if trades else float('nan'),
            'mean_gross_r': float(np.mean([t['gross_r'] for t in trades])) if trades else float('nan'),
            'avg_win': float(pnls[pnls > 0].mean()) if (pnls > 0).any() else 0.0,
            'avg_loss': float(pnls[pnls < 0].mean()) if (pnls < 0).any() else 0.0,
            'max_dd_usd': max_dd_usd,
            'max_dd_pct': max_dd_pct,
        },
    }
