"""Minute execution replay for S7, independent of the legacy hourly engine."""
from collections import Counter

import numpy as np
import pandas as pd

from .scalp_data import validate_minutes


def execute(minutes, funding, signals, features, config, start, end, initial_capital=10000.0):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    data = minutes.loc[(minutes.index >= start) & (minutes.index < end)]
    validate_minutes(data)
    if data.index[0] != start or data.index[-1] + pd.Timedelta(minutes=1) != end:
        raise ValueError('Incomplete execution period')
    signal_map = {x['timestamp']: x for x in signals if start <= x['timestamp'] < end}
    atr_map = features.atr.to_dict()
    rates = funding.to_dict()
    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000
    cash, pos, pending = float(initial_capital), None, None
    trades, equity, diagnostics = [], [], Counter()
    daily_equity = {}
    day, day_equity, day_blocked = None, cash, False

    def marked(price):
        if pos is None:
            return cash
        exit_fill = price * (1 - pos['side'] * slip)
        return cash + pos['qty'] * (pos['side'] * (exit_fill - pos['entry']) - exit_fill * fee)

    def close_part(price, quantity, timestamp, reason):
        nonlocal cash, pos
        fill = price * (1 - pos['side'] * slip)
        exit_fee = fill * quantity * fee
        gross = pos['side'] * (fill - pos['entry']) * quantity
        cash += gross - exit_fee
        pos['fees'] += exit_fee
        pos['gross_pnl'] += gross
        pos['qty'] -= quantity
        pos['exits'].append({'timestamp': str(timestamp), 'price': fill, 'quantity': quantity, 'reason': reason})
        if pos['qty'] <= pos['initial_qty'] * 1e-9:
            pnl = cash - pos['cash_before']
            trades.append({'opened_at': str(pos['opened_at']), 'closed_at': str(timestamp),
                           'side': 'LONG' if pos['side'] == 1 else 'SHORT',
                           'entry': pos['entry'], 'initial_stop': pos['initial_stop'],
                           'quantity': pos['initial_qty'], 'pnl': pnl,
                           'leverage': config.leverage, 'initial_margin': pos['initial_margin'],
                           'margin_return_pct': pnl / pos['initial_margin'] * 100,
                           'gross_pnl': pos['gross_pnl'], 'fees': pos['fees'],
                           'funding_pnl': pos['funding_pnl'],
                           'r_multiple': pnl / pos['initial_risk'],
                           'setup': pos['setup'], 'setup_id': pos.get('setup_id'),
                           'evidence': pos.get('evidence'), 'score': pos['score'],
                           'reason': reason, 'exits': pos['exits']})
            pos = None

    for row in data.itertuples():
        timestamp = row.Index
        close_time = timestamp + pd.Timedelta(minutes=1)
        if timestamp.date() != day:
            day = timestamp.date()
            day_equity, day_blocked = marked(row.open), False

        # Settlement precedes new entry. Use historical rate and minute open
        # as a documented mark-price proxy; do not fabricate zero funding.
        if pos is not None and timestamp in rates:
            payment = -pos['side'] * pos['qty'] * row.open * rates[timestamp]
            cash += payment
            pos['funding_pnl'] += payment

        new_signal = signal_map.get(timestamp)
        signal = None
        if new_signal is not None:
            diagnostics['signals'] += 1
            if pos is not None:
                diagnostics['blocked_open_position'] += 1
            elif day_blocked or cash <= 0:
                diagnostics['blocked_daily_loss_or_capital'] += 1
            elif pending is not None:
                diagnostics['blocked_pending_order'] += 1
            elif new_signal.get('limit_price') is not None:
                if new_signal['side'] * (row.open - new_signal['limit_price']) <= 0:
                    diagnostics['blocked_marketable_limit'] += 1
                else:
                    pending = {**new_signal, 'expires': timestamp + pd.Timedelta(
                        minutes=new_signal.get('limit_ttl_minutes', 15))}
            else:
                signal = new_signal
        if pending is not None:
            if timestamp >= pending['expires'] or day_blocked:
                diagnostics['expired_limit'] += 1
                pending = None
            else:
                penetration = config.limit_penetration_bps / 10000
                threshold = pending['limit_price'] * (1 - pending['side'] * penetration)
                touched = row.low <= threshold if pending['side'] == 1 else row.high >= threshold
                if touched:
                    signal, pending = pending, None
        if signal is not None and pos is None:
            is_limit = signal.get('limit_price') is not None
            entry_fee = config.maker_fee_bps / 10000 if is_limit else fee
            side = signal['side']
            entry = signal['limit_price'] if is_limit else row.open * (1 + side * slip)
            r = side * (entry - signal['stop'])
            target_price = signal.get('target_price', entry + side * config.target_r * r)
            reward = side * (target_price - entry)
            estimated_cost = entry * (entry_fee + fee + slip + (0 if is_limit else slip))
            boundary = signal.get('target_boundary')
            boundary_ok = boundary is None or side * (boundary - entry) >= reward
            min_stop_atr = signal.get('min_stop_atr', 0.5)
            max_stop_atr = signal.get('max_stop_atr', 3.0)
            if r <= 0 or r < min_stop_atr * signal['atr'] or r > max_stop_atr * signal['atr']:
                diagnostics['blocked_stop_width_or_gap'] += 1
            elif (not boundary_ok or reward < config.min_reward_cost_ratio * estimated_cost
                  or reward < signal.get('min_target_r', 0) * r):
                diagnostics['blocked_reward_cost_or_target'] += 1
            elif config.leverage > 1 and 2 * (r / entry + fee + slip) > 1 / config.leverage - config.margin_safety_reserve:
                # Conservative deposit buffer, NOT an exchange liquidation
                # formula. Exact liquidation needs mark price and risk tiers.
                diagnostics['blocked_margin_stop_buffer'] += 1
            else:
                stop_fill = signal['stop'] * (1 - side * slip)
                unit_loss = side * (entry - stop_fill) + entry_fee * entry + fee * stop_fill
                risk_budget = min(cash * config.risk_fraction, config.fixed_risk_usd or float('inf'))
                margin_budget = min(cash * config.max_margin_fraction, config.fixed_margin_usd or float('inf'))
                qty = min(risk_budget / unit_loss,
                          cash * config.max_notional_equity / entry,
                          margin_budget * config.leverage / entry,
                          cash / (entry * (1 / config.leverage + entry_fee)))
                target_fill = target_price * (1 - side * slip)
                projected_profit = qty * (side * (target_fill - entry) - entry_fee * entry - fee * target_fill)
                if projected_profit < signal.get('min_profit_usd', 0):
                    diagnostics['blocked_dollar_profit_target'] += 1
                else:
                    pos = {'side': side, 'entry': entry, 'stop': signal['stop'],
                           'initial_stop': signal['stop'], 'r': r, 'qty': qty,
                           'target_price': target_price, 'projected_profit': projected_profit,
                           'initial_qty': qty, 'initial_risk': qty * unit_loss,
                           'initial_margin': qty * entry / config.leverage,
                           'cash_before': cash, 'opened_at': timestamp,
                           'partial_hit': False, 'best': entry, 'atr': signal['atr'],
                           'fees': entry * qty * entry_fee, 'gross_pnl': 0.0, 'funding_pnl': 0.0,
                           'limit_fill_bar': timestamp if is_limit else None,
                           'setup': signal['setup'], 'setup_id': signal.get('setup_id'),
                           'evidence': signal.get('evidence'),
                           'score': signal['score'], 'exits': []}
                    cash -= pos['fees']
                    diagnostics['entries'] += 1

        if pos is not None:
            side = pos['side']
            stop = pos['stop']
            # Old stop takes precedence when OHLC cannot resolve SL vs TP.
            stop_hit = row.low <= stop if side == 1 else row.high >= stop
            if stop_hit:
                price = min(row.open, stop) if side == 1 else max(row.open, stop)
                close_part(price, pos['qty'], close_time, 'STOP')
            else:
                partial = pos['entry'] + side * config.partial_r * pos['r']
                target = pos['target_price']
                extreme = row.high if side == 1 else row.low
                # OHLC cannot establish whether the favorable high/low came
                # before an intraminute limit fill. Do not award that profit.
                can_take_profit = pos.get('limit_fill_bar') != timestamp
                if can_take_profit and not pos['partial_hit'] and side * (extreme - partial) >= 0:
                    pos['partial_hit'] = True
                    if config.partial_fraction > 0:
                        close_part(partial, pos['initial_qty'] * config.partial_fraction, close_time, 'PARTIAL')
                if can_take_profit and side * (extreme - target) >= 0:
                    close_part(target, pos['qty'], close_time, 'TARGET')
                elif (close_time - pos['opened_at']).total_seconds() / 60 >= config.max_hold_minutes:
                    close_part(row.close, pos['qty'], close_time, 'TIME')
                elif config.trailing and pos['partial_hit']:
                    # A stop computed from this minute activates NEXT minute.
                    pos['best'] = max(pos['best'], extreme) if side == 1 else min(pos['best'], extreme)
                    latest_atr = atr_map.get(close_time)
                    if latest_atr is not None and np.isfinite(latest_atr):
                        pos['atr'] = latest_atr
                    breakeven = pos['entry'] * (1 + side * 2 * (fee + slip))
                    trail = pos['best'] - side * config.trail_atr * pos['atr']
                    pos['stop'] = max(stop, breakeven, trail) if side == 1 else min(stop, breakeven, trail)

        current_equity = marked(row.close)
        if current_equity <= day_equity * (1 - config.daily_loss_fraction):
            day_blocked = True
            if pos is not None:
                close_part(row.close, pos['qty'], close_time, 'DAILY_LOSS')
                current_equity = cash
        if close_time == end and pos is not None:
            close_part(row.close, pos['qty'], close_time, 'END_OF_TEST')
            current_equity = cash
        equity.append(current_equity)
        daily_equity[str(day)] = current_equity

    values = np.r_[initial_capital, equity]
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    days = (end - start).total_seconds() / 86400
    daily_counts = pd.Series(0, index=pd.date_range(start.floor('D'), end - pd.Timedelta(minutes=1), freq='D'))
    for trade in trades:
        daily_counts.loc[pd.Timestamp(trade['opened_at']).floor('D')] += 1
    pnls = np.array([x['pnl'] for x in trades])
    daily_values = np.r_[initial_capital, list(daily_equity.values())]
    daily_returns = np.diff(daily_values) / daily_values[:-1]
    gains, losses = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
    summary = {'trades': len(trades), 'days': days, 'trades_per_day': len(trades) / days,
               'days_at_least_3_pct': float((daily_counts >= 3).mean() * 100),
               'days_at_least_4_pct': float((daily_counts >= 4).mean() * 100),
               'zero_trade_days': int((daily_counts == 0).sum()),
               'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0,
               'profit_factor': float(gains / losses) if losses else None,
               'net_pnl': cash - initial_capital, 'return_pct': (cash / initial_capital - 1) * 100,
               'max_drawdown_pct': float(drawdowns.max()),
               'mean_net_r': float(np.mean([x['r_multiple'] for x in trades])) if trades else 0,
               'fees': sum(x['fees'] for x in trades),
               'funding_pnl': sum(x['funding_pnl'] for x in trades),
               'gross_pnl_after_slippage': sum(x['gross_pnl'] for x in trades),
               'profitable_days_pct': float((daily_returns > 0).mean() * 100),
               'losing_days_pct': float((daily_returns < 0).mean() * 100),
               'mean_daily_return_pct': float(daily_returns.mean() * 100),
               'worst_day_pct': float(daily_returns.min() * 100),
               'diagnostics': dict(diagnostics)}
    # Full minute equity used for DD; persist hourly samples plus exact end.
    curve = [{'timestamp': str(data.index[i] + pd.Timedelta(minutes=1)), 'equity': equity[i]}
             for i in range(0, len(data), 60)]
    curve.append({'timestamp': str(end), 'equity': cash})
    return {'summary': summary, 'trades': trades, 'equity_hourly': curve,
            'daily_equity': daily_equity,
            'daily_entries': {str(k.date()): int(v) for k, v in daily_counts.items()}}
