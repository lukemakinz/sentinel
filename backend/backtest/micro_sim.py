"""MICRO-SIM: a dedicated sub-second replay engine for L2-triggered
signals, built because cluster_scalp_simulator.execute_cluster walks a
1-MINUTE Binance index and cannot see sub-minute signal timestamps (the
bug found in run_l2_hist_backtest.py -- diagnostics showed 'signals': 0
until timestamps were snapped to the next whole minute, which added up
to 59s of execution delay and defeated the entire point of testing a
sub-second microstructure thesis).

Design choices, disclosed:
  - Executes directly against OKX's own L2 mid price (the same venue the
    signal is computed from), not Binance -- this also removes the
    earlier OKX-vs-Binance reference/stop mismatch entirely, since there
    is now only one price series in play.
  - Single symbol, single global position (same discipline as
    execute_cluster: one position at a time, no pyramiding).
  - Same cost/risk conventions as ScalpConfig elsewhere in this project
    (fixed_risk_usd, fee_bps/slippage_bps, daily_loss_fraction,
    min_reward_cost_ratio, leverage/margin caps) -- a new engine, not new
    economics.
  - Bar-close fills (no intrabar path modeled): a signal at bar i fills
    at bar i's mid (with slippage), exits are evaluated at each
    subsequent bar's mid against stop/target/trailing -- the L2 grid is
    500ms, so this is already far finer than the 1-minute grid it
    replaces, without pretending to model true tick-by-tick queue
    position or partial fills.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MicroSimConfig:
    target_r: float = 8.0
    partial_r: float = 1.5
    trail_mult: float = 2.5   # multiplies the same volatility unit as the stop
    max_hold_bars: int = 3600  # at 500ms bars, 3600 = 30 minutes
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    fixed_risk_usd: float = 0.50
    risk_fraction: float = 0.0020
    daily_loss_fraction: float = 0.006
    min_reward_cost_ratio: float = 3.0
    leverage: float = 5.0
    max_margin_fraction: float = 0.10


def execute_l2_single_symbol(bars: pd.DataFrame, signals: list[dict], config: MicroSimConfig,
                              initial_capital: float = 250.0) -> dict:
    """`bars`: L2 500ms feature bars, must have a 'mid' column, index = ts.
    `signals`: list of {'timestamp', 'side', 'stop', 'vol_unit'} -- stop is
    an absolute price, vol_unit is the same unit used to derive it (e.g.
    the rolling mid-return std used as an ATR substitute), so target/
    trailing distances scale consistently with the stop distance.
    """
    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000
    signal_by_ts = {s['timestamp']: s for s in signals}

    mid = bars['mid']
    idx = bars.index
    cash = initial_capital
    pos = None
    trades = []
    day = None
    day_start_equity = cash
    day_blocked = False
    diagnostics = {'signals': 0, 'entries': 0, 'blocked_reward_cost': 0,
                   'blocked_risk_halt': 0, 'blocked_open_position': 0}

    def close_position(price, ts, reason):
        nonlocal cash, pos
        side = pos['side']
        exit_fill = price * (1 - side * slip)
        gross = side * (exit_fill - pos['entry']) * pos['qty']
        fees = pos['entry_fee_paid'] + exit_fill * pos['qty'] * fee
        pnl = gross - fees
        cash += pnl
        trades.append({
            'opened_at': pos['opened_at'], 'closed_at': ts, 'side': 'LONG' if side == 1 else 'SHORT',
            'entry': pos['entry'], 'exit': exit_fill, 'pnl': pnl, 'gross_pnl': gross, 'fees': fees,
            'r_multiple': pnl / pos['initial_risk_usd'], 'reason': reason, 'setup_id': pos.get('setup_id'),
        })
        pos = None

    for i, ts in enumerate(idx):
        price = mid.iloc[i]
        current_day = ts.date()
        if current_day != day:
            day = current_day
            day_start_equity = cash
            day_blocked = False

        if not np.isfinite(price):
            continue

        # ---- manage open position ----
        if pos is not None:
            side = pos['side']
            bars_held = i - pos['entry_i']
            if side == 1:
                pos['peak'] = max(pos['peak'], price)
            else:
                pos['peak'] = min(pos['peak'], price)
            r_now = side * (price - pos['entry']) / pos['unit_risk']

            if r_now >= config.partial_r and not pos['trailing_active']:
                pos['trailing_active'] = True
                pos['stop'] = pos['entry']  # breakeven

            if pos['trailing_active']:
                trail_stop = pos['peak'] - side * config.trail_mult * pos['vol_unit']
                if side == 1:
                    pos['stop'] = max(pos['stop'], trail_stop)
                else:
                    pos['stop'] = min(pos['stop'], trail_stop)

            hit_stop = (side == 1 and price <= pos['stop']) or (side == -1 and price >= pos['stop'])
            hit_target = r_now >= config.target_r
            timed_out = bars_held >= config.max_hold_bars

            if hit_stop:
                close_position(pos['stop'], ts, 'STOP')
            elif hit_target:
                close_position(price, ts, 'TARGET')
            elif timed_out:
                close_position(price, ts, 'TIME')

        # ---- consider new entry ----
        signal = signal_by_ts.get(ts)
        if signal is None:
            continue
        diagnostics['signals'] += 1
        if pos is not None:
            diagnostics['blocked_open_position'] += 1
            continue
        if day_blocked:
            diagnostics['blocked_risk_halt'] += 1
            continue

        side = signal['side']
        entry = price * (1 + side * slip)
        stop = signal['stop']
        risk = side * (entry - stop)
        if risk <= 0:
            continue
        reward = config.target_r * risk
        cost = entry * (fee + fee + slip + slip)
        if reward < config.min_reward_cost_ratio * cost:
            diagnostics['blocked_reward_cost'] += 1
            continue

        risk_usd = min(cash * config.risk_fraction, config.fixed_risk_usd)
        qty = risk_usd / risk
        notional = qty * entry
        margin = notional / config.leverage
        if margin > cash * config.max_margin_fraction:
            qty = (cash * config.max_margin_fraction * config.leverage) / entry
            risk_usd = qty * risk

        entry_fee_paid = entry * qty * fee
        pos = {
            'side': side, 'entry': entry, 'qty': qty, 'stop': stop, 'peak': entry,
            'unit_risk': risk, 'vol_unit': signal.get('vol_unit', risk),
            'initial_risk_usd': risk_usd, 'entry_fee_paid': entry_fee_paid,
            'entry_i': i, 'opened_at': ts, 'trailing_active': False, 'setup_id': signal.get('setup_id'),
        }
        diagnostics['entries'] += 1

        if (day_start_equity - cash) >= config.daily_loss_fraction * day_start_equity:
            day_blocked = True

    if pos is not None:
        close_position(mid.iloc[-1], idx[-1], 'END_OF_TEST')

    pnls = np.array([t['pnl'] for t in trades])
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    return {
        'trades': trades,
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': (gains / losses) if losses else (None if gains == 0 else float('inf')),
            'net_pnl': float(cash - initial_capital),
            'mean_net_r': float(np.mean([t['r_multiple'] for t in trades])) if trades else 0.0,
            'diagnostics': diagnostics,
        },
    }
