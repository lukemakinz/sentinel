"""Single-account minute replay for a correlated multi-symbol scalp cluster."""
from collections import Counter

import numpy as np
import pandas as pd

from .scalp_data import validate_minutes


def execute_cluster(
    markets,
    signals_by_symbol,
    config,
    start,
    end,
    initial_capital=250.0,
    symbol_priority=(),
):
    """Replay one global cash balance, pending order and up to N positions.

    ``markets`` maps symbol to ``(one_minute_frame, funding_series)``.  Signals
    at one timestamp are ranked only by their predeclared score and symbol
    priority; an ineligible candidate falls through to the next candidate.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    symbols = tuple(markets)
    priority = {symbol: rank for rank, symbol in enumerate(symbol_priority or symbols)}
    data, rates = {}, {}
    expected_index = None
    for symbol in symbols:
        frame, funding = markets[symbol]
        frame = frame.loc[(frame.index >= start) & (frame.index < end)]
        validate_minutes(frame)
        if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=1) != end:
            raise ValueError(f'Incomplete execution period for {symbol}')
        if expected_index is None:
            expected_index = frame.index
        elif not frame.index.equals(expected_index):
            raise ValueError('Cluster minute indices are not aligned')
        data[symbol] = frame
        rates[symbol] = funding.to_dict()

    signal_map = {}
    for symbol, signals in signals_by_symbol.items():
        for signal in signals:
            timestamp = signal['timestamp']
            if start <= timestamp < end:
                signal_map.setdefault(timestamp, []).append((symbol, signal))
    for timestamp in signal_map:
        signal_map[timestamp].sort(
            key=lambda item: (-item[1].get('score', 0), priority.get(item[0], len(priority))))

    if config.trailing and config.partial_fraction:
        raise ValueError(
            'execute_cluster trailing does not reduce position size; '
            'use partial_fraction=0 (partial_r only gates breakeven/trail activation)')

    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000
    cash, pending = float(initial_capital), None
    positions = {}
    trades, equity, diagnostics = [], [], Counter()
    day = week = None
    day_equity = week_equity = cash
    day_blocked = week_blocked = drawdown_halted = False
    peak_equity = cash
    daily_equity = {}
    consecutive_losses = 0
    consecutive_short_losses = 0
    max_positions = config.max_positions

    def marked(rows, field='close'):
        total = cash
        for pos in positions.values():
            price = getattr(rows[pos['symbol']], field)
            exit_fill = price * (1 - pos['side'] * slip)
            total += pos['qty'] * (
                pos['side'] * (exit_fill - pos['entry']) - exit_fill * fee)
        return total

    def close_position(symbol, price, timestamp, reason):
        nonlocal cash, consecutive_losses, consecutive_short_losses
        pos = positions.pop(symbol)
        fill = price * (1 - pos['side'] * slip)
        exit_fee = fill * pos['qty'] * fee
        gross = pos['side'] * (fill - pos['entry']) * pos['qty']
        cash += gross - exit_fee
        pos['fees'] += exit_fee
        pos['gross_pnl'] += gross
        pnl = pos['gross_pnl'] + pos['funding_pnl'] - pos['fees']
        closed_side = pos['side']
        trades.append({
            'symbol': pos['symbol'],
            'opened_at': str(pos['opened_at']),
            'closed_at': str(timestamp),
            'side': 'LONG' if pos['side'] == 1 else 'SHORT',
            'entry': pos['entry'],
            'initial_stop': pos['initial_stop'],
            'quantity': pos.get('initial_qty', pos['qty']),
            'pnl': pnl,
            'leverage': config.leverage,
            'initial_margin': pos['initial_margin'],
            'margin_return_pct': pnl / pos['initial_margin'] * 100,
            'gross_pnl': pos['gross_pnl'],
            'fees': pos['fees'],
            'funding_pnl': pos['funding_pnl'],
            'r_multiple': pnl / pos['initial_risk'],
            'setup': pos['setup'],
            'setup_id': pos.get('setup_id'),
            'evidence': pos.get('evidence'),
            'score': pos['score'],
            'reason': reason,
            'exits': pos.get('exits', []) + [{
                'timestamp': str(timestamp), 'price': fill,
                'quantity': pos['qty'], 'reason': reason,
            }],
        })
        if pnl < 0:
            consecutive_losses += 1
            if closed_side == -1:
                consecutive_short_losses += 1
        else:
            consecutive_losses = 0
            if closed_side == -1:
                consecutive_short_losses = 0

    def try_entry(symbol, signal, row, timestamp, risk_scale):
        nonlocal cash
        if symbol in positions or len(positions) >= max_positions:
            diagnostics['blocked_open_position'] += 1
            return False
        side = signal['side']
        halt_n = config.consecutive_loss_halt
        if halt_n:
            all_blocked = (
                config.consecutive_loss_halt_side == 'all'
                and consecutive_losses >= halt_n)
            short_blocked = (
                config.consecutive_loss_halt_side == 'short'
                and side == -1
                and consecutive_short_losses >= halt_n)
            if all_blocked or short_blocked:
                diagnostics['blocked_consecutive_loss_halt'] += 1
                return False
        is_limit = signal.get('limit_price') is not None
        entry_fee = config.maker_fee_bps / 10000 if is_limit else fee
        entry = signal['limit_price'] if is_limit else row.open * (1 + side * slip)
        risk = side * (entry - signal['stop'])
        target = signal.get('target_price', entry + side * config.target_r * risk)
        reward = side * (target - entry)
        estimated_cost = entry * (entry_fee + fee + slip + (0 if is_limit else slip))
        boundary = signal.get('target_boundary')
        boundary_ok = boundary is None or side * (boundary - entry) >= reward
        minimum = signal.get('min_stop_atr', 0.5) * signal['atr']
        maximum = signal.get('max_stop_atr', 3.0) * signal['atr']
        if risk <= 0 or risk < minimum or risk > maximum:
            diagnostics['blocked_stop_width_or_gap'] += 1
            return False
        if (not boundary_ok or reward < config.min_reward_cost_ratio * estimated_cost
                or reward < signal.get('min_target_r', 0) * risk):
            diagnostics['blocked_reward_cost_or_target'] += 1
            return False
        if (config.leverage > 1
                and 2 * (risk / entry + fee + slip)
                > 1 / config.leverage - config.margin_safety_reserve):
            diagnostics['blocked_margin_stop_buffer'] += 1
            return False
        if signal.get('partial_price') is not None and config.trailing:
            raise ValueError('Per-signal partial exits require trailing=False')
        stop_fill = signal['stop'] * (1 - side * slip)
        unit_loss = side * (entry - stop_fill) + entry_fee * entry + fee * stop_fill
        signal_scale = float(signal.get('risk_scale', 1.0))
        risk_budget = min(cash * config.risk_fraction,
                          config.fixed_risk_usd or float('inf')) * risk_scale * signal_scale
        margin_budget = min(cash * config.max_margin_fraction,
                            config.fixed_margin_usd or float('inf'))
        qty = min(
            risk_budget / unit_loss,
            cash * config.max_notional_equity / entry,
            margin_budget * config.leverage / entry,
            cash / (entry * (1 / config.leverage + entry_fee)),
        )
        target_fill = target * (1 - side * slip)
        projected = qty * (
            side * (target_fill - entry) - entry_fee * entry - fee * target_fill)
        if qty <= 0 or projected < signal.get('min_profit_usd', 0):
            diagnostics['blocked_dollar_profit_target'] += 1
            return False
        pos = {
            'symbol': symbol, 'side': side, 'entry': entry, 'stop': signal['stop'],
            'initial_stop': signal['stop'], 'r': risk, 'qty': qty,
            'target_price': target, 'initial_risk': qty * unit_loss,
            'initial_margin': qty * entry / config.leverage,
            'cash_before': cash, 'opened_at': timestamp, 'atr': signal['atr'],
            'fees': entry * qty * entry_fee, 'gross_pnl': 0.0, 'funding_pnl': 0.0,
            'limit_fill_bar': timestamp if is_limit else None,
            'setup': signal['setup'], 'setup_id': signal.get('setup_id'),
            'evidence': signal.get('evidence'), 'score': signal['score'],
            'best': entry, 'partial_hit': False,
            'initial_qty': qty, 'exits': [],
            'partial_price': signal.get('partial_price'),
            'partial_fraction': float(signal.get('partial_fraction', 0.0)),
            'partial_taken': False,
        }
        cash -= pos['fees']
        positions[symbol] = pos
        diagnostics['entries'] += 1
        diagnostics[f'entries_{symbol}'] += 1
        return True

    def take_partial(pos, price, timestamp):
        """Scale out at a fixed level; the stop is left untouched."""
        nonlocal cash
        quantity = pos['qty'] * pos['partial_fraction']
        fill = price * (1 - pos['side'] * slip)
        gross = pos['side'] * (fill - pos['entry']) * quantity
        exit_fee = fill * quantity * fee
        cash += gross - exit_fee
        pos['qty'] -= quantity
        pos['gross_pnl'] += gross
        pos['fees'] += exit_fee
        pos['partial_taken'] = True
        pos['exits'].append({
            'timestamp': str(timestamp), 'price': fill,
            'quantity': quantity, 'reason': 'PARTIAL',
        })
        diagnostics['partial_exits'] += 1

    def manage_position(symbol, row, timestamp, close_time):
        pos = positions[symbol]
        side, stop = pos['side'], pos['stop']
        stop_hit = row.low <= stop if side == 1 else row.high >= stop
        if stop_hit:
            price = min(row.open, stop) if side == 1 else max(row.open, stop)
            close_position(symbol, price, close_time, 'STOP')
            return
        target = pos['target_price']
        extreme = row.high if side == 1 else row.low
        can_take_profit = pos.get('limit_fill_bar') != timestamp
        partial = pos.get('partial_price')
        if (partial is not None and not pos['partial_taken'] and can_take_profit
                and side * (extreme - partial) >= 0):
            take_partial(pos, partial, close_time)
        if can_take_profit and side * (extreme - target) >= 0:
            close_position(symbol, target, close_time, 'TARGET')
        elif (close_time - pos['opened_at']).total_seconds() / 60 >= config.max_hold_minutes:
            close_position(symbol, row.close, close_time, 'TIME')
        elif config.trailing:
            partial_level = pos['entry'] + side * config.partial_r * pos['r']
            if not pos['partial_hit'] and side * (extreme - partial_level) >= 0:
                pos['partial_hit'] = True
            if pos['partial_hit']:
                pos['best'] = max(pos['best'], extreme) if side == 1 else min(pos['best'], extreme)
                breakeven = pos['entry'] * (1 + side * 2 * (fee + slip))
                if config.dollar_ratchet:
                    open_usd = pos['qty'] * side * (pos['best'] - pos['entry'])
                    if open_usd > 0:
                        locked = config.dollar_ratchet_lock_fraction * open_usd
                        trail = pos['entry'] + side * (locked / pos['qty'])
                    else:
                        trail = breakeven
                else:
                    trail = pos['best'] - side * config.trail_atr * pos['atr']
                pos['stop'] = max(stop, breakeven, trail) if side == 1 else min(stop, breakeven, trail)

    iterators = [data[symbol].itertuples() for symbol in symbols]
    for rows_tuple in zip(*iterators):
        rows = {symbol: row for symbol, row in zip(symbols, rows_tuple)}
        timestamp = rows_tuple[0].Index
        if any(row.Index != timestamp for row in rows_tuple[1:]):
            raise ValueError('Cluster iterator timestamps diverged')
        close_time = timestamp + pd.Timedelta(minutes=1)
        current_day = timestamp.date()
        iso = timestamp.isocalendar()
        current_week = (iso.year, iso.week)
        if current_day != day:
            day = current_day
            # The risk anchor belongs to the previous completed minute.  Using
            # the new day's open would absorb a boundary gap into the anchor
            # and hide that loss from the daily stop.
            day_equity = equity[-1] if equity else cash
            day_blocked = False
            consecutive_losses = 0
            consecutive_short_losses = 0
        if current_week != week:
            week = current_week
            week_equity = equity[-1] if equity else cash
            week_blocked = False

        for pos in positions.values():
            if timestamp in rates[pos['symbol']]:
                row = rows[pos['symbol']]
                payment = -pos['side'] * pos['qty'] * row.open * rates[pos['symbol']][timestamp]
                cash += payment
                pos['funding_pnl'] += payment

        open_equity = marked(rows, 'open')
        open_drawdown = 1 - open_equity / max(peak_equity, 1e-12)
        risk_scale = 0.5 if open_drawdown >= config.drawdown_risk_scale_fraction else 1.0
        if open_drawdown >= config.drawdown_halt_fraction:
            drawdown_halted = True
            if pending is not None:
                diagnostics['cancelled_drawdown_halt'] += 1
                pending = None

        fill_candidate = None
        if pending is not None:
            if timestamp >= pending['expires'] or day_blocked or week_blocked or drawdown_halted:
                diagnostics['expired_or_cancelled_limit'] += 1
                pending = None
            else:
                row = rows[pending['symbol']]
                penetration = config.limit_penetration_bps / 10000
                threshold = pending['limit_price'] * (1 - pending['side'] * penetration)
                touched = row.low <= threshold if pending['side'] == 1 else row.high >= threshold
                if touched:
                    fill_candidate, pending = pending, None

        candidates = signal_map.get(timestamp, [])
        diagnostics['signals'] += len(candidates)
        if candidates and fill_candidate is not None:
            diagnostics['blocked_pending_order'] += len(candidates)
        elif candidates and pending is not None:
            diagnostics['blocked_pending_order'] += len(candidates)
        elif candidates and (day_blocked or week_blocked or drawdown_halted or cash <= 0):
            diagnostics['blocked_risk_halt_or_capital'] += len(candidates)
        elif fill_candidate is None:
            if config.flip_on_opposite_signal:
                for symbol, signal in candidates:
                    held = positions.get(symbol)
                    if held is not None and held['side'] != signal['side']:
                        close_position(symbol, rows[symbol].open, timestamp, 'FLIP')
            for symbol, signal in candidates:
                held = positions.get(symbol)
                if held is not None and held['side'] == signal['side']:
                    diagnostics['held_same_side'] += 1
                    continue
                if symbol in positions or len(positions) >= max_positions:
                    diagnostics['blocked_open_position'] += 1
                    continue
                row = rows[symbol]
                if signal.get('limit_price') is not None:
                    if signal['side'] * (row.open - signal['limit_price']) <= 0:
                        diagnostics['blocked_marketable_limit'] += 1
                        continue
                    pending = {
                        **signal, 'symbol': symbol,
                        'expires': timestamp + pd.Timedelta(
                            minutes=signal.get('limit_ttl_minutes', 15)),
                    }
                    penetration = config.limit_penetration_bps / 10000
                    threshold = signal['limit_price'] * (1 - signal['side'] * penetration)
                    touched = row.low <= threshold if signal['side'] == 1 else row.high >= threshold
                    if touched:
                        fill_candidate, pending = pending, None
                    break
                if try_entry(symbol, signal, row, timestamp, risk_scale):
                    if len(positions) >= max_positions:
                        break

        if fill_candidate is not None and fill_candidate['symbol'] not in positions:
            try_entry(fill_candidate['symbol'], fill_candidate,
                      rows[fill_candidate['symbol']], timestamp, risk_scale)

        for symbol in list(positions):
            manage_position(symbol, rows[symbol], timestamp, close_time)

        current_equity = marked(rows)
        if current_equity <= day_equity * (1 - config.daily_loss_fraction):
            day_blocked = True
            if pending is not None:
                diagnostics['cancelled_daily_stop'] += 1
                pending = None
            for symbol in list(positions):
                close_position(symbol, rows[symbol].close, close_time, 'DAILY_LOSS')
            current_equity = cash
        if current_equity <= week_equity * (1 - config.weekly_loss_fraction):
            week_blocked = True
            if pending is not None:
                diagnostics['cancelled_weekly_stop'] += 1
                pending = None
            for symbol in list(positions):
                close_position(symbol, rows[symbol].close, close_time, 'WEEKLY_LOSS')
            current_equity = cash
        if close_time == end:
            for symbol in list(positions):
                close_position(symbol, rows[symbol].close, close_time, 'END_OF_TEST')
            current_equity = cash
        peak_equity = max(peak_equity, current_equity)
        equity.append(current_equity)
        daily_equity[str(day)] = current_equity

    values = np.r_[initial_capital, equity]
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    pnls = np.array([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    per_symbol = {}
    per_month = {}
    for symbol in symbols:
        selected = np.array([trade['pnl'] for trade in trades if trade['symbol'] == symbol])
        per_symbol[symbol] = {
            'trades': int(len(selected)),
            'net_pnl': float(selected.sum()) if len(selected) else 0.0,
            'gross_profit': float(selected[selected > 0].sum()) if len(selected) else 0.0,
        }
    for trade in trades:
        month = str(pd.Timestamp(trade['opened_at']).tz_localize(None).to_period('M'))
        record = per_month.setdefault(month, {'trades': 0, 'pnl': 0.0})
        record['trades'] += 1
        record['pnl'] += float(trade['pnl'])
    gross_by_symbol = [row['gross_profit'] for row in per_symbol.values()]
    return {
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()),
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else (None if gains == 0 else 'Infinity'),
            'net_pnl': cash - initial_capital,
            'return_pct': (cash / initial_capital - 1) * 100,
            'max_drawdown_pct': float(drawdowns.max()),
            'mean_net_r': float(np.mean([trade['r_multiple'] for trade in trades])) if trades else 0.0,
            'fees': float(sum(trade['fees'] for trade in trades)),
            'funding_pnl': float(sum(trade['funding_pnl'] for trade in trades)),
            'per_symbol': per_symbol,
            'positive_symbols': sum(row['net_pnl'] > 0 for row in per_symbol.values()),
            'largest_symbol_gross_profit_share_pct': (
                max(gross_by_symbol) / sum(gross_by_symbol) * 100
                if sum(gross_by_symbol) else None
            ),
            'per_month': dict(sorted(per_month.items())),
            'diagnostics': dict(diagnostics),
            'drawdown_halted': drawdown_halted,
        },
        'trades': trades,
        'daily_equity': daily_equity,
        'equity_hourly': [
            {'timestamp': str(expected_index[i] + pd.Timedelta(minutes=1)), 'equity': equity[i]}
            for i in range(0, len(equity), 60)
        ] + [{'timestamp': str(end), 'equity': cash}],
    }
