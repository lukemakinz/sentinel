"""One-account 5m replay for low-turnover futures swing strategies."""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SwingExecutionConfig:
    exit_policy: str
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    leverage: float = 5.0
    risk_fraction: float = 0.002
    fixed_risk_usd: float = 0.50
    max_notional_equity: float = 0.50
    max_margin_fraction: float = 0.10
    margin_safety_reserve: float = 0.01
    min_stop_atr: float = 1.5
    max_stop_atr: float = 2.5
    breakeven_trigger_r: float = 1.5
    chandelier_trigger_r: float = 2.0
    chandelier_atr: float = 2.5
    max_hold_days: int = 30
    daily_loss_fraction: float = 0.006
    weekly_loss_fraction: float = 0.018

    def __post_init__(self):
        if self.exit_policy not in (
            'initial_sl_only', 'delayed_cost_be', 'delayed_cost_be_chandelier',
        ):
            raise ValueError('Unknown exit policy')
        if (self.fee_bps < 0 or self.slippage_bps < 0
                or not 1 <= self.leverage <= 5
                or not 0 < self.risk_fraction < 1
                or self.fixed_risk_usd <= 0
                or self.max_notional_equity <= 0
                or not 0 < self.max_margin_fraction <= 1
                or not 0 <= self.margin_safety_reserve < 1 / self.leverage
                or not 0 < self.min_stop_atr <= self.max_stop_atr
                or self.breakeven_trigger_r <= 0
                or self.chandelier_trigger_r < self.breakeven_trigger_r
                or self.chandelier_atr <= 0 or self.max_hold_days <= 0):
            raise ValueError('Invalid swing execution configuration')


def _utc(timestamp) -> pd.Timestamp:
    value = pd.Timestamp(timestamp)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _validate_five_minutes(frame: pd.DataFrame) -> None:
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError('Empty, duplicate or unsorted 5m data')
    if not (frame.index.to_series().diff().dropna() == pd.Timedelta(minutes=5)).all():
        raise ValueError('Missing 5m execution candles')
    values = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Invalid execution prices')
    if ((frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError('Malformed execution OHLC')


def _is_synthetic(row) -> bool:
    """Return whether a regularized row is MTM-only, never executable."""
    return bool(getattr(row, 'synthetic', False))


def _cost_breakeven_trigger(entry: float, side: int, fee: float, slip: float) -> float:
    """Trigger whose adverse exit fill covers both market fees and slippage."""
    if side == 1:
        return entry * (1 + fee) / ((1 - slip) * (1 - fee))
    return entry * (1 - fee) / ((1 + slip) * (1 + fee))


def execute_swing_portfolio(
    markets: dict,
    entries_by_symbol: dict,
    exits_by_symbol: dict,
    management_by_symbol: dict,
    config: SwingExecutionConfig,
    start,
    end,
    initial_capital: float = 250.0,
    symbol_priority=(),
) -> dict:
    """Replay one cash balance and at most one position across all symbols."""
    start, end = _utc(start), _utc(end)
    symbols = tuple(markets)
    priority = {symbol: rank for rank, symbol in enumerate(symbol_priority or symbols)}
    data, rates = {}, {}
    expected_index = None
    for symbol in symbols:
        frame, funding = markets[symbol]
        frame = frame.loc[(frame.index >= start) & (frame.index < end)]
        _validate_five_minutes(frame)
        if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=5) != end:
            raise ValueError(f'Incomplete execution period for {symbol}')
        if expected_index is None:
            expected_index = frame.index
        elif not expected_index.equals(frame.index):
            raise ValueError('Market execution indices are not aligned')
        data[symbol] = frame
        rates[symbol] = funding.to_dict()

    entry_map, exit_map = {}, {}
    for symbol, records in entries_by_symbol.items():
        for record in records:
            if start <= record['timestamp'] < end:
                entry_map.setdefault(record['timestamp'], []).append((symbol, record))
    for timestamp, records in entry_map.items():
        records.sort(key=lambda item: (
            -item[1].get('score', 0), priority.get(item[0], len(priority))))
    for symbol, records in exits_by_symbol.items():
        for record in records:
            if start <= record['timestamp'] < end:
                exit_map.setdefault(record['timestamp'], []).append((symbol, record))
    management = {
        symbol: frame.to_dict('index') for symbol, frame in management_by_symbol.items()
    }

    fee = config.fee_bps / 10000
    slip = config.slippage_bps / 10000
    cash = float(initial_capital)
    position = None
    trades, equity, daily_equity = [], [], {}
    diagnostics = Counter()
    day = week = None
    day_cash = week_cash = cash
    day_blocked = week_blocked = drawdown_halted = False
    peak_equity = cash

    def marked(rows, field='close'):
        if position is None:
            return cash
        raw = float(getattr(rows[position['symbol']], field))
        fill = raw * (1 - position['side'] * slip)
        return cash + position['qty'] * (
            position['side'] * (fill - position['entry']) - fill * fee)

    def close_position(raw_price, timestamp, reason):
        nonlocal cash, position
        fill = float(raw_price) * (1 - position['side'] * slip)
        exit_fee = fill * position['qty'] * fee
        gross = position['side'] * (fill - position['entry']) * position['qty']
        cash += gross - exit_fee
        position['fees'] += exit_fee
        position['gross_pnl'] += gross
        pnl = cash - position['cash_before']
        trades.append({
            'symbol': position['symbol'],
            'opened_at': str(position['opened_at']),
            'closed_at': str(timestamp),
            'side': 'LONG' if position['side'] == 1 else 'SHORT',
            'entry': position['entry'],
            'initial_stop': position['initial_stop'],
            'final_stop': position['stop'],
            'quantity': position['qty'],
            'pnl': pnl,
            'gross_pnl': position['gross_pnl'],
            'fees': position['fees'],
            'funding_pnl': position['funding_pnl'],
            'initial_risk': position['initial_risk'],
            'r_multiple': pnl / position['initial_risk'],
            'initial_margin': position['initial_margin'],
            'signal_risk_scale': position['signal_risk_scale'],
            'exit_policy': config.exit_policy,
            'setup': position['setup'],
            'setup_id': position.get('setup_id'),
            'evidence': position.get('evidence'),
            'reason': reason,
            'stop_updates': position['stop_updates'],
        })
        position = None

    def enter(symbol, signal, row, timestamp, risk_scale):
        nonlocal cash, position
        side = int(signal['side'])
        signal_risk_scale = float(signal.get('risk_scale', 1.0))
        if (not np.isfinite(signal_risk_scale)
                or not 0 < signal_risk_scale <= 1.0):
            diagnostics['blocked_invalid_signal_risk_scale'] += 1
            return False
        entry = float(row.open) * (1 + side * slip)
        stop = float(signal['stop'])
        atr = float(signal['atr'])
        price_risk = side * (entry - stop)
        if (not np.isfinite(price_risk) or price_risk <= 0
                or price_risk < config.min_stop_atr * atr
                or price_risk > config.max_stop_atr * atr):
            diagnostics['blocked_stop_width_or_gap'] += 1
            return False
        if (config.leverage > 1
                and 2 * (price_risk / entry + fee + slip)
                > 1 / config.leverage - config.margin_safety_reserve):
            diagnostics['blocked_margin_stop_buffer'] += 1
            return False
        stop_fill = stop * (1 - side * slip)
        unit_loss = side * (entry - stop_fill) + fee * (entry + stop_fill)
        risk_budget = (
            min(cash * config.risk_fraction, config.fixed_risk_usd)
            * risk_scale * signal_risk_scale)
        margin_budget = cash * config.max_margin_fraction
        qty = min(
            risk_budget / unit_loss,
            cash * config.max_notional_equity / entry,
            margin_budget * config.leverage / entry,
            cash / (entry * (1 / config.leverage + fee)),
        )
        if not np.isfinite(qty) or qty <= 0:
            diagnostics['blocked_size'] += 1
            return False
        entry_fee = entry * qty * fee
        target_price = signal.get('target_price')
        if target_price is None and signal.get('target_r') is not None:
            target_price = entry + side * float(signal['target_r']) * price_risk
        if target_price is not None:
            achieved_target_r = side * (float(target_price) - entry) / price_risk
            if (not np.isfinite(achieved_target_r)
                    or achieved_target_r < float(signal.get('min_target_r', 0.0))):
                diagnostics['blocked_target_space_after_fill'] += 1
                return False
        position = {
            'symbol': symbol, 'side': side, 'entry': entry,
            'stop': stop, 'initial_stop': stop, 'price_r': price_risk,
            'qty': qty, 'initial_risk': qty * unit_loss,
            'initial_margin': qty * entry / config.leverage,
            'cash_before': cash, 'opened_at': timestamp,
            'fees': entry_fee, 'gross_pnl': 0.0, 'funding_pnl': 0.0,
            'best': entry, 'setup': signal['setup'],
            'setup_id': signal.get('setup_id'), 'evidence': signal.get('evidence'),
            'target_price': target_price,
            'signal_risk_scale': signal_risk_scale,
            'max_hold_minutes': signal.get(
                'max_hold_minutes', config.max_hold_days * 24 * 60),
            'time_reason': ('TIME' if signal.get('max_hold_minutes') is not None
                            else f'TIME_{config.max_hold_days}D'),
            'stop_updates': [],
        }
        cash -= entry_fee
        diagnostics['entries'] += 1
        diagnostics[f'entries_{symbol}'] += 1
        return True

    iterators = [data[symbol].itertuples() for symbol in symbols]
    for rows_tuple in zip(*iterators):
        rows = {symbol: row for symbol, row in zip(symbols, rows_tuple)}
        timestamp = rows_tuple[0].Index
        if any(row.Index != timestamp for row in rows_tuple[1:]):
            raise ValueError('Market iterators diverged')
        close_time = timestamp + pd.Timedelta(minutes=5)
        current_day = timestamp.date()
        iso = timestamp.isocalendar()
        current_week = (iso.year, iso.week)
        if current_day != day:
            day, day_cash, day_blocked = current_day, cash, False
        if current_week != week:
            week, week_cash, week_blocked = current_week, cash, False

        if position is not None and timestamp in rates[position['symbol']]:
            row = rows[position['symbol']]
            payment = (-position['side'] * position['qty'] * row.open
                       * rates[position['symbol']][timestamp])
            cash += payment
            position['funding_pnl'] += payment

        closed_at_open = False
        if position is not None:
            row = rows[position['symbol']]
            side, stop = position['side'], position['stop']
            open_through_stop = (
                not _is_synthetic(row)
                and (row.open <= stop if side == 1 else row.open >= stop)
            )
            if open_through_stop:
                close_position(row.open, timestamp, 'STOP_GAP')
                closed_at_open = True

        if position is not None:
            for symbol, event in exit_map.get(timestamp, []):
                if (symbol == position['symbol']
                        and not _is_synthetic(rows[symbol])
                        and event['position_side'] == position['side']):
                    close_position(rows[symbol].open, timestamp, event['reason'])
                    closed_at_open = True
                    break

        open_equity = marked(rows, 'open')
        open_drawdown = 1 - open_equity / max(peak_equity, 1e-12)
        risk_scale = 0.5 if open_drawdown >= 0.04 else 1.0
        if open_drawdown >= 0.06:
            drawdown_halted = True

        candidates = entry_map.get(timestamp, [])
        diagnostics['signals'] += len(candidates)
        if candidates and position is not None:
            diagnostics['blocked_open_position'] += len(candidates)
        elif candidates and closed_at_open:
            diagnostics['blocked_same_bar_reentry'] += len(candidates)
        elif candidates and (day_blocked or week_blocked or drawdown_halted or cash <= 0):
            diagnostics['blocked_risk_halt_or_capital'] += len(candidates)
        elif candidates:
            for symbol, signal in candidates:
                if _is_synthetic(rows[symbol]):
                    diagnostics['blocked_synthetic_entry'] += 1
                    continue
                if enter(symbol, signal, rows[symbol], timestamp, risk_scale):
                    break

        if position is not None:
            row = rows[position['symbol']]
            side, stop = position['side'], position['stop']
            hit = (not _is_synthetic(row)
                   and (row.low <= stop if side == 1 else row.high >= stop))
            if hit:
                close_position(stop, close_time, 'STOP')
            elif (position['target_price'] is not None
                  and not _is_synthetic(row)
                  and (row.high >= float(position['target_price']) if side == 1
                       else row.low <= float(position['target_price']))):
                close_position(float(position['target_price']), close_time, 'TARGET')
            elif (not _is_synthetic(row)
                  and close_time - position['opened_at'] >= pd.Timedelta(
                      minutes=position['max_hold_minutes'])):
                close_position(row.close, close_time, position['time_reason'])

        # Management uses only a just-completed 4h candle and activates for
        # the following 5m candle.  It can never rescue this candle's old stop.
        if position is not None:
            bar = management.get(position['symbol'], {}).get(close_time)
            if bar is not None and np.isfinite(bar.get('atr', np.nan)):
                side = position['side']
                position['best'] = (max(position['best'], float(bar['high'])) if side == 1
                                    else min(position['best'], float(bar['low'])))
                price_r = side * (float(bar['close']) - position['entry']) / position['price_r']
                old_stop = position['stop']
                candidates_stop = [old_stop]
                reasons = []
                if (config.exit_policy != 'initial_sl_only'
                        and price_r >= config.breakeven_trigger_r):
                    candidates_stop.append(_cost_breakeven_trigger(
                        position['entry'], side, fee, slip))
                    reasons.append('COST_BE')
                if (config.exit_policy == 'delayed_cost_be_chandelier'
                        and price_r >= config.chandelier_trigger_r):
                    candidates_stop.append(
                        position['best'] - side * config.chandelier_atr * float(bar['atr']))
                    reasons.append('CHANDELIER_2_5ATR')
                new_stop = max(candidates_stop) if side == 1 else min(candidates_stop)
                if side * (new_stop - old_stop) > 1e-12:
                    position['stop'] = new_stop
                    position['stop_updates'].append({
                        'computed_at': str(close_time),
                        'active_from': str(close_time),
                        'old_stop': old_stop,
                        'new_stop': new_stop,
                        'closed_bar_r': price_r,
                        'reasons': reasons,
                    })

        if cash <= day_cash * (1 - config.daily_loss_fraction):
            day_blocked = True
        if cash <= week_cash * (1 - config.weekly_loss_fraction):
            week_blocked = True

        current_equity = marked(rows)
        if close_time == end and position is not None:
            close_position(rows[position['symbol']].close, close_time, 'END_OF_TEST')
            current_equity = cash
        peak_equity = max(peak_equity, current_equity)
        equity.append(current_equity)
        daily_equity[str(day)] = current_equity

    pnls = np.asarray([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.r_[initial_capital, equity]
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    per_symbol = {}
    for symbol in symbols:
        selected = np.asarray(
            [trade['pnl'] for trade in trades if trade['symbol'] == symbol], dtype=float)
        per_symbol[symbol] = {
            'trades': int(len(selected)),
            'net_pnl': float(selected.sum()) if len(selected) else 0.0,
            'gross_profit': float(selected[selected > 0].sum()) if len(selected) else 0.0,
        }
    return {
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()),
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else (None if gains == 0 else 'Infinity'),
            'net_pnl': cash - initial_capital,
            'return_pct': (cash / initial_capital - 1) * 100,
            'max_drawdown_pct': float(drawdowns.max()),
            'mean_net_r': float(np.mean([x['r_multiple'] for x in trades])) if trades else 0.0,
            'fees': float(sum(x['fees'] for x in trades)),
            'funding_pnl': float(sum(x['funding_pnl'] for x in trades)),
            'per_symbol': per_symbol,
            'represented_symbols': sum(row['trades'] > 0 for row in per_symbol.values()),
            'diagnostics': dict(diagnostics),
            'drawdown_halted': drawdown_halted,
        },
        'trades': trades,
        'daily_equity': daily_equity,
        'equity_daily': [
            {'timestamp': timestamp, 'equity': value}
            for timestamp, value in daily_equity.items()
        ],
    }
