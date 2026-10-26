"""Causal S35 post-funding exhaustion signal generation and replay.

Five-minute OHLC indices are bar-open timestamps.  A funding timestamp ``T``
is classified only after settlement, confirmation uses the complete ``T`` bar,
and the earliest possible fill is the open of the ``T + 5m`` bar.
"""
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


DEFAULT_SYMBOL_PRIORITY = (
    'SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT',
)

# Frozen research filters.  Quantities are MARKET_LOT_SIZE steps supplied by
# the protocol owner; price steps are used only to make barrier rounding
# adverse.  They must be revisited against live exchangeInfo before paper/live.
QUANTITY_STEPS = {
    'ETHUSDT': .001, 'SOLUSDT': .01, 'XRPUSDT': .1,
    'DOGEUSDT': 1.0, 'SUIUSDT': .1,
}
PRICE_TICKS = {
    'ETHUSDT': .01, 'SOLUSDT': .001, 'XRPUSDT': .0001,
    'DOGEUSDT': .00001, 'SUIUSDT': .0001,
}


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class PFECosts:
    taker_fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 10.0

    @property
    def round_trip_bps(self) -> float:
        return 2 * (self.taker_fee_bps_per_side + self.slippage_bps_per_side)


@dataclass(frozen=True)
class PFEConfig:
    name: str = 'S35_post_funding_exhaustion'
    history_events: int = 180
    funding_floor: float = .0005
    funding_quantile: float = .95
    return_quantile: float = .80
    minimum_premium: float = .0003
    premium_compression: float = .75
    atr_period: int = 14
    atr_multiple: float = 2.0
    minimum_r_fraction: float = .004
    target_r: float = 2.0
    breakeven_trigger_r: float = 1.0
    breakeven_net_bps: float = 2.0
    maximum_holding_minutes: int = 180
    risk_fraction: float = .002
    fixed_risk_usd: float = .50
    max_notional_equity: float = .50
    minimum_notional_usd: float = 20.0
    maximum_quote_volume_fraction: float = .001
    liquidity_lookback_bars: int = 12
    maximum_isolated_leverage: float = 2.0
    daily_loss_fraction: float = .006
    weekly_loss_fraction: float = .015
    drawdown_kill_fraction: float = .04
    # Cost-BE is deliberately calibrated to the frozen stress friction even
    # when the caller replays base costs.
    breakeven_fee_bps_per_side: float = 5.0
    breakeven_slippage_bps_per_side: float = 10.0
    costs: PFECosts = PFECosts()
    symbol_priority: tuple[str, ...] = DEFAULT_SYMBOL_PRIORITY

    def validate(self, initial_capital: float = 250.0) -> None:
        if initial_capital <= 0:
            raise ValueError('Initial capital must be positive')
        if self.history_events < 2 or self.atr_period < 2:
            raise ValueError('Invalid rolling history')
        if not (0 < self.funding_quantile < 1 and 0 < self.return_quantile < 1):
            raise ValueError('Invalid quantile')
        if (self.funding_floor <= 0 or self.minimum_premium <= 0
                or not 0 < self.premium_compression <= 1):
            raise ValueError('Invalid exhaustion threshold')
        if (self.atr_multiple <= 0 or self.minimum_r_fraction <= 0
                or self.target_r <= self.breakeven_trigger_r
                or self.breakeven_trigger_r <= 0):
            raise ValueError('Invalid reward/risk geometry')
        if (self.maximum_holding_minutes <= 0
                or self.maximum_holding_minutes % 5):
            raise ValueError('Holding time must be a positive 5m multiple')
        if (not 0 < self.risk_fraction < 1 or self.fixed_risk_usd <= 0
                or not 0 < self.max_notional_equity <= 1
                or self.minimum_notional_usd <= 0
                or not 0 < self.maximum_quote_volume_fraction <= 1
                or self.liquidity_lookback_bars < 1
                or self.maximum_isolated_leverage < 1):
            raise ValueError('Invalid sizing configuration')
        if (not 0 < self.daily_loss_fraction < self.weekly_loss_fraction
                or not self.weekly_loss_fraction < self.drawdown_kill_fraction < 1):
            raise ValueError('Invalid portfolio stops')
        cost_values = (
            self.costs.taker_fee_bps_per_side,
            self.costs.slippage_bps_per_side,
            self.breakeven_fee_bps_per_side,
            self.breakeven_slippage_bps_per_side,
            self.breakeven_net_bps,
        )
        if min(cost_values) < 0:
            raise ValueError('Costs cannot be negative')


def _validate_ohlc(frame: pd.DataFrame, label: str) -> None:
    required = ['open', 'high', 'low', 'close']
    if (not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None or not set(required).issubset(frame)
            or frame.empty or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing):
        raise ValueError(f'Invalid {label} 5m data')
    if not (frame.index.minute % 5 == 0).all() or not (frame.index.second == 0).all():
        raise ValueError(f'Off-grid {label} timestamps')
    values = frame[required].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values <= 0).any()
            or (frame.high < frame[required].max(axis=1)).any()
            or (frame.low > frame[required].min(axis=1)).any()):
        raise ValueError(f'Malformed {label} OHLC')


def _validate_funding(funding: pd.Series, label: str) -> pd.Series:
    if (not isinstance(funding.index, pd.DatetimeIndex)
            or funding.index.tz is None or funding.index.has_duplicates
            or not funding.index.is_monotonic_increasing):
        raise ValueError(f'Duplicate or non-causal {label} funding timestamps')
    values = funding.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f'Invalid {label} funding values')
    result = funding.astype(float).copy()
    result.index = result.index.tz_convert('UTC')
    if (not (result.index.minute % 5 == 0).all()
            or not (result.index.second == 0).all()):
        raise ValueError(f'Off-grid {label} funding timestamps')
    return result


def wilder_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR, restarted after every missing five-minute candle."""
    _validate_ohlc(frame, 'ATR')
    high = frame.high.to_numpy(dtype=float)
    low = frame.low.to_numpy(dtype=float)
    close = frame.close.to_numpy(dtype=float)
    previous = np.r_[np.nan, close[:-1]]
    true_range = np.nanmax(np.vstack([
        high - low, np.abs(high - previous), np.abs(low - previous),
    ]), axis=0)
    five_minutes_ns = int(pd.Timedelta(minutes=5).value)
    boundaries = np.r_[
        0, np.flatnonzero(np.diff(frame.index.asi8) != five_minutes_ns) + 1,
        len(frame),
    ]
    output = np.full(len(frame), np.nan, dtype=float)
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        # The first bar after a gap cannot use a pre-gap close.
        true_range[left] = high[left] - low[left]
        values = true_range[left:right]
        if len(values) < period:
            continue
        seeded = np.concatenate((
            [float(values[:period].mean())], values[period:]))
        # An EWM seeded by the first simple average is exactly Wilder's
        # recursive smoothing with alpha=1/period.
        smoothed = pd.Series(seeded, dtype=float).ewm(
            alpha=1 / period, adjust=False).mean().to_numpy(dtype=float)
        output[left + period - 1:right] = smoothed
    return pd.Series(output, index=frame.index, dtype=float)


def _event_return(perpetual: pd.DataFrame, timestamp: pd.Timestamp):
    """Return between closes exactly 60m apart, ending at settlement T."""
    newer = timestamp - pd.Timedelta(minutes=5)
    older = timestamp - pd.Timedelta(minutes=65)
    locations = perpetual.index.get_indexer([older, newer])
    if locations[0] < 0 or locations[1] - locations[0] != 12:
        return None
    return float(perpetual.at[newer, 'close'] / perpetual.at[older, 'close'] - 1)


def _candidate_for_event(symbol: str, streams: dict, funding: pd.Series,
                         event_returns: pd.Series, event_number: int, atr: pd.Series,
                         config: PFEConfig):
    """Classify one settled event using only data available by T+5m."""
    if event_number < config.history_events:
        return None
    timestamp = funding.index[event_number]
    rate = float(funding.iloc[event_number])
    history = funding.iloc[event_number - config.history_events:event_number]
    if len(history) != config.history_events:
        return None
    historical_returns = event_returns.iloc[
        event_number - config.history_events:event_number].to_numpy(dtype=float)
    current_return = float(event_returns.iloc[event_number])
    if not np.isfinite(current_return) or not np.isfinite(historical_returns).all():
        return None
    funding_threshold = max(
        config.funding_floor,
        float(np.quantile(np.abs(history.to_numpy(dtype=float)),
                          config.funding_quantile)),
    )
    return_threshold = float(np.quantile(
        np.abs(historical_returns),
        config.return_quantile,
    ))
    direction = int(np.sign(rate))
    if (direction == 0 or abs(rate) < funding_threshold
            or return_threshold <= 0 or abs(current_return) < return_threshold
            or int(np.sign(current_return)) != direction):
        return None

    before = timestamp - pd.Timedelta(minutes=5)
    after = timestamp
    required = ((streams['mark'], before), (streams['index'], before),
                (streams['mark'], after), (streams['index'], after),
                (streams['perpetual'], before), (streams['perpetual'], after))
    if any(bar_time not in frame.index for frame, bar_time in required):
        return None
    pre_premium = float(
        streams['mark'].at[before, 'close'] / streams['index'].at[before, 'close'] - 1)
    post_premium = float(
        streams['mark'].at[after, 'close'] / streams['index'].at[after, 'close'] - 1)
    reversal = float(
        streams['perpetual'].at[after, 'close']
        / streams['perpetual'].at[before, 'close'] - 1)
    atr_value = float(atr.get(after, np.nan))
    liquidity_times = pd.date_range(
        timestamp - pd.Timedelta(minutes=5 * (config.liquidity_lookback_bars - 1)),
        timestamp, freq='5min')
    perpetual = streams['perpetual']
    if ('quote_volume' not in perpetual
            or not liquidity_times.isin(perpetual.index).all()):
        return None
    quote_volume = perpetual.loc[liquidity_times, 'quote_volume'].to_numpy(dtype=float)
    if (not np.isfinite(atr_value) or atr_value <= 0
            or not np.isfinite(quote_volume).all() or (quote_volume <= 0).any()
            or int(np.sign(pre_premium)) != direction
            or abs(pre_premium) < config.minimum_premium
            or int(np.sign(reversal)) != -direction
            or abs(post_premium) > config.premium_compression * abs(pre_premium)):
        return None
    compression_component = 1 - abs(post_premium / pre_premium)
    score = (
        abs(rate) / funding_threshold
        + abs(current_return) / return_threshold
        + abs(pre_premium) / config.minimum_premium
        + compression_component
    )
    entry_time = timestamp + pd.Timedelta(minutes=5)
    minimum_quote_volume = float(quote_volume.min())
    return {
        'timestamp': entry_time,
        'funding_time': timestamp,
        'confirmation_time': entry_time,
        # The T bar closes at T+5; this is the latest feature availability.
        'feature_cutoff': entry_time,
        'symbol': symbol,
        'side': -direction,
        'score': float(score),
        'funding_rate': rate,
        'funding_threshold': funding_threshold,
        'return_60m': current_return,
        'return_threshold': return_threshold,
        'pre_premium': pre_premium,
        'post_premium': post_premium,
        'reversal_return': reversal,
        'atr': atr_value,
        'minimum_prior_12_quote_volume': minimum_quote_volume,
        'liquidity_notional_cap_usd': (
            minimum_quote_volume * config.maximum_quote_volume_fraction),
        'setup': 'POST_FUNDING_EXHAUSTION',
        'setup_id': f'S35|{symbol}|{timestamp.isoformat()}',
    }


def build_post_funding_candidates(markets: dict, start, end,
                                  config: PFEConfig | None = None) -> list[dict]:
    """Create immutable, causally timestamped candidates across all symbols."""
    config = config or PFEConfig()
    config.validate()
    start, end = _utc(start), _utc(end)
    candidates = []
    for symbol, streams in markets.items():
        if symbol not in QUANTITY_STEPS or symbol not in PRICE_TICKS:
            raise ValueError(f'No frozen order filters for {symbol}')
        if set(streams) != {'perpetual', 'mark', 'index', 'funding'}:
            raise ValueError(f'Invalid S35 streams for {symbol}')
        for stream in ('perpetual', 'mark', 'index'):
            _validate_ohlc(streams[stream], f'{symbol} {stream}')
        funding = _validate_funding(streams['funding'], symbol)
        atr = wilder_atr(streams['perpetual'], config.atr_period)
        event_returns = pd.Series([
            _event_return(streams['perpetual'], timestamp)
            for timestamp in funding.index
        ], index=funding.index, dtype=float)
        for event_number in range(config.history_events, len(funding)):
            candidate = _candidate_for_event(
                symbol, streams, funding, event_returns,
                event_number, atr, config)
            if candidate is not None and start <= candidate['timestamp'] < end:
                candidates.append(candidate)
    priority = {symbol: rank for rank, symbol in enumerate(config.symbol_priority)}
    return sorted(candidates, key=lambda row: (
        row['timestamp'], -row['score'],
        priority.get(row['symbol'], len(priority)), row['symbol']))


def _has_complete_holding_data(streams: dict, entry_time: pd.Timestamp,
                               end: pd.Timestamp, minutes: int) -> bool:
    """A missing source bar invalidates this event, never gets filled forward."""
    last = min(entry_time + pd.Timedelta(minutes=minutes),
               end - pd.Timedelta(minutes=5))
    if last < entry_time:
        return False
    expected = pd.date_range(entry_time, last, freq='5min')
    return all(expected.isin(streams[name].index).all()
               for name in ('perpetual', 'mark', 'index'))


def _cost_breakeven_stop(entry_fill: float, side: int,
                         config: PFEConfig) -> float:
    """Raw stop whose adverse stress fill targets +2 bps net."""
    fee = config.breakeven_fee_bps_per_side / 10_000
    slip = config.breakeven_slippage_bps_per_side / 10_000
    locked = config.breakeven_net_bps / 10_000
    if side == 1:
        desired_fill = entry_fill * (1 + fee + locked) / (1 - fee)
        return desired_fill / (1 - slip)
    desired_fill = entry_fill * (1 - fee - locked) / (1 + fee)
    return desired_fill / (1 + slip)


def _round_down_step(value: float, step: float) -> float:
    return float(np.floor(value / step + 1e-12) * step)


def _adverse_price_round(value: float, side: int, tick: float) -> float:
    units = value / tick
    rounded = np.floor(units + 1e-12) if side == 1 else np.ceil(units - 1e-12)
    return float(rounded * tick)


def simulate_post_funding_exhaustion(
    markets: dict,
    start,
    end,
    config: PFEConfig | None = None,
    initial_capital: float = 250.0,
    precomputed_candidates: list[dict] | None = None,
) -> dict:
    """Replay S35 with one global position and frozen portfolio controls."""
    config = config or PFEConfig()
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    if end <= start or (end - start) % pd.Timedelta(minutes=5):
        raise ValueError('Replay window must align to five minutes')
    candidates = (build_post_funding_candidates(markets, start, end, config)
                  if precomputed_candidates is None else [
                      row for row in precomputed_candidates
                      if start <= row['timestamp'] < end])
    candidates_by_time = {}
    for candidate in candidates:
        candidates_by_time.setdefault(candidate['timestamp'], []).append(candidate)
    funding_maps = {
        symbol: _validate_funding(streams['funding'], symbol).to_dict()
        for symbol, streams in markets.items()
    }

    fee = config.costs.taker_fee_bps_per_side / 10_000
    slip = config.costs.slippage_bps_per_side / 10_000
    cash = float(initial_capital)
    position = None
    trades, invalidated, equity_curve = [], [], []
    diagnostics = Counter()
    calendar_days = pd.date_range(
        start.normalize(), (end - pd.Timedelta(minutes=5)).normalize(), freq='1D')
    daily_pnl = Counter({str(day.date()): 0.0 for day in calendar_days})
    weekly_pnl = Counter()
    realised_total = 0.0
    current_day = current_week = None
    day_start_equity = week_start_equity = cash
    day_realised_anchor = week_realised_anchor = 0.0
    day_blocked = week_blocked = risk_fail = False
    peak_equity = cash

    def record_cash_change(amount: float, timestamp: pd.Timestamp) -> None:
        nonlocal cash, realised_total
        cash += amount
        realised_total += amount
        daily_pnl[str(timestamp.date())] += amount
        iso = timestamp.isocalendar()
        weekly_pnl[f'{iso.year}-W{iso.week:02d}'] += amount

    def refresh_realised_loss_stops() -> None:
        nonlocal day_blocked, week_blocked
        if (not day_blocked and realised_total - day_realised_anchor
                <= -config.daily_loss_fraction * day_start_equity):
            day_blocked = True
            diagnostics['daily_loss_stops'] += 1
        if (not week_blocked and realised_total - week_realised_anchor
                <= -config.weekly_loss_fraction * week_start_equity):
            week_blocked = True
            diagnostics['weekly_loss_stops'] += 1

    def marked(raw_price: float) -> float:
        if position is None:
            return cash
        exit_fill = raw_price * (1 - position['side'] * slip)
        gross = position['side'] * position['qty'] * (exit_fill - position['entry_fill'])
        return cash + gross - position['qty'] * exit_fill * fee

    def close_position(raw_price: float, timestamp: pd.Timestamp, reason: str) -> None:
        nonlocal position
        exit_fill = float(raw_price) * (1 - position['side'] * slip)
        exit_fee = position['qty'] * exit_fill * fee
        gross = position['side'] * position['qty'] * (
            exit_fill - position['entry_fill'])
        record_cash_change(gross - exit_fee, timestamp)
        pnl = cash - position['cash_before']
        trades.append({
            **position['candidate'],
            'opened_at': str(position['opened_at']),
            'closed_at': str(timestamp),
            'side': 'LONG' if position['side'] == 1 else 'SHORT',
            'entry_reference': position['entry_reference'],
            'entry_fill': position['entry_fill'],
            'initial_stop': position['initial_stop'],
            'final_stop': position['stop'],
            'target': position['target'],
            'price_r': position['price_r'],
            'quantity': position['qty'],
            'notional_usd': position['qty'] * position['entry_fill'],
            'initial_margin_usd': position['initial_margin'],
            'risk_budget_usd': position['risk_budget'],
            'initial_risk_usd': position['initial_risk'],
            'gross_pnl': position['gross_pnl'] + gross,
            'funding_pnl': position['funding_pnl'],
            'fees': position['fees'] + exit_fee,
            'pnl': pnl,
            'r_multiple': pnl / position['initial_risk'],
            'reason': reason,
            'stop_updates': position['stop_updates'],
        })
        position = None

    def enter(candidate: dict, timestamp: pd.Timestamp) -> bool:
        nonlocal position
        symbol, side = candidate['symbol'], int(candidate['side'])
        streams = markets[symbol]
        if (timestamp not in streams['perpetual'].index
                or not _has_complete_holding_data(
                    streams, timestamp, end, config.maximum_holding_minutes)):
            diagnostics['invalidated_missing_holding_data'] += 1
            invalidated.append(candidate)
            return False
        reference = float(streams['perpetual'].at[timestamp, 'open'])
        entry_fill = reference * (1 + side * slip)
        price_r = max(
            config.atr_multiple * float(candidate['atr']),
            config.minimum_r_fraction * entry_fill,
        )
        tick = PRICE_TICKS[symbol]
        stop = _adverse_price_round(entry_fill - side * price_r, side, tick)
        target = _adverse_price_round(
            entry_fill + side * config.target_r * price_r, side, tick)
        if stop <= 0 or target <= 0:
            diagnostics['blocked_invalid_rounded_barrier'] += 1
            return False
        # Quantity is always sized against at least the frozen stress exit
        # friction, even in a base-cost replay.  A cheaper replay therefore
        # cannot silently take more dollar risk.
        sizing_fee = max(fee, config.breakeven_fee_bps_per_side / 10_000)
        sizing_slip = max(slip, config.breakeven_slippage_bps_per_side / 10_000)
        stop_fill = stop * (1 - side * sizing_slip)
        unit_loss = (
            side * (entry_fill - stop_fill)
            + sizing_fee * (entry_fill + stop_fill)
        )
        equity = cash
        risk_budget = min(
            config.fixed_risk_usd,
            config.risk_fraction * min(equity, initial_capital),
        )
        unrounded_quantity = min(
            risk_budget / unit_loss,
            config.max_notional_equity * equity / entry_fill,
            equity * config.maximum_isolated_leverage / entry_fill,
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
        entry_fee = quantity * entry_fill * fee
        # Fractional quantity is intentional for sub-dollar XRP/DOGE/SUI.
        position = {
            'candidate': candidate, 'symbol': symbol, 'side': side,
            'opened_at': timestamp, 'entry_reference': reference,
            'entry_fill': entry_fill, 'price_r': price_r,
            'stop': stop, 'initial_stop': stop, 'target': target,
            'qty': quantity,
            'initial_margin': quantity * entry_fill / config.maximum_isolated_leverage,
            'risk_budget': risk_budget, 'initial_risk': quantity * unit_loss,
            'cash_before': cash, 'fees': entry_fee, 'gross_pnl': 0.0,
            'funding_pnl': 0.0, 'breakeven_armed': False,
            'stop_updates': [],
        }
        record_cash_change(-entry_fee, timestamp)
        diagnostics['entries'] += 1
        diagnostics[f'entries_{symbol}'] += 1
        return True

    for timestamp in pd.date_range(start, end, freq='5min', inclusive='left'):
        row = None if position is None else markets[position['symbol']]['perpetual'].loc[timestamp]
        raw_open = None if row is None else float(row.open)
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
            payment = (-position['side'] * position['qty']
                       * float(mark.at[mark_time, 'close'])
                       * float(funding_maps[position['symbol']][timestamp]))
            record_cash_change(payment, timestamp)
            position['funding_pnl'] += payment

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            side, stop = position['side'], position['stop']
            gap = row.open <= stop if side == 1 else row.open >= stop
            if gap:
                close_position(float(row.open), timestamp, 'STOP_GAP')
                closed_at_open = True

        if (position is not None and timestamp - position['opened_at']
                >= pd.Timedelta(minutes=config.maximum_holding_minutes)):
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            close_position(float(row.open), timestamp, 'TIME_180M')
            closed_at_open = True

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            open_equity = marked(float(row.open))
            peak_equity = max(peak_equity, open_equity)
            if 1 - open_equity / peak_equity >= config.drawdown_kill_fraction:
                close_position(float(row.open), timestamp, 'RISK_DRAWDOWN_OPEN')
                closed_at_open, risk_fail = True, True
                diagnostics['drawdown_kills'] += 1

        refresh_realised_loss_stops()

        arrivals = candidates_by_time.get(timestamp, [])
        diagnostics['qualified_candidates'] += len(arrivals)
        if arrivals and position is not None:
            diagnostics['blocked_open_position'] += len(arrivals)
        elif arrivals and closed_at_open:
            diagnostics['blocked_same_bar_reentry'] += len(arrivals)
        elif arrivals and (day_blocked or week_blocked or risk_fail or cash <= 0):
            diagnostics['blocked_risk_halt_or_capital'] += len(arrivals)
        elif arrivals:
            for candidate in arrivals:
                if enter(candidate, timestamp):
                    break

        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            side, stop, target = (
                position['side'], position['stop'], position['target'])
            stop_hit = row.low <= stop if side == 1 else row.high >= stop
            target_hit = row.high >= target if side == 1 else row.low <= target
            if stop_hit:
                # Deliberately adverse when both barriers occur in one candle.
                raw = min(float(row.open), stop) if side == 1 else max(float(row.open), stop)
                close_position(raw, timestamp + pd.Timedelta(minutes=5), 'STOP')
            elif target_hit:
                close_position(target, timestamp + pd.Timedelta(minutes=5), 'TARGET')
            elif not position['breakeven_armed']:
                trigger = position['entry_fill'] + side * (
                    config.breakeven_trigger_r * position['price_r'])
                reached = row.high >= trigger if side == 1 else row.low <= trigger
                if reached:
                    old_stop = position['stop']
                    new_stop = _adverse_price_round(
                        _cost_breakeven_stop(position['entry_fill'], side, config),
                        side, PRICE_TICKS[position['symbol']])
                    improves = side * (new_stop - old_stop) > 0
                    if improves:
                        position['stop'] = new_stop
                        position['stop_updates'].append({
                            'computed_at': str(timestamp + pd.Timedelta(minutes=5)),
                            'active_from': str(timestamp + pd.Timedelta(minutes=5)),
                            'old_stop': old_stop,
                            'new_stop': new_stop,
                            'reason': 'STRESS_COST_BE_PLUS_2BPS',
                        })
                    position['breakeven_armed'] = True

        close_time = timestamp + pd.Timedelta(minutes=5)
        if position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            current_equity = marked(float(row.close))
        else:
            current_equity = cash
        peak_equity = max(peak_equity, current_equity)
        if (position is not None
                and 1 - current_equity / peak_equity >= config.drawdown_kill_fraction):
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            close_position(float(row.close), close_time, 'RISK_DRAWDOWN_CLOSE')
            current_equity, risk_fail = cash, True
            diagnostics['drawdown_kills'] += 1
        elif (position is None
              and 1 - current_equity / peak_equity >= config.drawdown_kill_fraction):
            if not risk_fail:
                diagnostics['drawdown_kills'] += 1
            risk_fail = True

        refresh_realised_loss_stops()
        if close_time == end and position is not None:
            row = markets[position['symbol']]['perpetual'].loc[timestamp]
            close_position(float(row.close), close_time, 'END_OF_TEST')
            current_equity = cash
        equity_curve.append({'timestamp': str(close_time), 'equity': current_equity})

    pnls = np.asarray([trade['pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.asarray(
        [initial_capital] + [point['equity'] for point in equity_curve], dtype=float)
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100

    def cohort(selected: list[dict]) -> dict:
        selected_pnl = np.asarray([trade['pnl'] for trade in selected], dtype=float)
        return {
            'trades': len(selected),
            'wins': int((selected_pnl > 0).sum()) if len(selected_pnl) else 0,
            'net_pnl': float(selected_pnl.sum()) if len(selected_pnl) else 0.0,
            'gross_profit': float(selected_pnl[selected_pnl > 0].sum())
            if len(selected_pnl) else 0.0,
        }

    per_symbol = {
        symbol: cohort([trade for trade in trades if trade['symbol'] == symbol])
        for symbol in markets
    }
    direction_cohorts = {
        direction: cohort([trade for trade in trades if trade['side'] == direction])
        for direction in ('LONG', 'SHORT')
    }
    gross_by_symbol = [row['gross_profit'] for row in per_symbol.values()]
    daily_values = np.asarray(list(dict(sorted(daily_pnl.items())).values()), dtype=float)
    monthly_pnl = Counter()
    for day, pnl in daily_pnl.items():
        monthly_pnl[str(pd.Timestamp(day).to_period('M'))] += float(pnl)
    worst_day_index = int(np.argmin(daily_values)) if len(daily_values) else None
    daily_keys = list(dict(sorted(daily_pnl.items())))
    average_daily_pnl = float(daily_values.mean()) if len(daily_values) else 0.0
    return {
        'config': {**asdict(config),
                   'round_trip_bps': config.costs.round_trip_bps},
        'window': [str(start), str(end)],
        'summary': {
            'trades': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else (
                'Infinity' if gains else None),
            'net_pnl': cash - initial_capital,
            'return_pct': (cash / initial_capital - 1) * 100,
            'max_drawdown_pct': float(drawdowns.max()) if len(drawdowns) else 0.0,
            'mean_net_r': float(np.mean([trade['r_multiple'] for trade in trades]))
            if trades else 0.0,
            'fees': float(sum(trade['fees'] for trade in trades)),
            'funding_pnl': float(sum(trade['funding_pnl'] for trade in trades)),
            'daily_pnl': dict(sorted(daily_pnl.items())),
            'weekly_pnl': dict(sorted(weekly_pnl.items())),
            'monthly_pnl': dict(sorted(monthly_pnl.items())),
            'average_daily_pnl': average_daily_pnl,
            'median_daily_pnl': float(np.median(daily_values))
            if len(daily_values) else 0.0,
            'share_days_at_least_25_usd_pct': float(
                (daily_values >= 25).mean() * 100) if len(daily_values) else 0.0,
            'worst_day': daily_keys[worst_day_index]
            if worst_day_index is not None else None,
            'worst_day_pnl': float(daily_values[worst_day_index])
            if worst_day_index is not None else None,
            'linear_capital_for_25_average_daily_usd': (
                initial_capital * 25 / average_daily_pnl
                if average_daily_pnl > 0 else None),
            'direction_cohorts': direction_cohorts,
            'per_symbol': per_symbol,
            'represented_symbols': sum(row['trades'] > 0 for row in per_symbol.values()),
            'largest_symbol_gross_profit_share_pct': (
                max(gross_by_symbol) / sum(gross_by_symbol) * 100
                if sum(gross_by_symbol) else None),
            'drawdown_halted': risk_fail,
            'risk_fail': risk_fail,
            'diagnostics': dict(diagnostics),
        },
        'candidates': candidates,
        'invalidated_candidates': invalidated,
        'trades': trades,
        'equity_curve': equity_curve,
    }
