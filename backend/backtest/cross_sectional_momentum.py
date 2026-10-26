"""Causal XSM-28 cross-sectional, beta-neutral pair research.

This module deliberately keeps the signal and the two-leg ledger together:
the long and short are one indivisible episode and are never reported as two
standalone accounts.  It is research code, not an exchange adapter.
"""
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class XSMCosts:
    taker_fee_bps: float = 5.0
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class XSMConfig:
    name: str = 'XSM_28_beta_neutral'
    momentum_days: int = 28
    beta_days: int = 60
    risk_fraction: float = 0.005
    target_r: float = 2.0
    pair_vol_multiplier: float = 1.5
    min_stop_gross_fraction: float = 0.03
    max_stop_gross_fraction: float = 0.12
    max_gross_equity: float = 0.75
    min_beta: float = 0.25
    max_beta: float = 3.0
    min_leg_weight: float = 0.25
    max_leg_weight: float = 0.75
    max_hold_days: int = 28
    drawdown_halt_fraction: float = 0.06
    costs: XSMCosts = XSMCosts()

    def validate(self) -> None:
        if self.momentum_days < 2 or self.beta_days < self.momentum_days:
            raise ValueError('Invalid momentum/beta lookbacks')
        if not 0 < self.risk_fraction < self.drawdown_halt_fraction < 1:
            raise ValueError('Invalid risk/drawdown fractions')
        if not 0 < self.min_stop_gross_fraction <= self.max_stop_gross_fraction:
            raise ValueError('Invalid pair stop bounds')
        if not 0 < self.max_gross_equity <= 1:
            raise ValueError('Gross notional must not exceed shared equity')
        if not 0 < self.min_leg_weight <= self.max_leg_weight < 1:
            raise ValueError('Invalid leg weight guard')


def _daily_close_series(frame: pd.DataFrame, decision: pd.Timestamp) -> pd.Series:
    """Return closes known strictly before ``decision``.

    Daily archive rows are indexed by open time.  ``close_time`` is required so
    a Sunday candle is usable at Monday 00:00 UTC while the still-open Monday
    candle can never leak into the ranking.
    """
    if 'close_time' not in frame or 'close' not in frame:
        raise ValueError('Daily data requires close and close_time columns')
    close_time = pd.to_datetime(frame.close_time, utc=True)
    values = frame.loc[close_time < decision, 'close'].astype(float)
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError('Daily data must be sorted and unique')
    return values


def _log_returns(closes: pd.Series) -> pd.Series:
    values = np.log(closes).diff().dropna()
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError('Invalid daily return history')
    return values


def weekly_xsm_targets(
    daily: dict[str, pd.DataFrame],
    btc_daily: pd.DataFrame,
    start,
    end,
    config: XSMConfig = XSMConfig(),
    symbol_order=(),
) -> list[dict]:
    """Create causal Monday targets from completed daily candles."""
    config.validate()
    start, end = _utc(start), _utc(end)
    if start.weekday() != 0 or start.time() != pd.Timestamp('00:00').time():
        raise ValueError('XSM window must start Monday 00:00 UTC')
    symbols = tuple(symbol_order or daily)
    if set(symbols) != set(daily):
        raise ValueError('symbol_order must contain every and only tradable symbol')
    decisions = pd.date_range(start, end, freq='7D', inclusive='left')
    targets = []

    for decision in decisions:
        btc_returns = _log_returns(_daily_close_series(btc_daily, decision))
        observations = {}
        for symbol in symbols:
            closes = _daily_close_series(daily[symbol], decision)
            returns = _log_returns(closes)
            if len(returns) < config.beta_days or len(closes) < config.momentum_days + 1:
                observations = {}
                break
            momentum_closes = closes.iloc[-(config.momentum_days + 1):]
            momentum_returns = returns.iloc[-config.momentum_days:]
            simple_return = float(momentum_closes.iloc[-1] / momentum_closes.iloc[0] - 1)
            volatility = float(momentum_returns.std(ddof=1))
            aligned = pd.concat(
                [returns.rename('asset'), btc_returns.rename('btc')], axis=1,
                join='inner',
            ).dropna().iloc[-config.beta_days:]
            if len(aligned) != config.beta_days:
                observations = {}
                break
            btc_variance = float(aligned.btc.var(ddof=1))
            beta = (float(aligned.asset.cov(aligned.btc)) / btc_variance
                    if btc_variance > 0 else np.nan)
            if volatility <= 0 or not np.isfinite([simple_return, volatility, beta]).all():
                observations = {}
                break
            observations[symbol] = {
                'return_28d': simple_return,
                'volatility_28d': volatility,
                'score': simple_return / volatility,
                'beta_60d': beta,
                'returns_28d': momentum_returns,
                'last_completed_daily_open': str(momentum_closes.index[-1]),
            }

        if len(observations) != len(symbols):
            continue
        ranked = sorted(symbols, key=lambda symbol: (
            -observations[symbol]['score'], symbols.index(symbol)))
        leader, laggard = ranked[0], ranked[-1]
        leader_row, laggard_row = observations[leader], observations[laggard]
        if leader_row['return_28d'] <= 0 or laggard_row['return_28d'] >= 0:
            continue
        long_beta, short_beta = leader_row['beta_60d'], laggard_row['beta_60d']
        if not (config.min_beta <= long_beta <= config.max_beta
                and config.min_beta <= short_beta <= config.max_beta):
            continue
        beta_sum = long_beta + short_beta
        long_weight, short_weight = short_beta / beta_sum, long_beta / beta_sum
        if not (config.min_leg_weight <= long_weight <= config.max_leg_weight
                and config.min_leg_weight <= short_weight <= config.max_leg_weight):
            continue
        paired_returns = pd.concat(
            [leader_row['returns_28d'].rename('long'),
             laggard_row['returns_28d'].rename('short')],
            axis=1, join='inner',
        ).dropna()
        if len(paired_returns) != config.momentum_days:
            continue
        pair_volatility = float((paired_returns.long - paired_returns.short).std(ddof=1))
        if not np.isfinite(pair_volatility) or pair_volatility <= 0:
            continue
        stop_fraction = float(np.clip(
            config.pair_vol_multiplier * pair_volatility,
            config.min_stop_gross_fraction,
            config.max_stop_gross_fraction,
        ))
        targets.append({
            'timestamp': decision,
            'long_symbol': leader,
            'short_symbol': laggard,
            'long_weight': long_weight,
            'short_weight': short_weight,
            'long_beta': long_beta,
            'short_beta': short_beta,
            'net_beta': long_weight * long_beta - short_weight * short_beta,
            'pair_volatility_28d': pair_volatility,
            'stop_gross_fraction': stop_fraction,
            'scores': {
                symbol: {
                    key: value for key, value in observations[symbol].items()
                    if key != 'returns_28d'
                }
                for symbol in symbols
            },
        })
    return targets


def _validate_execution_frame(frame: pd.DataFrame) -> None:
    required = {'open', 'high', 'low', 'close'}
    if not required.issubset(frame):
        raise ValueError('Execution data lacks OHLC columns')
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError('Execution data must be non-empty, sorted and unique')
    if not (frame.index.to_series().diff().dropna() == pd.Timedelta(minutes=5)).all():
        raise ValueError('Missing 5m bars: refusing an apparently continuous replay')
    values = frame[list(required)].to_numpy(dtype=float)
    if (not np.isfinite(values).all()
            or (frame[list(required)] <= 0).any().any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError('Invalid execution OHLC')


def simulate_xsm_pairs(
    markets: dict[str, tuple[pd.DataFrame, pd.Series]],
    targets: list[dict],
    start,
    end,
    config: XSMConfig = XSMConfig(),
    initial_capital: float = 250.0,
) -> dict:
    """Replay a single shared account holding at most one two-leg pair."""
    config.validate()
    start, end = _utc(start), _utc(end)
    if initial_capital <= 0:
        raise ValueError('Initial capital must be positive')
    symbols = tuple(markets)
    data, rates, common_index = {}, {}, None
    for symbol, (frame, funding) in markets.items():
        frame = frame.loc[(frame.index >= start) & (frame.index < end)]
        _validate_execution_frame(frame)
        if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=5) != end:
            raise ValueError(f'Incomplete execution period for {symbol}')
        if common_index is None:
            common_index = frame.index
        elif not frame.index.equals(common_index):
            raise ValueError('Pair execution indices are not aligned')
        if funding.index.has_duplicates or not np.isfinite(funding.to_numpy(dtype=float)).all():
            raise ValueError('Invalid funding history')
        data[symbol] = frame
        rates[symbol] = funding.to_dict()

    target_map = {}
    for target in targets:
        timestamp = _utc(target['timestamp'])
        if start <= timestamp < end:
            if timestamp in target_map:
                raise ValueError('More than one pair target at one timestamp')
            if target['long_symbol'] == target['short_symbol']:
                raise ValueError('Pair legs must use different symbols')
            if target['long_symbol'] not in markets or target['short_symbol'] not in markets:
                raise ValueError('Target symbol absent from execution markets')
            weights = np.array(
                [target['long_weight'], target['short_weight']], dtype=float)
            if (not np.isfinite(weights).all() or (weights <= 0).any()
                    or not np.isclose(weights.sum(), 1.0, atol=1e-12)):
                raise ValueError('Pair gross weights must be positive and sum to one')
            calculated_beta = (
                target['long_weight'] * target['long_beta']
                - target['short_weight'] * target['short_beta'])
            if not np.isclose(calculated_beta, target['net_beta'], atol=1e-12):
                raise ValueError('Target net beta does not match its weights')
            if abs(calculated_beta) > 1e-10:
                raise ValueError('Target is not beta-neutral')
            if not (config.min_stop_gross_fraction
                    <= target['stop_gross_fraction']
                    <= config.max_stop_gross_fraction):
                raise ValueError('Target pair stop is outside frozen bounds')
            target_map[timestamp] = target

    fee = config.costs.taker_fee_bps / 10_000
    slip = config.costs.slippage_bps / 10_000
    cash, position, pending_exit = float(initial_capital), None, None
    peak_equity, drawdown_halted = cash, False
    episodes, equity_curve, diagnostics = [], [], Counter()

    def liquidation_value(rows, field='close'):
        if position is None:
            return cash
        long_price = getattr(rows[position['long_symbol']], field) * (1 - slip)
        short_price = getattr(rows[position['short_symbol']], field) * (1 + slip)
        long_gross = position['long_qty'] * (long_price - position['long_entry'])
        short_gross = position['short_qty'] * (position['short_entry'] - short_price)
        exit_fees = fee * (
            position['long_qty'] * long_price + position['short_qty'] * short_price)
        return cash + long_gross + short_gross - exit_fees

    def open_pair(target, rows, timestamp):
        nonlocal cash, position
        equity_before = cash
        risk_budget = equity_before * config.risk_fraction
        gross_notional = min(
            equity_before * config.max_gross_equity,
            risk_budget / target['stop_gross_fraction'],
        )
        long_notional = gross_notional * target['long_weight']
        short_notional = gross_notional * target['short_weight']
        long_open = rows[target['long_symbol']].open
        short_open = rows[target['short_symbol']].open
        long_entry = long_open * (1 + slip)
        short_entry = short_open * (1 - slip)
        long_qty, short_qty = long_notional / long_entry, short_notional / short_entry
        entry_fees = fee * (long_notional + short_notional)
        cash -= entry_fees
        position = {
            **target,
            'opened_at': timestamp,
            'deadline': timestamp + pd.Timedelta(days=config.max_hold_days),
            'cash_before': equity_before,
            'risk_budget': risk_budget,
            'gross_notional': gross_notional,
            'long_notional': long_notional,
            'short_notional': short_notional,
            'long_entry': long_entry,
            'short_entry': short_entry,
            'long_qty': long_qty,
            'short_qty': short_qty,
            'entry_fees': entry_fees,
            'funding_pnl': 0.0,
        }
        diagnostics['entries'] += 1

    def close_pair(rows, field, timestamp, reason):
        nonlocal cash, position
        long_price = getattr(rows[position['long_symbol']], field) * (1 - slip)
        short_price = getattr(rows[position['short_symbol']], field) * (1 + slip)
        long_gross = position['long_qty'] * (long_price - position['long_entry'])
        short_gross = position['short_qty'] * (position['short_entry'] - short_price)
        exit_fees = fee * (
            position['long_qty'] * long_price + position['short_qty'] * short_price)
        cash += long_gross + short_gross - exit_fees
        pnl = cash - position['cash_before']
        episodes.append({
            **{key: value for key, value in position.items()
               if key not in {'deadline', 'cash_before'}},
            'closed_at': timestamp,
            'long_exit': long_price,
            'short_exit': short_price,
            'long_gross_pnl': long_gross,
            'short_gross_pnl': short_gross,
            'gross_pnl': long_gross + short_gross,
            'exit_fees': exit_fees,
            'total_fees': position['entry_fees'] + exit_fees,
            'pnl': pnl,
            'r_multiple': pnl / position['risk_budget'],
            'reason': reason,
        })
        diagnostics[f'exits_{reason.lower()}'] += 1
        position = None

    iterators = [data[symbol].itertuples() for symbol in symbols]
    for rows_tuple in zip(*iterators):
        rows = {symbol: row for symbol, row in zip(symbols, rows_tuple)}
        timestamp = rows_tuple[0].Index
        if any(row.Index != timestamp for row in rows_tuple[1:]):
            raise ValueError('Pair iterator timestamps diverged')

        was_open_at_bar_start = position is not None
        if position is not None:
            for symbol, side, quantity in (
                (position['long_symbol'], 1, position['long_qty']),
                (position['short_symbol'], -1, position['short_qty']),
            ):
                if timestamp in rates[symbol]:
                    payment = -side * quantity * rows[symbol].open * rates[symbol][timestamp]
                    cash += payment
                    position['funding_pnl'] += payment

        if position is not None and pending_exit is not None:
            reason, pending_exit = pending_exit, None
            close_pair(rows, 'open', timestamp, reason)
        elif position is not None and timestamp >= position['deadline']:
            close_pair(rows, 'open', timestamp, 'MAX_HOLD')

        target = target_map.get(timestamp)
        if target is not None:
            diagnostics['weekly_targets'] += 1
            if was_open_at_bar_start:
                diagnostics['ignored_targets_while_open'] += 1
            elif position is None and not drawdown_halted:
                open_pair(target, rows, timestamp)
            elif drawdown_halted:
                diagnostics['blocked_drawdown_halt'] += 1

        marked = liquidation_value(rows, 'close')
        if position is not None and pending_exit is None:
            pair_pnl = marked - position['cash_before']
            if pair_pnl <= -position['risk_budget']:
                pending_exit = 'STOP'
            elif pair_pnl >= config.target_r * position['risk_budget']:
                pending_exit = 'TARGET'

        peak_equity = max(peak_equity, marked)
        if 1 - marked / max(peak_equity, 1e-12) >= config.drawdown_halt_fraction:
            drawdown_halted = True
        equity_curve.append({'timestamp': str(timestamp + pd.Timedelta(minutes=5)),
                             'equity': float(marked)})

    if position is not None:
        rows = {symbol: data[symbol].iloc[-1] for symbol in symbols}
        close_pair(rows, 'close', end, 'END_OF_TEST')
        equity_curve[-1] = {'timestamp': str(end), 'equity': float(cash)}

    pnls = np.array([episode['pnl'] for episode in episodes], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    equity_values = np.r_[initial_capital, [row['equity'] for row in equity_curve]]
    drawdowns = (1 - equity_values / np.maximum.accumulate(equity_values)) * 100
    pair_breakdown = {}
    for episode in episodes:
        key = f'{episode["long_symbol"]}>{episode["short_symbol"]}'
        row = pair_breakdown.setdefault(key, {'episodes': 0, 'net_pnl': 0.0})
        row['episodes'] += 1
        row['net_pnl'] += float(episode['pnl'])
    return {
        'config': {**asdict(config), 'costs': asdict(config.costs)},
        'window': [str(start), str(end)],
        'summary': {
            'episodes': len(episodes),
            'wins': int((pnls > 0).sum()),
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'episode_profit_factor': (
                gains / losses if losses else (None if gains == 0 else 'Infinity')),
            'net_pnl': float(cash - initial_capital),
            'return_pct': float((cash / initial_capital - 1) * 100),
            'max_drawdown_pct': float(drawdowns.max()),
            'fees': float(sum(row['total_fees'] for row in episodes)),
            'funding_pnl': float(sum(row['funding_pnl'] for row in episodes)),
            'mean_net_r': float(np.mean([row['r_multiple'] for row in episodes]))
            if episodes else 0.0,
            'max_abs_entry_net_beta': max(
                (abs(row['net_beta']) for row in episodes), default=0.0),
            'pair_breakdown': pair_breakdown,
            'diagnostics': dict(diagnostics),
            'drawdown_halted': drawdown_halted,
        },
        'episodes': episodes,
        'equity_curve': equity_curve,
    }
