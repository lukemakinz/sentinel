"""Single-ledger two-perpetual replay for S96 alt-long/BTC-short pairs."""
from collections import Counter

import numpy as np
import pandas as pd

from .scalp_data import validate_minutes


def execute_residual_pairs(
    markets,
    features_by_symbol,
    signals_by_symbol,
    config,
    start,
    end,
    initial_capital=500.0,
    fee_bps=8.0,
    slippage_bps=5.0,
    symbol_priority=(),
):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    symbols = tuple(markets)
    if 'BTCUSDT' not in symbols:
        raise ValueError('BTCUSDT hedge market is required')
    priority = {symbol: i for i, symbol in enumerate(symbol_priority or symbols)}
    data, rates, arrays = {}, {}, {}
    index = None
    for symbol, (frame, funding) in markets.items():
        frame = frame.loc[(frame.index >= start) & (frame.index < end)]
        validate_minutes(frame)
        if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=1) != end:
            raise ValueError(f'Incomplete execution period for {symbol}')
        if index is None:
            index = frame.index
        elif not frame.index.equals(index):
            raise ValueError('Pair market minute indices diverged')
        data[symbol], rates[symbol] = frame, funding.to_dict()
        arrays[symbol] = {column: frame[column].to_numpy(dtype=float) for column in ('open', 'close')}

    signal_map = {}
    for symbol, signals in signals_by_symbol.items():
        for signal in signals:
            if start <= signal['timestamp'] < end:
                signal_map.setdefault(signal['timestamp'], []).append(signal)
    for timestamp in signal_map:
        signal_map[timestamp].sort(
            key=lambda row: (-row['score'], priority.get(row['symbol'], len(priority))))

    feature_maps = {
        symbol: frame.z.to_dict() for symbol, frame in features_by_symbol.items()
    }
    fee, slip = fee_bps / 10000.0, slippage_bps / 10000.0
    cash, peak, position = float(initial_capital), float(initial_capital), None
    trades, daily_equity, diagnostics = [], {}, Counter()
    halted = False

    def funding_payment(symbol, side, qty, price, timestamp):
        rate = rates[symbol].get(timestamp)
        return 0.0 if rate is None else -side * qty * price * rate

    def mark(i, include_exit_cost=True):
        if position is None:
            return cash
        alt, aq, bq = position['symbol'], position['alt_qty'], position['btc_qty']
        alt_px, btc_px = arrays[alt]['close'][i], arrays['BTCUSDT']['close'][i]
        gross = aq * (alt_px - position['alt_entry']) + bq * (position['btc_entry'] - btc_px)
        exit_cost = fee * (aq * alt_px + bq * btc_px) if include_exit_cost else 0.0
        return cash + gross - exit_cost

    def close(i, timestamp, reason, z_value):
        nonlocal cash, position
        alt = position['symbol']
        alt_fill = arrays[alt]['open'][i] * (1.0 - slip)
        btc_fill = arrays['BTCUSDT']['open'][i] * (1.0 + slip)
        gross = (position['alt_qty'] * (alt_fill - position['alt_entry'])
                 + position['btc_qty'] * (position['btc_entry'] - btc_fill))
        exit_fee = fee * (
            position['alt_qty'] * alt_fill + position['btc_qty'] * btc_fill)
        cash += gross - exit_fee
        pnl = gross + position['funding_pnl'] - position['entry_fee'] - exit_fee
        trades.append({
            'symbol': alt,
            'opened_at': str(position['opened_at']),
            'closed_at': str(timestamp),
            'side': 'LONG_ALT_SHORT_BTC',
            'beta': position['beta'],
            'entry_z': position['entry_z'],
            'exit_z': None if z_value is None else float(z_value),
            'alt_entry': position['alt_entry'],
            'btc_entry': position['btc_entry'],
            'alt_quantity': position['alt_qty'],
            'btc_quantity': position['btc_qty'],
            'gross_pnl': gross,
            'funding_pnl': position['funding_pnl'],
            'fees': position['entry_fee'] + exit_fee,
            'pnl': pnl,
            'r_multiple': pnl / 4.0,
            'reason': reason,
            'setup_id': position['setup_id'],
        })
        position = None

    for i, timestamp in enumerate(index):
        if position is not None:
            alt = position['symbol']
            payment = funding_payment(
                alt, 1, position['alt_qty'], arrays[alt]['open'][i], timestamp)
            payment += funding_payment(
                'BTCUSDT', -1, position['btc_qty'],
                arrays['BTCUSDT']['open'][i], timestamp)
            cash += payment
            position['funding_pnl'] += payment

        if (position is not None
                and mark(i) - position['cash_before'] <= -config.hard_stop_usd):
            close(i, timestamp, 'HARD_DOLLAR_STOP', None)

        if position is not None and timestamp in feature_maps[position['symbol']]:
            z_value = feature_maps[position['symbol']][timestamp]
            held_hours = (timestamp - position['opened_at']).total_seconds() / 3600
            if np.isfinite(z_value) and z_value >= config.exit_z:
                close(i, timestamp, 'MEAN_REVERSION', z_value)
            elif np.isfinite(z_value) and z_value <= config.stop_z:
                close(i, timestamp, 'RESIDUAL_STOP', z_value)
            elif held_hours >= config.max_hold_hours:
                close(i, timestamp, 'TIME', z_value)

        if position is None and not halted and timestamp in signal_map:
            signal = signal_map[timestamp][0]
            alt, beta = signal['symbol'], signal['beta']
            alt_entry = arrays[alt]['open'][i] * (1.0 + slip)
            btc_entry = arrays['BTCUSDT']['open'][i] * (1.0 - slip)
            alt_notional = min(config.alt_notional_usd, cash * 0.25)
            btc_notional = min(beta * alt_notional, config.maximum_btc_hedge_usd)
            entry_fee = fee * (alt_notional + btc_notional)
            if alt_notional + btc_notional <= 0 or entry_fee >= cash:
                diagnostics['blocked_capital'] += 1
            else:
                cash_before = cash
                cash -= entry_fee
                position = {
                    'symbol': alt, 'beta': beta,
                    'alt_entry': alt_entry, 'btc_entry': btc_entry,
                    'alt_qty': alt_notional / alt_entry,
                    'btc_qty': btc_notional / btc_entry,
                    'entry_fee': entry_fee, 'funding_pnl': 0.0,
                    'opened_at': timestamp, 'entry_z': signal['z'],
                    'setup_id': signal['setup_id'], 'cash_before': cash_before,
                }
                diagnostics['entries'] += 1

        equity = mark(i)
        peak = max(peak, equity)
        if 1.0 - equity / max(peak, 1e-12) >= config.drawdown_halt_fraction:
            halted = True
        daily_equity[str(timestamp.date())] = equity

    if position is not None:
        close(len(index) - 1, end, 'END_OF_TEST', None)
        daily_equity[str((end - pd.Timedelta(minutes=1)).date())] = cash
    pnl_values = np.array([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnl_values[pnl_values > 0].sum()) if len(pnl_values) else 0.0
    losses = float(-pnl_values[pnl_values < 0].sum()) if len(pnl_values) else 0.0
    equity_values = np.array([initial_capital, *daily_equity.values()], dtype=float)
    dd = 1.0 - equity_values / np.maximum.accumulate(equity_values)
    return {
        'summary': {
            'trades': len(trades),
            'net_pnl': cash - initial_capital,
            'return_pct': (cash / initial_capital - 1.0) * 100,
            'profit_factor': gains / losses if losses else (None if not gains else 'Infinity'),
            'mean_net_r': float(np.mean([trade['r_multiple'] for trade in trades])) if trades else 0.0,
            'max_drawdown_pct': float(dd.max() * 100),
            'fees': float(sum(trade['fees'] for trade in trades)),
            'funding_pnl': float(sum(trade['funding_pnl'] for trade in trades)),
            'drawdown_halted': halted,
            'diagnostics': dict(diagnostics),
        },
        'trades': trades,
        'daily_equity': daily_equity,
    }
