"""Single-account long-spot/short-perpetual basis-compression replay."""
from collections import Counter

import numpy as np
import pandas as pd

from .scalp_data import validate_minutes


def execute_basis_compression(
    spot_by_symbol,
    perp_markets,
    features_by_symbol,
    signals_by_symbol,
    config,
    start,
    end,
    initial_capital=500.0,
    costs=None,
    symbol_priority=(),
):
    costs = costs or {'spot_side': 15.0, 'perp_side': 13.0, 'leg_risk': 10.0}
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    symbols = tuple(spot_by_symbol)
    priority = {symbol: i for i, symbol in enumerate(symbol_priority or symbols)}
    spot_arrays, perp_arrays, funding_maps = {}, {}, {}
    index = None
    for symbol in symbols:
        spot = spot_by_symbol[symbol].loc[
            (spot_by_symbol[symbol].index >= start) & (spot_by_symbol[symbol].index < end)]
        perp, funding = perp_markets[symbol]
        perp = perp.loc[(perp.index >= start) & (perp.index < end)]
        validate_minutes(spot)
        validate_minutes(perp)
        if not spot.index.equals(perp.index):
            raise ValueError(f'Spot/perpetual minute indices diverged for {symbol}')
        if index is None:
            index = spot.index
        elif not index.equals(spot.index):
            raise ValueError('Symbols have divergent minute indices')
        spot_arrays[symbol] = {c: spot[c].to_numpy(dtype=float) for c in ('open', 'close')}
        perp_arrays[symbol] = {c: perp[c].to_numpy(dtype=float) for c in ('open', 'close')}
        funding_maps[symbol] = funding.to_dict()

    signal_map = {}
    for rows in signals_by_symbol.values():
        for signal in rows:
            if start <= signal['timestamp'] < end:
                signal_map.setdefault(signal['timestamp'], []).append(signal)
    for timestamp in signal_map:
        signal_map[timestamp].sort(
            key=lambda row: (-row['score'], priority.get(row['symbol'], len(priority))))
    basis_maps = {symbol: frame.basis.to_dict() for symbol, frame in features_by_symbol.items()}
    spot_side = costs['spot_side'] / 10000.0
    perp_side = costs['perp_side'] / 10000.0
    leg_risk = costs['leg_risk'] / 10000.0
    free_cash, peak, position = float(initial_capital), float(initial_capital), None
    trades, daily_equity, diagnostics = [], {}, Counter()

    def equity(i):
        if position is None:
            return free_cash
        symbol, qty = position['symbol'], position['qty']
        spot = spot_arrays[symbol]['close'][i]
        perp = perp_arrays[symbol]['close'][i]
        spot_value = qty * spot
        perp_unrealized = qty * (position['perp_entry'] - perp)
        exit_cost = qty * spot * spot_side + qty * perp * perp_side
        return free_cash + spot_value + position['collateral'] + perp_unrealized - exit_cost

    def close(i, timestamp, reason, basis_value):
        nonlocal free_cash, position
        symbol, qty = position['symbol'], position['qty']
        spot_fill = spot_arrays[symbol]['open'][i]
        perp_fill = perp_arrays[symbol]['open'][i]
        spot_exit_cost = qty * spot_fill * spot_side
        perp_exit_cost = qty * perp_fill * perp_side
        spot_proceeds = qty * spot_fill - spot_exit_cost
        perp_gross = qty * (position['perp_entry'] - perp_fill)
        free_cash += (
            spot_proceeds + position['collateral'] + perp_gross - perp_exit_cost)
        pnl = free_cash - position['cash_before']
        trades.append({
            'symbol': symbol,
            'opened_at': str(position['opened_at']),
            'closed_at': str(timestamp),
            'entry_basis': position['entry_basis'],
            'exit_basis': None if basis_value is None else float(basis_value),
            'frozen_median': position['median'],
            'quantity': qty,
            'spot_entry': position['spot_entry'],
            'perp_entry': position['perp_entry'],
            'gross_basis_pnl': qty * (
                (spot_fill - position['spot_entry'])
                + (position['perp_entry'] - perp_fill)),
            'funding_pnl': position['funding_pnl'],
            'costs': position['entry_cost'] + spot_exit_cost + perp_exit_cost,
            'pnl': pnl,
            'reason': reason,
            'setup_id': position['setup_id'],
        })
        position = None

    for i, timestamp in enumerate(index):
        if position is not None and timestamp > position['opened_at']:
            rate = funding_maps[position['symbol']].get(timestamp)
            if rate is not None:
                payment = position['qty'] * perp_arrays[position['symbol']]['open'][i] * rate
                position['collateral'] += payment
                position['funding_pnl'] += payment
                position['funding_after_entry'].append(float(rate))

        if position is not None and timestamp in basis_maps[position['symbol']]:
            basis = basis_maps[position['symbol']][timestamp]
            held = (timestamp - position['opened_at']).total_seconds() / 3600.0
            perp = perp_arrays[position['symbol']]['open'][i]
            futures_equity = position['collateral'] + position['qty'] * (
                position['perp_entry'] - perp)
            leverage = position['qty'] * perp / max(futures_equity, 1e-12)
            compressed_level = position['median'] + (
                1.0 - config.compression_fraction) * (
                    position['entry_basis'] - position['median'])
            funding_bad = (
                len(position['funding_after_entry']) >= 2
                and sum(position['funding_after_entry'][-2:]) <= 0)
            reason = None
            if np.isfinite(basis) and basis <= compressed_level:
                reason = 'COMPRESSION'
            elif np.isfinite(basis) and basis >= position['entry_basis'] + config.extension_stop:
                reason = 'BASIS_EXTENSION'
            elif funding_bad:
                reason = 'FUNDING_REVERSAL'
            elif held >= config.maximum_hold_hours:
                reason = 'TIME'
            elif futures_equity < config.minimum_futures_equity_usd:
                reason = 'COLLATERAL_STOP'
            elif leverage > config.maximum_mark_leverage:
                reason = 'LEVERAGE_STOP'
            if reason:
                close(i, timestamp, reason, basis)

        if position is None and timestamp in signal_map:
            signal = signal_map[timestamp][0]
            symbol = signal['symbol']
            spot_fill = spot_arrays[symbol]['open'][i]
            perp_fill = perp_arrays[symbol]['open'][i]
            qty = min(
                config.notional_cap_each_leg_usd / spot_fill,
                config.notional_cap_each_leg_usd / perp_fill,
            )
            spot_notional, perp_notional = qty * spot_fill, qty * perp_fill
            entry_cost = (
                spot_notional * spot_side + perp_notional * perp_side
                + max(spot_notional, perp_notional) * leg_risk)
            required = spot_notional + config.futures_collateral_usd + entry_cost
            if required > free_cash:
                diagnostics['blocked_capital'] += 1
            else:
                cash_before = free_cash
                free_cash -= required
                position = {
                    'symbol': symbol, 'qty': qty,
                    'spot_entry': spot_fill, 'perp_entry': perp_fill,
                    'entry_basis': signal['basis'], 'median': signal['median'],
                    'opened_at': timestamp, 'cash_before': cash_before,
                    'collateral': config.futures_collateral_usd,
                    'entry_cost': entry_cost, 'funding_pnl': 0.0,
                    'funding_after_entry': [], 'setup_id': signal['setup_id'],
                }
                diagnostics['entries'] += 1

        marked = equity(i)
        peak = max(peak, marked)
        daily_equity[str(timestamp.date())] = marked

    if position is not None:
        close(len(index) - 1, end, 'END_OF_TEST', None)
        daily_equity[str((end - pd.Timedelta(minutes=1)).date())] = free_cash
    pnls = np.array([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    equity_values = np.array([initial_capital, *daily_equity.values()], dtype=float)
    dd = 1.0 - equity_values / np.maximum.accumulate(equity_values)
    return {
        'summary': {
            'trades': len(trades),
            'net_pnl': free_cash - initial_capital,
            'return_pct': (free_cash / initial_capital - 1.0) * 100,
            'profit_factor': gains / losses if losses else (None if not gains else 'Infinity'),
            'max_drawdown_pct': float(dd.max() * 100),
            'funding_pnl': float(sum(t['funding_pnl'] for t in trades)),
            'costs': float(sum(t['costs'] for t in trades)),
            'diagnostics': dict(diagnostics),
        },
        'trades': trades,
        'daily_equity': daily_equity,
    }
