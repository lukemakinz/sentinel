"""Causal execution and portfolio replay for frozen S36 candidates.

Signal construction lives in the S36 signal module.  This module deliberately
accepts already-qualified candidates and owns only execution, position
management, costs and portfolio risk.  Five-minute OHLC indices are bar-open
timestamps and all stop changes computed from a completed bar become active on
the next bar.
"""
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .post_funding_exhaustion import (
    PRICE_TICKS,
    QUANTITY_STEPS,
    _adverse_price_round,
    _round_down_step,
    _utc,
    _validate_funding,
    _validate_ohlc,
)


DEFAULT_SYMBOL_PRIORITY = (
    'SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT',
)


@dataclass(frozen=True)
class FRSCosts:
    taker_fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 10.0

    @property
    def round_trip_bps(self) -> float:
        return 2 * (self.taker_fee_bps_per_side + self.slippage_bps_per_side)


@dataclass(frozen=True)
class FRSPortfolioConfig:
    """Parameters copied from the frozen S36 protocol."""

    name: str = 'S36_funding_regime_switch'
    atr_stop_buffer: float = .15
    minimum_atr_distance: float = .60
    minimum_price_distance: float = .006
    minimum_tick_distance: int = 3
    maximum_atr_distance: float = 2.50
    maximum_price_distance: float = .03
    risk_fraction: float = .002
    fixed_risk_usd: float = .50
    maximum_notional_equity: float = .50
    maximum_isolated_leverage: float = 2.0
    minimum_notional_usd: float = 20.0
    partial_fraction: float = .50
    partial_trigger_r: float = 1.0
    breakeven_trigger_r: float = 1.0
    breakeven_net_bps: float = 2.0
    trailing_trigger_r: float = 1.5
    trailing_atr: float = 1.5
    trailing_swing_bars: int = 3
    hard_target_r: float = 4.0
    stagnation_minutes: int = 60
    stagnation_mfe_r: float = .50
    unreached_target_minutes: int = 120
    reached_target_minutes: int = 180
    daily_loss_fraction: float = .006
    weekly_loss_fraction: float = .015
    drawdown_kill_fraction: float = .04
    # Sizing and cost-BE never assume less than frozen stress friction.
    stress_fee_bps_per_side: float = 5.0
    stress_slippage_bps_per_side: float = 10.0
    costs: FRSCosts = FRSCosts()
    symbol_priority: tuple[str, ...] = DEFAULT_SYMBOL_PRIORITY

    def validate(self, initial_capital: float = 250.0) -> None:
        if initial_capital <= 0:
            raise ValueError('Initial capital must be positive')
        if min(
            self.atr_stop_buffer,
            self.minimum_atr_distance,
            self.minimum_price_distance,
            self.maximum_atr_distance,
            self.maximum_price_distance,
            self.risk_fraction,
            self.fixed_risk_usd,
            self.maximum_notional_equity,
            self.maximum_isolated_leverage,
            self.minimum_notional_usd,
            self.partial_fraction,
            self.partial_trigger_r,
            self.breakeven_trigger_r,
            self.trailing_trigger_r,
            self.trailing_atr,
            self.hard_target_r,
            self.daily_loss_fraction,
            self.weekly_loss_fraction,
            self.drawdown_kill_fraction,
        ) <= 0:
            raise ValueError('S36 risk parameters must be positive')
        if self.minimum_tick_distance < 1 or self.trailing_swing_bars < 1:
            raise ValueError('Invalid integer risk parameter')
        if not 0 < self.partial_fraction < 1:
            raise ValueError('Partial fraction must be between zero and one')
        if not 0 < self.maximum_notional_equity <= 1:
            raise ValueError('Invalid notional cap')
        if self.maximum_isolated_leverage < 1:
            raise ValueError('Invalid leverage cap')
        if not (
            self.partial_trigger_r == self.breakeven_trigger_r
            < self.trailing_trigger_r < self.hard_target_r
        ):
            raise ValueError('Invalid S36 exit geometry')
        if not (
            0 < self.stagnation_minutes < self.unreached_target_minutes
            < self.reached_target_minutes
        ):
            raise ValueError('Invalid S36 time stops')
        if any(minutes % 5 for minutes in (
            self.stagnation_minutes,
            self.unreached_target_minutes,
            self.reached_target_minutes,
        )):
            raise ValueError('Time stops must align to five minutes')
        if not (
            0 < self.daily_loss_fraction < self.weekly_loss_fraction
            < self.drawdown_kill_fraction < 1
        ):
            raise ValueError('Invalid portfolio loss limits')
        if min(
            self.costs.taker_fee_bps_per_side,
            self.costs.slippage_bps_per_side,
            self.stress_fee_bps_per_side,
            self.stress_slippage_bps_per_side,
            self.breakeven_net_bps,
        ) < 0:
            raise ValueError('Costs cannot be negative')


def _candidate_dict(candidate) -> dict:
    if is_dataclass(candidate):
        value = asdict(candidate)
    elif isinstance(candidate, Mapping):
        value = dict(candidate)
    else:
        raise TypeError('Candidate must be a dataclass or mapping')
    required = {
        'timestamp', 'symbol', 'side', 'regime', 'atr',
        'structural_extreme', 'breakout_level',
        'liquidity_notional_cap_usd',
    }
    missing = required.difference(value)
    if missing:
        raise ValueError(f'Missing S36 candidate fields: {sorted(missing)}')
    value['timestamp'] = _utc(value['timestamp'])
    for key in ('feature_cutoff', 'funding_time', 'classification_time', 'retest_time'):
        if value.get(key) is not None:
            value[key] = _utc(value[key])
    side = value['side']
    if isinstance(side, str):
        side = {'LONG': 1, 'SHORT': -1}.get(side.upper())
    if side not in (-1, 1):
        raise ValueError('Candidate side must be LONG/SHORT or +/-1')
    value['side'] = int(side)
    if value['regime'] not in ('FADE', 'CONTINUATION'):
        raise ValueError('Candidate regime must be FADE or CONTINUATION')
    numeric = (
        'atr', 'structural_extreme', 'breakout_level',
        'liquidity_notional_cap_usd',
    )
    if any(not np.isfinite(float(value[key])) for key in numeric):
        raise ValueError('Candidate risk fields must be finite')
    if any(float(value[key]) <= 0 for key in numeric):
        raise ValueError('Candidate risk fields must be positive')
    cutoff = value.get('feature_cutoff')
    if cutoff is not None and cutoff > value['timestamp']:
        raise ValueError('Candidate uses features unavailable at entry')
    return value


def _candidate_rank(candidate: dict, priority: dict[str, int]):
    return (
        -int(candidate.get('soft_count', 0)),
        -int(candidate.get('event_criteria_count', 0)),
        -float(candidate.get('funding_ratio', 0.0)),
        priority.get(candidate['symbol'], len(priority)),
        candidate['symbol'],
        str(candidate.get('setup_id', '')),
    )


def _has_complete_holding_data(
    streams: dict,
    entry_time: pd.Timestamp,
    end: pd.Timestamp,
    minutes: int,
) -> bool:
    last = min(
        entry_time + pd.Timedelta(minutes=minutes),
        end - pd.Timedelta(minutes=5),
    )
    if last < entry_time:
        return False
    expected = pd.date_range(entry_time, last, freq='5min')
    return all(
        name in streams and expected.isin(streams[name].index).all()
        for name in ('perpetual', 'mark', 'index')
    )


def _cost_breakeven_stop(
    entry_fill: float,
    side: int,
    config: FRSPortfolioConfig,
) -> float:
    """Raw stop whose adverse stress fill leaves +2 bps on the remainder."""
    fee = config.stress_fee_bps_per_side / 10_000
    slip = config.stress_slippage_bps_per_side / 10_000
    locked = config.breakeven_net_bps / 10_000
    if side == 1:
        desired_fill = entry_fill * (1 + fee + locked) / (1 - fee)
        return desired_fill / (1 - slip)
    desired_fill = entry_fill * (1 - fee - locked) / (1 + fee)
    return desired_fill / (1 + slip)


def simulate_funding_regime_switch_portfolio(
    markets: dict,
    candidates,
    start,
    end,
    config: FRSPortfolioConfig | None = None,
    initial_capital: float = 250.0,
) -> dict:
    """Replay frozen S36 candidates through one shared portfolio ledger."""
    config = config or FRSPortfolioConfig()
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    if end <= start or (end - start) % pd.Timedelta(minutes=5):
        raise ValueError('Replay window must align to five minutes')

    for symbol, streams in markets.items():
        if symbol not in QUANTITY_STEPS or symbol not in PRICE_TICKS:
            raise ValueError(f'No frozen order filters for {symbol}')
        if not {'perpetual', 'mark', 'index', 'funding'}.issubset(streams):
            raise ValueError(f'Invalid S36 streams for {symbol}')
        for stream in ('perpetual', 'mark', 'index'):
            _validate_ohlc(streams[stream], f'{symbol} {stream}')

    normalized = [_candidate_dict(candidate) for candidate in candidates]
    normalized = [
        candidate for candidate in normalized
        if start <= candidate['timestamp'] < end
    ]
    if any(candidate['symbol'] not in markets for candidate in normalized):
        raise ValueError('Candidate symbol has no market streams')
    priority = {
        symbol: rank for rank, symbol in enumerate(config.symbol_priority)
    }
    normalized.sort(key=lambda row: (
        row['timestamp'], *_candidate_rank(row, priority)))
    candidates_by_time: dict[pd.Timestamp, list[dict]] = {}
    for candidate in normalized:
        candidates_by_time.setdefault(candidate['timestamp'], []).append(candidate)

    funding_maps = {
        symbol: _validate_funding(streams['funding'], symbol).to_dict()
        for symbol, streams in markets.items()
    }
    fee = config.costs.taker_fee_bps_per_side / 10_000
    slip = config.costs.slippage_bps_per_side / 10_000
    stress_fee = max(fee, config.stress_fee_bps_per_side / 10_000)
    stress_slip = max(slip, config.stress_slippage_bps_per_side / 10_000)

    cash = float(initial_capital)
    realised_total = 0.0
    position = None
    trades, invalidated, equity_curve = [], [], []
    diagnostics = Counter()
    calendar_days = pd.date_range(
        start.normalize(),
        (end - pd.Timedelta(minutes=5)).normalize(),
        freq='1D',
    )
    daily_pnl = Counter({str(day.date()): 0.0 for day in calendar_days})
    weekly_pnl = Counter()
    current_day = current_week = None
    day_start_equity = week_start_equity = cash
    day_realised_anchor = week_realised_anchor = 0.0
    day_blocked = week_blocked = risk_fail = False
    peak_equity = cash

    def record_cash_change(amount: float, timestamp: pd.Timestamp) -> None:
        nonlocal cash, realised_total
        cash += float(amount)
        realised_total += float(amount)
        daily_pnl[str(timestamp.date())] += float(amount)
        iso = timestamp.isocalendar()
        weekly_pnl[f'{iso.year}-W{iso.week:02d}'] += float(amount)

    def marked(raw_price: float) -> float:
        if position is None:
            return cash
        exit_fill = float(raw_price) * (1 - position['side'] * slip)
        gross = position['side'] * position['qty'] * (
            exit_fill - position['entry_fill'])
        exit_fee = position['qty'] * exit_fill * fee
        return cash + gross - exit_fee

    def refresh_realised_stops() -> None:
        nonlocal day_blocked, week_blocked
        if (
            not day_blocked
            and realised_total - day_realised_anchor
            <= -config.daily_loss_fraction * day_start_equity
        ):
            day_blocked = True
            diagnostics['daily_loss_stops'] += 1
        if (
            not week_blocked
            and realised_total - week_realised_anchor
            <= -config.weekly_loss_fraction * week_start_equity
        ):
            week_blocked = True
            diagnostics['weekly_loss_stops'] += 1

    def reduce_position(
        quantity: float,
        raw_price: float,
        timestamp: pd.Timestamp,
        reason: str,
    ) -> dict:
        nonlocal position
        quantity = min(float(quantity), position['qty'])
        exit_fill = float(raw_price) * (1 - position['side'] * slip)
        gross = position['side'] * quantity * (
            exit_fill - position['entry_fill'])
        exit_fee = quantity * exit_fill * fee
        record_cash_change(gross - exit_fee, timestamp)
        position['gross_pnl'] += gross
        position['fees'] += exit_fee
        position['qty'] = max(0.0, position['qty'] - quantity)
        fill = {
            'timestamp': str(timestamp),
            'reason': reason,
            'quantity': quantity,
            'raw_price': float(raw_price),
            'fill_price': exit_fill,
            'gross_pnl': gross,
            'fee': exit_fee,
        }
        position['exits'].append(fill)
        return fill

    def close_position(
        raw_price: float,
        timestamp: pd.Timestamp,
        reason: str,
    ) -> None:
        nonlocal position
        state = position
        reduce_position(state['qty'], raw_price, timestamp, reason)
        pnl = cash - state['cash_before']
        trades.append({
            **state['candidate'],
            'opened_at': str(state['opened_at']),
            'closed_at': str(timestamp),
            'side': 'LONG' if state['side'] == 1 else 'SHORT',
            'entry_reference': state['entry_reference'],
            'entry_fill': state['entry_fill'],
            'initial_stop': state['initial_stop'],
            'final_stop': state['stop'],
            'partial_target': state['partial_target'],
            'hard_target': state['hard_target'],
            'price_r': state['price_r'],
            'quantity': state['initial_qty'],
            'notional_usd': state['initial_qty'] * state['entry_fill'],
            'initial_margin_usd': state['initial_margin'],
            'risk_budget_usd': state['risk_budget'],
            'initial_risk_usd': state['initial_risk'],
            'gross_pnl': state['gross_pnl'],
            'funding_pnl': state['funding_pnl'],
            'fees': state['fees'],
            'pnl': pnl,
            'r_multiple': pnl / state['initial_risk'],
            'reason': reason,
            'partial_enabled': state['partial_enabled'],
            'partial_taken': state['partial_taken'],
            'reached_1r': state['reached_1r'],
            'reached_1_5r': state['reached_1_5r'],
            'stop_updates': state['stop_updates'],
            'exits': state['exits'],
        })
        position = None

    def improve_stop(raw_stop: float, timestamp: pd.Timestamp, reason: str) -> None:
        tick = PRICE_TICKS[position['symbol']]
        new_stop = _adverse_price_round(raw_stop, position['side'], tick)
        if position['side'] * (new_stop - position['stop']) <= 0:
            return
        old_stop = position['stop']
        position['stop'] = new_stop
        position['stop_updates'].append({
            'computed_at': str(timestamp),
            'active_from': str(timestamp),
            'old_stop': old_stop,
            'new_stop': new_stop,
            'reason': reason,
        })

    def enter(candidate: dict, timestamp: pd.Timestamp) -> bool:
        nonlocal position
        symbol, side = candidate['symbol'], int(candidate['side'])
        streams = markets[symbol]
        if (
            timestamp not in streams['perpetual'].index
            or not _has_complete_holding_data(
                streams, timestamp, end, config.reached_target_minutes)
        ):
            diagnostics['invalidated_missing_holding_data'] += 1
            invalidated.append(candidate)
            return False

        reference = float(streams['perpetual'].at[timestamp, 'open'])
        entry_fill = reference * (1 + side * slip)
        atr = float(candidate['atr'])
        tick = PRICE_TICKS[symbol]
        buffer = max(config.atr_stop_buffer * atr, 2 * tick)
        structural_stop = float(candidate['structural_extreme']) - side * buffer
        structural_distance = side * (entry_fill - structural_stop)
        minimum_distance = max(
            config.minimum_atr_distance * atr,
            config.minimum_price_distance * entry_fill,
            config.minimum_tick_distance * tick,
        )
        maximum_distance = min(
            config.maximum_atr_distance * atr,
            config.maximum_price_distance * entry_fill,
        )
        if maximum_distance + 1e-12 < minimum_distance:
            diagnostics['blocked_stop_band_empty'] += 1
            return False
        if structural_distance <= 0:
            diagnostics['blocked_invalid_structural_stop'] += 1
            return False
        if structural_distance > maximum_distance + 1e-12:
            diagnostics['blocked_structural_stop_too_wide'] += 1
            return False
        distance = max(structural_distance, minimum_distance)
        stop = _adverse_price_round(entry_fill - side * distance, side, tick)
        price_r = side * (entry_fill - stop)
        if stop <= 0 or price_r <= 0:
            diagnostics['blocked_invalid_rounded_barrier'] += 1
            return False
        partial_target = _adverse_price_round(
            entry_fill + side * config.partial_trigger_r * price_r,
            side,
            tick,
        )
        hard_target = _adverse_price_round(
            entry_fill + side * config.hard_target_r * price_r,
            side,
            tick,
        )
        if partial_target <= 0 or hard_target <= 0:
            diagnostics['blocked_invalid_rounded_barrier'] += 1
            return False

        stop_fill = stop * (1 - side * stress_slip)
        unit_loss = (
            side * (entry_fill - stop_fill)
            + stress_fee * (entry_fill + stop_fill)
        )
        if not np.isfinite(unit_loss) or unit_loss <= 0:
            diagnostics['blocked_invalid_unit_risk'] += 1
            return False
        risk_budget = min(
            config.fixed_risk_usd,
            config.risk_fraction * min(cash, initial_capital),
        )
        unrounded_quantity = min(
            risk_budget / unit_loss,
            config.maximum_notional_equity * cash / entry_fill,
            cash * config.maximum_isolated_leverage / entry_fill,
            float(candidate['liquidity_notional_cap_usd']) / entry_fill,
        )
        quantity = _round_down_step(unrounded_quantity, QUANTITY_STEPS[symbol])
        if not np.isfinite(quantity) or quantity <= 0:
            diagnostics['blocked_size'] += 1
            return False
        notional = quantity * entry_fill
        if notional + 1e-12 < config.minimum_notional_usd:
            diagnostics['blocked_minimum_notional'] += 1
            return False
        if notional > float(candidate['liquidity_notional_cap_usd']) + 1e-9:
            raise AssertionError('Liquidity sizing cap was exceeded')

        partial_qty = _round_down_step(
            quantity * config.partial_fraction,
            QUANTITY_STEPS[symbol],
        )
        remaining_qty = quantity - partial_qty
        partial_enabled = (
            partial_qty > 0
            and remaining_qty > 0
            and partial_qty * partial_target + 1e-12
            >= config.minimum_notional_usd
            and remaining_qty * partial_target + 1e-12
            >= config.minimum_notional_usd
        )
        entry_fee = quantity * entry_fill * fee
        position = {
            'candidate': candidate,
            'symbol': symbol,
            'side': side,
            'opened_at': timestamp,
            'entry_reference': reference,
            'entry_fill': entry_fill,
            'atr': atr,
            'stop': stop,
            'initial_stop': stop,
            'partial_target': partial_target,
            'hard_target': hard_target,
            'price_r': price_r,
            'qty': quantity,
            'initial_qty': quantity,
            'partial_qty': partial_qty,
            'partial_enabled': partial_enabled,
            'partial_taken': False,
            'initial_margin': notional / config.maximum_isolated_leverage,
            'risk_budget': risk_budget,
            'initial_risk': quantity * unit_loss,
            'cash_before': cash,
            'fees': entry_fee,
            'gross_pnl': 0.0,
            'funding_pnl': 0.0,
            'reached_1r': False,
            'reached_1_5r': False,
            'breakeven_armed': False,
            'trailing_armed': False,
            'mfe_r': 0.0,
            'best_close': None,
            'recent_lows': [],
            'recent_highs': [],
            'scheduled_exit': None,
            'stop_updates': [],
            'exits': [],
        }
        record_cash_change(-entry_fee, timestamp)
        diagnostics['entries'] += 1
        diagnostics[f'entries_{symbol}'] += 1
        diagnostics[f'entries_{candidate["regime"]}'] += 1
        if not partial_enabled:
            diagnostics['partial_not_executable'] += 1
        return True

    for timestamp in pd.date_range(start, end, freq='5min', inclusive='left'):
        raw_open = None
        if position is not None:
            raw_open = float(
                markets[position['symbol']]['perpetual'].at[timestamp, 'open'])
        open_equity = cash if position is None else marked(raw_open)
        day = timestamp.date()
        iso = timestamp.isocalendar()
        week = (iso.year, iso.week)
        if day != current_day:
            current_day, day_start_equity = day, open_equity
            day_realised_anchor, day_blocked = realised_total, False
        if week != current_week:
            current_week, week_start_equity = week, open_equity
            week_realised_anchor, week_blocked = realised_total, False

        closed_at_open = False
        if position is not None and timestamp in funding_maps[position['symbol']]:
            mark_time = timestamp - pd.Timedelta(minutes=5)
            mark = markets[position['symbol']]['mark']
            if mark_time not in mark.index:
                raise ValueError(f'Missing open-position funding mark at {mark_time}')
            payment = (
                -position['side'] * position['qty']
                * float(mark.at[mark_time, 'close'])
                * float(funding_maps[position['symbol']][timestamp])
            )
            record_cash_change(payment, timestamp)
            position['funding_pnl'] += payment

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            gap = (
                row.open <= position['stop']
                if position['side'] == 1
                else row.open >= position['stop']
            )
            if gap:
                close_position(float(row.open), timestamp, 'STOP_GAP')
                closed_at_open = True

        if position is not None and position['scheduled_exit'] is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            reason = position['scheduled_exit']
            close_position(float(row.open), timestamp, reason)
            closed_at_open = True

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            open_equity = marked(float(row.open))
            peak_equity = max(peak_equity, open_equity)
            if 1 - open_equity / peak_equity >= config.drawdown_kill_fraction:
                close_position(float(row.open), timestamp, 'RISK_DRAWDOWN_OPEN')
                closed_at_open, risk_fail = True, True
                diagnostics['drawdown_kills'] += 1

        refresh_realised_stops()
        arrivals = candidates_by_time.get(timestamp, [])
        diagnostics['qualified_candidates'] += len(arrivals)
        if arrivals and position is not None:
            diagnostics['blocked_open_position'] += len(arrivals)
        elif arrivals and closed_at_open:
            diagnostics['blocked_same_bar_reentry'] += len(arrivals)
        elif arrivals and (day_blocked or week_blocked or risk_fail or cash <= 0):
            diagnostics['blocked_risk_halt_or_capital'] += len(arrivals)
        else:
            for candidate in arrivals:
                if enter(candidate, timestamp):
                    break

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            side = position['side']
            stop_hit = (
                row.low <= position['stop']
                if side == 1 else row.high >= position['stop'])
            hard_target_hit = (
                row.high >= position['hard_target']
                if side == 1 else row.low <= position['hard_target'])
            partial_target_hit = (
                row.high >= position['partial_target']
                if side == 1 else row.low <= position['partial_target'])
            if stop_hit:
                raw = (
                    min(float(row.open), position['stop'])
                    if side == 1
                    else max(float(row.open), position['stop'])
                )
                close_position(
                    raw, timestamp + pd.Timedelta(minutes=5), 'STOP')
            elif hard_target_hit:
                if position['partial_enabled'] and not position['partial_taken']:
                    reduce_position(
                        position['partial_qty'],
                        position['partial_target'],
                        timestamp + pd.Timedelta(minutes=5),
                        'PARTIAL_1R',
                    )
                    position['partial_taken'] = True
                close_position(
                    position['hard_target'],
                    timestamp + pd.Timedelta(minutes=5),
                    'TARGET_4R',
                )
            else:
                favorable = (
                    float(row.high) - position['entry_fill']
                    if side == 1
                    else position['entry_fill'] - float(row.low)
                )
                position['mfe_r'] = max(
                    position['mfe_r'], favorable / position['price_r'])
                if partial_target_hit:
                    position['reached_1r'] = True
                    if position['partial_enabled'] and not position['partial_taken']:
                        reduce_position(
                            position['partial_qty'],
                            position['partial_target'],
                            timestamp + pd.Timedelta(minutes=5),
                            'PARTIAL_1R',
                        )
                        position['partial_taken'] = True
                if position is not None:
                    trigger_1_5 = position['entry_fill'] + side * (
                        config.trailing_trigger_r * position['price_r'])
                    if (
                        float(row.high) >= trigger_1_5
                        if side == 1 else float(row.low) <= trigger_1_5
                    ):
                        position['reached_1_5r'] = True

                    close_time = timestamp + pd.Timedelta(minutes=5)
                    close_value = float(row.close)
                    position['recent_lows'].append(float(row.low))
                    position['recent_highs'].append(float(row.high))
                    position['recent_lows'] = position['recent_lows'][
                        -config.trailing_swing_bars:]
                    position['recent_highs'] = position['recent_highs'][
                        -config.trailing_swing_bars:]
                    if position['best_close'] is None:
                        position['best_close'] = close_value
                    elif side == 1:
                        position['best_close'] = max(
                            position['best_close'], close_value)
                    else:
                        position['best_close'] = min(
                            position['best_close'], close_value)

                    if position['reached_1r'] and not position['breakeven_armed']:
                        improve_stop(
                            _cost_breakeven_stop(
                                position['entry_fill'], side, config),
                            close_time,
                            'STRESS_COST_BE_PLUS_2BPS',
                        )
                        position['breakeven_armed'] = True

                    if position['reached_1_5r']:
                        cost_be = _cost_breakeven_stop(
                            position['entry_fill'], side, config)
                        if side == 1:
                            trail = max(
                                cost_be,
                                position['best_close']
                                - config.trailing_atr * position['atr'],
                                min(position['recent_lows'])
                                - config.atr_stop_buffer * position['atr'],
                            )
                        else:
                            trail = min(
                                cost_be,
                                position['best_close']
                                + config.trailing_atr * position['atr'],
                                max(position['recent_highs'])
                                + config.atr_stop_buffer * position['atr'],
                            )
                        improve_stop(trail, close_time, 'TRAIL_1P5R')
                        position['trailing_armed'] = True

                    elapsed = close_time - position['opened_at']
                    marked_trade_pnl = marked(close_value) - position['cash_before']
                    if (
                        position['scheduled_exit'] is None
                        and elapsed >= pd.Timedelta(
                            minutes=config.stagnation_minutes)
                        and position['mfe_r'] < config.stagnation_mfe_r
                        and marked_trade_pnl <= 0
                    ):
                        position['scheduled_exit'] = 'STAGNATION_60M'
                    elif (
                        position['scheduled_exit'] is None
                        and not position['reached_1r']
                        and elapsed >= pd.Timedelta(
                            minutes=config.unreached_target_minutes)
                    ):
                        position['scheduled_exit'] = 'TIME_120M'
                    elif (
                        position['scheduled_exit'] is None
                        and position['reached_1r']
                        and elapsed >= pd.Timedelta(
                            minutes=config.reached_target_minutes)
                    ):
                        position['scheduled_exit'] = 'TIME_180M'

        close_time = timestamp + pd.Timedelta(minutes=5)
        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            current_equity = marked(float(row.close))
        else:
            current_equity = cash
        peak_equity = max(peak_equity, current_equity)
        if (
            position is not None
            and 1 - current_equity / peak_equity
            >= config.drawdown_kill_fraction
        ):
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            close_position(
                float(row.close), close_time, 'RISK_DRAWDOWN_CLOSE')
            current_equity, risk_fail = cash, True
            diagnostics['drawdown_kills'] += 1
        elif (
            position is None
            and 1 - current_equity / peak_equity
            >= config.drawdown_kill_fraction
        ):
            if not risk_fail:
                diagnostics['drawdown_kills'] += 1
            risk_fail = True

        refresh_realised_stops()
        if close_time == end and position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            close_position(float(row.close), close_time, 'END_OF_TEST')
            current_equity = cash
        equity_curve.append({
            'timestamp': str(close_time),
            'equity': current_equity,
        })

    pnls = np.asarray([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.asarray(
        [initial_capital] + [point['equity'] for point in equity_curve],
        dtype=float,
    )
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    monthly_pnl = Counter()
    for day_key, pnl in daily_pnl.items():
        monthly_pnl[str(pd.Timestamp(day_key).to_period('M'))] += float(pnl)
    return {
        'config': {
            **asdict(config),
            'round_trip_bps': config.costs.round_trip_bps,
        },
        'window': [str(start), str(end)],
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100)
            if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else (
                'Infinity' if gains else None),
            'net_pnl': cash - initial_capital,
            'return_pct': (cash / initial_capital - 1) * 100,
            'max_drawdown_pct': float(drawdowns.max())
            if len(drawdowns) else 0.0,
            'mean_net_r': float(np.mean([
                trade['r_multiple'] for trade in trades
            ])) if trades else 0.0,
            'fees': float(sum(trade['fees'] for trade in trades)),
            'funding_pnl': float(sum(
                trade['funding_pnl'] for trade in trades)),
            'daily_pnl': dict(sorted(daily_pnl.items())),
            'weekly_pnl': dict(sorted(weekly_pnl.items())),
            'monthly_pnl': dict(sorted(monthly_pnl.items())),
            'drawdown_halted': risk_fail,
            'risk_fail': risk_fail,
            'diagnostics': dict(diagnostics),
        },
        'candidates': normalized,
        'invalidated_candidates': invalidated,
        'trades': trades,
        'equity_curve': equity_curve,
    }


__all__ = [
    'FRSCosts',
    'FRSPortfolioConfig',
    'simulate_funding_regime_switch_portfolio',
]
