"""FCM-1M: causal monthly funding carry with distinct spot/perp/mark prices."""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class FCMCosts:
    spot_fee_bps: float = 10.0
    futures_fee_bps: float = 2.0
    spot_slippage_bps: float = 1.0
    futures_slippage_bps: float = 1.0

    @property
    def round_trip_bps(self) -> float:
        return 2 * (
            self.spot_fee_bps + self.futures_fee_bps
            + self.spot_slippage_bps + self.futures_slippage_bps
        )


@dataclass(frozen=True)
class FCMConfig:
    name: str = 'FCM_1M'
    spot_notional_usd: float = 100.0
    futures_margin_usd: float = 100.0
    reserve_usd: float = 50.0
    qualification_funding_bps: float = 50.0
    return_lookback_days: int = 30
    ema_span_days: int = 50
    decision_delay_hours: int = 1
    max_execution_delay_hours: int = 168
    max_initial_futures_leverage: float = 1.05
    force_monthly_reset: bool = False
    emergency_futures_equity_floor_usd: float | None = None
    emergency_max_mark_leverage: float | None = None
    emergency_detection_delay_minutes: int = 60
    quantity_steps: tuple[tuple[str, float], ...] = ()
    minimum_futures_notionals: tuple[tuple[str, float], ...] = ()
    costs: FCMCosts = FCMCosts()

    def validate(self, initial_capital: float) -> None:
        if min(self.spot_notional_usd, self.futures_margin_usd, self.reserve_usd) < 0:
            raise ValueError('Allocation values cannot be negative')
        if self.spot_notional_usd + self.futures_margin_usd + self.reserve_usd > initial_capital:
            raise ValueError('FCM allocation exceeds initial capital')
        if self.return_lookback_days < 1 or self.ema_span_days < 2:
            raise ValueError('Invalid trend lookback')
        if self.decision_delay_hours < 1:
            raise ValueError('Decision delay must prevent close/open simultaneity lookahead')
        if self.max_execution_delay_hours < 1:
            raise ValueError('Execution-delay cap must be positive')
        if self.max_initial_futures_leverage <= 0:
            raise ValueError('Futures leverage cap must be positive')
        if (self.emergency_futures_equity_floor_usd is not None
                and not 0 < self.emergency_futures_equity_floor_usd
                < self.futures_margin_usd):
            raise ValueError('Emergency equity floor must be between zero and margin')
        if (self.emergency_max_mark_leverage is not None
                and self.emergency_max_mark_leverage <= 0):
            raise ValueError('Emergency mark leverage cap must be positive')
        if self.emergency_detection_delay_minutes < 1:
            raise ValueError('Emergency detection delay must be at least one minute')
        for name, rows in (
                ('quantity step', self.quantity_steps),
                ('minimum futures notional', self.minimum_futures_notionals)):
            keys = [symbol for symbol, _value in rows]
            if len(keys) != len(set(keys)) or any(value <= 0 for _symbol, value in rows):
                raise ValueError(f'Invalid {name} table')


def executable_hedge_quantity(symbol: str, spot_price: float,
                              perpetual_price: float,
                              config: FCMConfig) -> dict:
    """Round down to a common executable lot without creating delta drift."""
    if spot_price <= 0 or perpetual_price <= 0:
        raise ValueError('Hedge prices must be positive')
    raw_quantity = config.spot_notional_usd / spot_price
    quantity_step = dict(config.quantity_steps).get(symbol)
    quantity = raw_quantity
    if quantity_step is not None:
        quantity = float(np.floor(
            (raw_quantity + 1e-12) / quantity_step) * quantity_step)
        quantity = round(quantity, 12)
    if quantity <= 0:
        raise ValueError(f'Quantity rounds to zero for {symbol}')
    perpetual_notional = quantity * perpetual_price
    minimum_notional = dict(config.minimum_futures_notionals).get(symbol, 0.0)
    if perpetual_notional < minimum_notional:
        raise ValueError(
            f'Futures minimum notional not met for {symbol}: '
            f'{perpetual_notional:.6f} < {minimum_notional:.6f}')
    return {
        'quantity': quantity,
        'raw_quantity': raw_quantity,
        'quantity_step': quantity_step,
        'perpetual_notional': perpetual_notional,
        'unused_spot_notional': config.spot_notional_usd - quantity * spot_price,
    }


def previous_month_funding_bps(rates: pd.Series, decision_time) -> float:
    decision = _utc(decision_time)
    month = decision.tz_localize(None).to_period('M')
    start = (month - 1).start_time.tz_localize('UTC')
    end = month.start_time.tz_localize('UTC')
    return float(rates.loc[(rates.index >= start) & (rates.index < end)].sum() * 10_000)


def _trend_snapshot(spot: pd.DataFrame, decision_time, config: FCMConfig) -> dict:
    decision = _utc(decision_time)
    daily = spot['close'].resample('1D').last()
    history = daily.loc[daily.index < decision.normalize()].dropna()
    minimum = max(config.ema_span_days, config.return_lookback_days + 1)
    if len(history) < minimum:
        raise ValueError(f'Need at least {minimum} completed daily closes before {decision}')
    last_time = history.index[-1]
    base_time = last_time - pd.Timedelta(days=config.return_lookback_days)
    if base_time not in history.index:
        raise ValueError(f'Missing exact {config.return_lookback_days}-day reference close')
    close = float(history.iloc[-1])
    ema = float(history.ewm(
        span=config.ema_span_days, adjust=False,
        min_periods=config.ema_span_days,
    ).mean().iloc[-1])
    return {
        'feature_cutoff': last_time,
        'close': close,
        'ema50': ema,
        'return_30d_pct': (close / float(history.at[base_time]) - 1) * 100,
    }


def monthly_fcm_targets(spot_prices: dict[str, pd.DataFrame],
                        rates: dict[str, pd.Series], start, end,
                        config: FCMConfig) -> list[dict]:
    """Rank only assets passing all three frozen prior-information filters."""
    start, end = _utc(start), _utc(end)
    if start != start.normalize() or start.day != 1:
        raise ValueError('FCM windows must start at a UTC month boundary')
    if set(spot_prices) != set(rates):
        raise ValueError('Spot and funding universes differ')
    schedule = []
    current = None
    for decision in pd.date_range(start, end, freq='MS', inclusive='left'):
        features, qualified = {}, []
        for symbol in sorted(spot_prices):
            trend = _trend_snapshot(spot_prices[symbol], decision, config)
            funding = previous_month_funding_bps(rates[symbol], decision)
            passed = (
                funding >= config.qualification_funding_bps
                and trend['return_30d_pct'] > 0
                and trend['close'] > trend['ema50']
            )
            features[symbol] = {
                **trend,
                'prior_month_funding_bps': funding,
                'qualified': passed,
            }
            if passed:
                qualified.append(symbol)
        target = max(
            qualified,
            key=lambda symbol: (features[symbol]['prior_month_funding_bps'], symbol),
            default=None,
        )
        if target is None:
            reason = 'exit_or_hold_cash_no_qualified_asset'
        elif target == current:
            reason = 'monthly_requalification_hold'
        elif current is None:
            reason = 'enter_highest_qualified_funding'
        else:
            reason = 'switch_to_highest_qualified_funding'
        schedule.append({
            'decision_time': decision,
            'action_time': decision + pd.Timedelta(hours=config.decision_delay_hours),
            'target': target,
            'reason': reason,
            'features': features,
        })
        current = target
    return schedule


def _price(frame: pd.DataFrame, timestamp, column='open', require_observed=False) -> float:
    timestamp = _utc(timestamp)
    try:
        value = float(frame.at[timestamp, column])
    except KeyError as exc:
        raise ValueError(f'Missing {column} at {timestamp}') from exc
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f'Invalid {column} at {timestamp}')
    if require_observed and 'observed' in frame and not bool(frame.at[timestamp, 'observed']):
        raise ValueError(f'Synthetic {column} cannot be used as a fill at {timestamp}')
    return value


def _price_asof(frame: pd.DataFrame, timestamp, column='open') -> float:
    timestamp = _utc(timestamp)
    history = frame.loc[frame.index <= timestamp, column]
    if history.empty:
        raise ValueError(f'No causal {column} at or before {timestamp}')
    value = float(history.iloc[-1])
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f'Invalid causal {column} at or before {timestamp}')
    return value


def simulate_fcm(spot_prices: dict[str, pd.DataFrame],
                 perpetual_prices: dict[str, pd.DataFrame],
                 mark_prices: dict[str, pd.DataFrame],
                 rates: dict[str, pd.Series], start, end, config: FCMConfig,
                 initial_capital=250.0,
                 emergency_spot_prices: dict[str, pd.DataFrame] | None = None,
                 emergency_perpetual_prices: dict[str, pd.DataFrame] | None = None,
                 emergency_mark_prices: dict[str, pd.DataFrame] | None = None) -> dict:
    """Replay one $100 spot-long/equal-quantity perp-short hedge at a time."""
    config.validate(initial_capital)
    symbols = set(spot_prices)
    if symbols != set(perpetual_prices) or symbols != set(mark_prices) or symbols != set(rates):
        raise ValueError('Spot, perpetual, mark and funding universes differ')
    emergency_spot_prices = emergency_spot_prices or spot_prices
    emergency_perpetual_prices = emergency_perpetual_prices or perpetual_prices
    emergency_mark_prices = emergency_mark_prices or mark_prices
    if (symbols != set(emergency_spot_prices)
            or symbols != set(emergency_perpetual_prices)
            or symbols != set(emergency_mark_prices)):
        raise ValueError('Emergency price universes differ')
    start, end = _utc(start), _utc(end)
    schedule = monthly_fcm_targets(spot_prices, rates, start, end, config)
    ledger, episodes = [], []
    execution_actions = []
    position = None

    def next_joint_execution_time(requested, required_symbols, hard_deadline=None,
                                  price_sets=None):
        deadline = requested + pd.Timedelta(hours=config.max_execution_delay_hours)
        if hard_deadline is not None:
            deadline = min(deadline, _utc(hard_deadline))
        common = None
        price_sets = price_sets or (spot_prices, perpetual_prices)
        for symbol in required_symbols:
            indices = []
            for prices in price_sets:
                frame = prices[symbol]
                eligible = frame.loc[(frame.index >= requested) & (frame.index <= deadline)]
                if 'observed' in eligible:
                    eligible = eligible.loc[eligible.observed.astype(bool)]
                indices.append(eligible.index)
            symbol_common = indices[0].intersection(indices[1])
            common = symbol_common if common is None else common.intersection(symbol_common)
        return common[0] if common is not None and len(common) else None

    def book(timestamp, amount, kind, symbol, pnl_effect=True):
        ledger.append({
            'timestamp': _utc(timestamp), 'amount': float(amount), 'kind': kind,
            'symbol': symbol, 'pnl_effect': bool(pnl_effect),
        })

    def open_position(symbol, timestamp):
        nonlocal position
        spot_ref = _price(spot_prices[symbol], timestamp, require_observed=True)
        perpetual_ref = _price(
            perpetual_prices[symbol], timestamp, require_observed=True)
        spot_fill = spot_ref * (1 + config.costs.spot_slippage_bps / 10_000)
        perpetual_fill = perpetual_ref * (1 - config.costs.futures_slippage_bps / 10_000)
        hedge = executable_hedge_quantity(
            symbol, spot_fill, perpetual_fill, config)
        quantity = hedge['quantity']
        perpetual_notional = hedge['perpetual_notional']
        initial_leverage = perpetual_notional / config.futures_margin_usd
        if initial_leverage > config.max_initial_futures_leverage:
            raise ValueError(f'Initial futures leverage cap exceeded: {initial_leverage:.4f}')
        spot_fee = quantity * spot_fill * config.costs.spot_fee_bps / 10_000
        futures_fee = perpetual_notional * config.costs.futures_fee_bps / 10_000
        capital_before_entry = initial_capital + sum(
            episode['pnl'] for episode in episodes)
        free_cash_after_entry = (
            capital_before_entry - quantity * spot_fill
            - config.futures_margin_usd - spot_fee - futures_fee
        )
        if free_cash_after_entry < 0:
            raise ValueError(
                f'Insufficient pathwise capital at {timestamp}: '
                f'{free_cash_after_entry:.6f} USD after entry')
        book(timestamp, -quantity * spot_fill, 'spot_purchase', symbol, pnl_effect=False)
        book(timestamp, -spot_fee, 'spot_entry_fee', symbol)
        book(timestamp, -config.futures_margin_usd, 'futures_margin_lock', symbol,
             pnl_effect=False)
        book(timestamp, -futures_fee, 'futures_entry_fee', symbol)
        position = {
            'symbol': symbol,
            'opened_at': _utc(timestamp),
            'quantity': quantity,
            'raw_quantity_before_lot_rounding': hedge['raw_quantity'],
            'quantity_step': hedge['quantity_step'],
            'unused_spot_notional_after_rounding': hedge['unused_spot_notional'],
            'spot_entry_reference': spot_ref,
            'spot_entry_fill': spot_fill,
            'perpetual_entry_reference': perpetual_ref,
            'perpetual_entry_fill': perpetual_fill,
            'spot_entry_fee': spot_fee,
            'futures_entry_fee': futures_fee,
            'entry_basis_bps': (perpetual_ref / spot_ref - 1) * 10_000,
            'initial_futures_notional': perpetual_notional,
            'initial_futures_leverage': initial_leverage,
            'capital_before_entry': capital_before_entry,
            'free_cash_after_entry': free_cash_after_entry,
        }

    def futures_risk_curve(active_position, timestamp):
        """Exit-ready short equity using completed hourly mark highs.

        A high from hour H can only trigger at H+1.  The curve also reserves the
        futures exit fee, so the circuit breaker does not spend that amount twice.
        """
        timestamp = _utc(timestamp)
        symbol, quantity = active_position['symbol'], active_position['quantity']
        risk_marks = emergency_mark_prices[symbol]
        marks = risk_marks.loc[
            (risk_marks.index >= active_position['opened_at'])
            & (risk_marks.index < timestamp)
        ]
        if marks.empty:
            return pd.DataFrame(columns=('mark_high', 'funding', 'equity', 'leverage'))
        mark_high = marks['high'].astype(float)
        funding_events = pd.Series(0.0, index=mark_high.index)
        settlements = rates[symbol].loc[
            (rates[symbol].index > active_position['opened_at'])
            & (rates[symbol].index <= mark_high.index[-1])
        ]
        for funding_time, rate in settlements.items():
            if funding_time in funding_events.index:
                funding_events.at[funding_time] += (
                    quantity * _price(mark_prices[symbol], funding_time) * float(rate)
                )
        # Funding receipts are deliberately excluded from the safety buffer;
        # only adverse funding payments can reduce the amount available to exit.
        funding_curve = funding_events.clip(upper=0.0).cumsum()
        estimated_exit_fee = (
            quantity * mark_high * config.costs.futures_fee_bps / 10_000)
        equity = (
            config.futures_margin_usd
            + quantity * (active_position['perpetual_entry_fill'] - mark_high)
            + funding_curve - active_position['futures_entry_fee']
            - estimated_exit_fee
        )
        leverage = quantity * mark_high / equity.where(equity > 0)
        return pd.DataFrame({
            'mark_high': mark_high,
            'funding': funding_curve,
            'equity': equity,
            'leverage': leverage,
        })

    def first_emergency(active_position, through):
        if (config.emergency_futures_equity_floor_usd is None
                and config.emergency_max_mark_leverage is None):
            return None
        risk = futures_risk_curve(active_position, through)
        if risk.empty:
            return None
        equity_breach = pd.Series(False, index=risk.index)
        leverage_breach = pd.Series(False, index=risk.index)
        if config.emergency_futures_equity_floor_usd is not None:
            equity_breach = risk.equity < config.emergency_futures_equity_floor_usd
        if config.emergency_max_mark_leverage is not None:
            leverage_breach = risk.leverage > config.emergency_max_mark_leverage
        breached = equity_breach | leverage_breach
        if not breached.any():
            return None
        breach_time = breached[breached].index[0]
        reasons = []
        if bool(equity_breach.at[breach_time]):
            reasons.append('futures_equity_floor')
        if bool(leverage_breach.at[breach_time]):
            reasons.append('mark_leverage_cap')
        return {
            'breach_bar_time': breach_time,
            'requested_exit_time': breach_time + pd.Timedelta(
                minutes=config.emergency_detection_delay_minutes),
            'reason': '+'.join(reasons),
            'equity_usd': float(risk.at[breach_time, 'equity']),
            'mark_leverage': float(risk.at[breach_time, 'leverage']),
        }

    def close_position(timestamp, close_reason='scheduled',
                       execution_spot_prices=None,
                       execution_perpetual_prices=None):
        nonlocal position
        if position is None:
            return
        timestamp = _utc(timestamp)
        symbol, quantity = position['symbol'], position['quantity']
        execution_spot_prices = execution_spot_prices or spot_prices
        execution_perpetual_prices = (
            execution_perpetual_prices or perpetual_prices)
        spot_ref = _price(
            execution_spot_prices[symbol], timestamp, require_observed=True)
        perpetual_ref = _price(
            execution_perpetual_prices[symbol], timestamp,
            require_observed=True)
        spot_fill = spot_ref * (1 - config.costs.spot_slippage_bps / 10_000)
        perpetual_fill = perpetual_ref * (1 + config.costs.futures_slippage_bps / 10_000)
        spot_exit_fee = quantity * spot_fill * config.costs.spot_fee_bps / 10_000
        futures_exit_fee = quantity * perpetual_fill * config.costs.futures_fee_bps / 10_000
        settlements = rates[symbol].loc[
            (rates[symbol].index > position['opened_at'])
            & (rates[symbol].index <= timestamp)
        ]
        funding_pnl = 0.0
        for funding_time, rate in settlements.items():
            payment = quantity * _price(mark_prices[symbol], funding_time) * float(rate)
            funding_pnl += payment
            book(funding_time, payment, 'funding', symbol)
        spot_pnl = quantity * (spot_fill - position['spot_entry_fill'])
        futures_pnl = quantity * (position['perpetual_entry_fill'] - perpetual_fill)
        price_basis_pnl = quantity * (
            (spot_ref - position['spot_entry_reference'])
            + (position['perpetual_entry_reference'] - perpetual_ref)
        )
        fees = (
            position['spot_entry_fee'] + position['futures_entry_fee']
            + spot_exit_fee + futures_exit_fee
        )
        slippage = price_basis_pnl - spot_pnl - futures_pnl
        pnl = spot_pnl + futures_pnl + funding_pnl - fees
        book(timestamp, quantity * spot_fill, 'spot_sale', symbol, pnl_effect=False)
        book(timestamp, -spot_exit_fee, 'spot_exit_fee', symbol)
        book(timestamp, futures_pnl, 'futures_variation_pnl', symbol)
        book(timestamp, -futures_exit_fee, 'futures_exit_fee', symbol)
        book(timestamp, config.futures_margin_usd, 'futures_margin_release', symbol,
             pnl_effect=False)

        marks = mark_prices[symbol].loc[
            (mark_prices[symbol].index >= position['opened_at'])
            & (mark_prices[symbol].index <= timestamp), 'open'
        ].astype(float)
        funding_curve = settlements.reindex(marks.index, fill_value=0.0)
        funding_curve = (funding_curve * quantity * marks).cumsum()
        futures_equity = (
            config.futures_margin_usd
            + quantity * (position['perpetual_entry_fill'] - marks)
            + funding_curve - position['futures_entry_fee']
        )
        leverage = quantity * marks / futures_equity.where(futures_equity > 0)
        spot_slice = spot_prices[symbol]['open'].reindex(marks.index, method='ffill').astype(float)
        perpetual_slice = perpetual_prices[symbol]['open'].reindex(
            marks.index, method='ffill').astype(float)
        basis_bps = (perpetual_slice / spot_slice - 1) * 10_000
        high_risk = futures_risk_curve(position, timestamp)
        episodes.append({
            **position,
            'closed_at': timestamp,
            'close_reason': close_reason,
            'spot_exit_reference': spot_ref,
            'spot_exit_fill': spot_fill,
            'perpetual_exit_reference': perpetual_ref,
            'perpetual_exit_fill': perpetual_fill,
            'exit_basis_bps': (perpetual_ref / spot_ref - 1) * 10_000,
            'spot_exit_fee': spot_exit_fee,
            'futures_exit_fee': futures_exit_fee,
            'spot_pnl_after_slippage': spot_pnl,
            'futures_pnl_after_slippage': futures_pnl,
            'price_basis_pnl_before_costs': price_basis_pnl,
            'funding_pnl': funding_pnl,
            'fees': fees,
            'slippage_cost': slippage,
            'pnl': pnl,
            'funding_settlements': int(len(settlements)),
            'min_futures_equity_usd': float(futures_equity.min()),
            'max_mark_leverage': float(leverage.max()) if leverage.notna().any() else None,
            'min_exit_ready_futures_equity_usd': (
                float(high_risk.equity.min()) if not high_risk.empty
                else float(config.futures_margin_usd - position['futures_entry_fee'])
            ),
            'max_high_mark_leverage': (
                float(high_risk.leverage.max())
                if not high_risk.empty and high_risk.leverage.notna().any()
                else position['initial_futures_leverage']
            ),
            'max_abs_basis_bps': float(basis_bps.abs().max()),
            'maintenance_margin_modelled': False,
        })
        position = None

    for item in schedule:
        if position is not None:
            emergency = first_emergency(position, item['action_time'])
            if emergency is not None:
                emergency_symbol = position['symbol']
                execution_time = next_joint_execution_time(
                    emergency['requested_exit_time'], (emergency_symbol,),
                    hard_deadline=item['action_time'],
                    price_sets=(emergency_spot_prices,
                                emergency_perpetual_prices),
                )
                execution_actions.append({
                    'decision_time': emergency['breach_bar_time'],
                    'planned_action_time': emergency['requested_exit_time'],
                    'actual_action_time': execution_time,
                    'from_symbol': emergency_symbol,
                    'to_symbol': None,
                    'status': ('executed_emergency' if execution_time is not None
                               else 'skipped_emergency_no_real_fill'),
                    'action_kind': 'emergency_close',
                    'emergency_reason': emergency['reason'],
                    'breach_equity_usd': emergency['equity_usd'],
                    'breach_mark_leverage': emergency['mark_leverage'],
                })
                if execution_time is not None:
                    close_position(
                        execution_time,
                        close_reason=f'emergency_{emergency["reason"]}',
                        execution_spot_prices=emergency_spot_prices,
                        execution_perpetual_prices=emergency_perpetual_prices,
                    )
        target = item['target']
        current = position['symbol'] if position else None
        should_reset = (
            config.force_monthly_reset and target is not None and target == current)
        if target != current or should_reset:
            required = tuple(dict.fromkeys(
                symbol for symbol in (current, target) if symbol is not None))
            execution_time = next_joint_execution_time(item['action_time'], required)
            execution_actions.append({
                'decision_time': item['decision_time'],
                'planned_action_time': item['action_time'],
                'actual_action_time': execution_time,
                'from_symbol': current,
                'to_symbol': target,
                'status': 'executed' if execution_time is not None else 'skipped_no_real_fill',
                'action_kind': 'monthly_rebalance',
            })
            if execution_time is None:
                continue
            close_position(execution_time, close_reason='monthly_rebalance')
            if target is not None:
                open_position(target, execution_time)
    if position is not None:
        fill_frames = (
            spot_prices[position['symbol']], perpetual_prices[position['symbol']])
        observed_indices = []
        for frame in fill_frames:
            eligible = frame.loc[frame.index < end]
            if 'observed' in eligible:
                eligible = eligible.loc[eligible.observed.astype(bool)]
            observed_indices.append(eligible.index)
        common = observed_indices[0].intersection(observed_indices[1])
        last_common = common[-1]
        final_exit = end if all(
            end in frame.index for frame in (
                spot_prices[position['symbol']], perpetual_prices[position['symbol']],
                mark_prices[position['symbol']])) else last_common
        emergency = first_emergency(position, final_exit)
        if emergency is not None:
            emergency_symbol = position['symbol']
            execution_time = next_joint_execution_time(
                emergency['requested_exit_time'], (emergency_symbol,),
                hard_deadline=final_exit,
                price_sets=(emergency_spot_prices,
                            emergency_perpetual_prices),
            )
            execution_actions.append({
                'decision_time': emergency['breach_bar_time'],
                'planned_action_time': emergency['requested_exit_time'],
                'actual_action_time': execution_time,
                'from_symbol': emergency_symbol,
                'to_symbol': None,
                'status': ('executed_emergency' if execution_time is not None
                           else 'skipped_emergency_no_real_fill'),
                'action_kind': 'emergency_close',
                'emergency_reason': emergency['reason'],
                'breach_equity_usd': emergency['equity_usd'],
                'breach_mark_leverage': emergency['mark_leverage'],
            })
            if execution_time is not None:
                close_position(
                    execution_time,
                    close_reason=f'emergency_{emergency["reason"]}',
                    execution_spot_prices=emergency_spot_prices,
                    execution_perpetual_prices=emergency_perpetual_prices,
                )
        if position is not None:
            close_position(final_exit, close_reason='window_end')

    ledger.sort(key=lambda row: (row['timestamp'], row['kind']))
    final_time = max((episode['closed_at'] for episode in episodes), default=end)
    timeline = pd.date_range(start, final_time, freq='1h')
    equity = []
    mtm_stale_spot_hours = 0
    mtm_stale_mark_hours = 0
    for timestamp in timeline:
        realised = sum(
            episode['pnl'] for episode in episodes if episode['closed_at'] <= timestamp)
        active = next((episode for episode in episodes
                       if episode['opened_at'] <= timestamp < episode['closed_at']), None)
        unrealised = 0.0
        if active is not None:
            symbol, quantity = active['symbol'], active['quantity']
            mtm_stale_spot_hours += int(timestamp not in spot_prices[symbol].index)
            mtm_stale_mark_hours += int(timestamp not in mark_prices[symbol].index)
            funding = rates[symbol].loc[
                (rates[symbol].index > active['opened_at'])
                & (rates[symbol].index <= timestamp)
            ]
            funding_to_date = sum(
                quantity * _price(mark_prices[symbol], time) * float(rate)
                for time, rate in funding.items()
            )
            unrealised = (
                quantity * (_price_asof(spot_prices[symbol], timestamp)
                            - active['spot_entry_fill'])
                + quantity * (active['perpetual_entry_fill']
                              - _price_asof(mark_prices[symbol], timestamp))
                + funding_to_date
                - active['spot_entry_fee'] - active['futures_entry_fee']
            )
        equity.append(initial_capital + realised + unrealised)
    equity = np.asarray(equity, dtype=float)
    peaks = np.maximum.accumulate(equity) if len(equity) else np.array([initial_capital])
    drawdown = (1 - equity / peaks) * 100 if len(equity) else np.array([0.0])
    pnls = np.asarray([episode['pnl'] for episode in episodes], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    net = float(pnls.sum()) if len(pnls) else 0.0
    ledger_net = sum(row['amount'] for row in ledger)
    if not np.isclose(ledger_net, net, atol=1e-8):
        raise AssertionError(f'Ledger mismatch: {ledger_net} != {net}')

    serializable_schedule = []
    for item in schedule:
        serializable_schedule.append({
            **item,
            'decision_time': str(item['decision_time']),
            'action_time': str(item['action_time']),
            'features': {
                symbol: {**features, 'feature_cutoff': str(features['feature_cutoff'])}
                for symbol, features in item['features'].items()
            },
        })
    return {
        'config': {**asdict(config), 'round_trip_bps': config.costs.round_trip_bps},
        'window': [str(start), str(end)],
        'schedule': serializable_schedule,
        'episodes': episodes,
        'execution_actions': execution_actions,
        'ledger': ledger,
        'summary': {
            'decisions': len(schedule),
            'qualified_decisions': int(sum(item['target'] is not None for item in schedule)),
            'episodes': len(episodes),
            'winning_episodes': int((pnls > 0).sum()) if len(pnls) else 0,
            'funding_settlements': int(sum(x['funding_settlements'] for x in episodes)),
            'gross_funding_pnl': float(sum(x['funding_pnl'] for x in episodes)),
            'price_basis_pnl_before_costs': float(sum(
                x['price_basis_pnl_before_costs'] for x in episodes)),
            'fees': float(sum(x['fees'] for x in episodes)),
            'slippage_cost': float(sum(x['slippage_cost'] for x in episodes)),
            'net_pnl': net,
            'return_pct': net / initial_capital * 100,
            'episode_profit_factor': (
                gains / losses if losses else ('Infinity' if gains else None)),
            'max_mtm_drawdown_pct': float(drawdown.max()),
            'min_futures_equity_usd': min(
                (x['min_futures_equity_usd'] for x in episodes), default=None),
            'max_mark_leverage': max(
                (x['max_mark_leverage'] for x in episodes
                 if x['max_mark_leverage'] is not None), default=None),
            'min_exit_ready_futures_equity_usd': min(
                (x['min_exit_ready_futures_equity_usd'] for x in episodes),
                default=None),
            'max_high_mark_leverage': max(
                (x['max_high_mark_leverage'] for x in episodes
                 if x['max_high_mark_leverage'] is not None), default=None),
            'max_abs_basis_bps': max(
                (x['max_abs_basis_bps'] for x in episodes), default=None),
            'min_free_cash_after_entry_usd': min(
                (x['free_cash_after_entry'] for x in episodes), default=None),
            'spot_notional_deployed_usd': float(sum(
                config.spot_notional_usd
                - x['unused_spot_notional_after_rounding']
                for x in episodes)),
            'unused_spot_notional_after_rounding_usd': float(sum(
                x['unused_spot_notional_after_rounding'] for x in episodes)),
            'modelled_liquidation_breaches': int(sum(
                x['min_exit_ready_futures_equity_usd'] <= 0 for x in episodes)),
            'emergency_closes': int(sum(
                x['close_reason'].startswith('emergency_') for x in episodes)),
            'unfilled_emergency_closes': int(sum(
                row.get('action_kind') == 'emergency_close'
                and row['status'] != 'executed_emergency'
                for row in execution_actions)),
            'maintenance_margin_modelled': False,
            'mtm_stale_spot_hours': mtm_stale_spot_hours,
            'mtm_stale_mark_hours': mtm_stale_mark_hours,
            'ledger_reconciled': True,
            'delayed_execution_actions': int(sum(
                row['actual_action_time'] is not None
                and row['actual_action_time'] > row['planned_action_time']
                for row in execution_actions)),
            'skipped_execution_actions': int(sum(
                row['status'] != 'executed' for row in execution_actions)),
            'max_execution_delay_hours': max((
                (row['actual_action_time'] - row['planned_action_time']).total_seconds() / 3600
                for row in execution_actions if row['actual_action_time'] is not None
            ), default=0.0),
        },
    }
