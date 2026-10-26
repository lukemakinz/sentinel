"""Single-venue fixed-expiry spot/futures cash-and-carry replay."""
from calendar import monthrange
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def _utc(value):
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class DatedCarryCosts:
    spot_fee_bps: float = 10.0
    futures_fee_bps: float = 2.0
    spot_slippage_bps: float = 1.0
    futures_slippage_bps: float = 1.0

    @property
    def combined_round_trip_bps(self):
        return 2 * (self.spot_fee_bps + self.futures_fee_bps
                    + self.spot_slippage_bps + self.futures_slippage_bps)


@dataclass(frozen=True)
class DatedCarryConfig:
    name: str = 'S33_dated_carry'
    spot_notional_usd: float = 50.0
    futures_margin_usd: float = 175.0
    reserve_usd: float = 25.0
    days_before_expiry: int = 30
    exit_hours_before_expiry: int = 1
    execution_delay_hours: int = 1
    minimum_premium_bps: float = 100.0
    minimum_annualized_premium_pct: float = 12.0
    minimum_futures_equity_usd: float = 100.0
    maximum_futures_mark_leverage: float = .80
    costs: DatedCarryCosts = DatedCarryCosts()

    def validate(self, initial_capital=250.0):
        if self.spot_notional_usd + self.futures_margin_usd + self.reserve_usd > initial_capital:
            raise ValueError('Dated-carry allocation exceeds capital')
        if min(self.spot_notional_usd, self.futures_margin_usd, self.reserve_usd) <= 0:
            raise ValueError('Dated-carry allocation must be positive')
        if self.days_before_expiry < 2 or self.exit_hours_before_expiry < 1:
            raise ValueError('Invalid expiry timing')
        if not 0 < self.maximum_futures_mark_leverage <= 1:
            raise ValueError('Invalid futures leverage gate')


def quarterly_expiries(start, end) -> list[pd.Timestamp]:
    """Return the last Friday of each quarter month at 08:00 UTC."""
    start, end = _utc(start), _utc(end)
    expiries = []
    for year in range(start.year - 1, end.year + 1):
        for month in (3, 6, 9, 12):
            last = pd.Timestamp(
                year=year, month=month, day=monthrange(year, month)[1],
                hour=8, tz='UTC')
            while last.weekday() != 4:
                last -= pd.Timedelta(days=1)
            if start <= last < end:
                expiries.append(last)
    return sorted(expiries)


def _validate_hourly(frame, start, end, label, allow_gaps=False):
    start, end = _utc(start), _utc(end)
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    actual = frame.loc[(frame.index >= start) & (frame.index < end)]
    complete = actual.index.equals(expected)
    valid_sparse_index = (
        allow_gaps and actual.index.isin(expected).all()
        and not actual.index.has_duplicates
        and actual.index.is_monotonic_increasing)
    if ((not complete and not valid_sparse_index) or actual.index.has_duplicates
            or not actual.index.is_monotonic_increasing):
        raise ValueError(f'Incomplete {label} hourly data')
    required = ['open', 'high', 'low', 'close']
    if not set(required).issubset(actual):
        raise ValueError(f'Missing {label} OHLC columns')
    values = actual[required].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values <= 0).any()
            or (actual.high < actual[['open', 'close', 'low']].max(axis=1)).any()
            or (actual.low > actual[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError(f'Invalid {label} OHLC')


def build_dated_carry_schedule(data: dict, start, end,
                               config: DatedCarryConfig) -> list[dict]:
    """Create one causal selection decision for each quarterly expiry."""
    start, end = _utc(start), _utc(end)
    schedule = []
    for expiry in quarterly_expiries(start, end):
        decision = expiry - pd.Timedelta(days=config.days_before_expiry)
        if decision < start:
            continue
        cutoff = decision - pd.Timedelta(hours=1)
        candidates = []
        for symbol in sorted(data):
            if (cutoff not in data[symbol]['spot'].index
                    or cutoff not in data[symbol]['futures'].index):
                continue
            spot = float(data[symbol]['spot'].at[cutoff, 'close'])
            futures = float(data[symbol]['futures'].at[cutoff, 'close'])
            premium_bps = (futures / spot - 1) * 10_000
            annualized_pct = premium_bps / 10_000 * 365 / config.days_before_expiry * 100
            if (premium_bps >= config.minimum_premium_bps
                    and annualized_pct >= config.minimum_annualized_premium_pct):
                candidates.append({
                    'symbol': symbol, 'premium_bps': premium_bps,
                    'annualized_premium_pct': annualized_pct,
                    'spot_feature_close': spot,
                    'futures_feature_close': futures,
                })
        selected = max(
            candidates, key=lambda row: (row['premium_bps'], -sorted(data).index(row['symbol'])),
            default=None,
        )
        schedule.append({
            'expiry': expiry, 'decision_time': decision,
            'feature_cutoff': cutoff,
            'entry_time': decision + pd.Timedelta(hours=config.execution_delay_hours),
            'planned_exit_time': expiry - pd.Timedelta(
                hours=config.exit_hours_before_expiry),
            'selected': selected,
            'all_candidates': candidates,
        })
    return schedule


def simulate_dated_carry(data: dict, start, end, config: DatedCarryConfig,
                         initial_capital=250.0) -> dict:
    """Replay quarterly opportunities without crossing a continuous roll."""
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    for symbol, streams in data.items():
        # Spot can have a genuine venue-halt gap. It is never filled or
        # interpolated; execution timestamps remain mandatory below. Futures
        # stays complete because it drives isolated-collateral risk every hour.
        _validate_hourly(
            streams['spot'], start, end, f'{symbol} spot', allow_gaps=True)
        _validate_hourly(streams['futures'], start, end, f'{symbol} futures')
    schedule = build_dated_carry_schedule(data, start, end, config)
    fee_spot = config.costs.spot_fee_bps / 10_000
    fee_futures = config.costs.futures_fee_bps / 10_000
    slip_spot = config.costs.spot_slippage_bps / 10_000
    slip_futures = config.costs.futures_slippage_bps / 10_000
    realised = 0.0
    trades, equity_points = [], [initial_capital]
    global_min_futures_equity = config.futures_margin_usd
    global_max_futures_leverage = 0.0

    for item in schedule:
        selected = item['selected']
        if selected is None:
            continue
        symbol = selected['symbol']
        entry_time, planned_exit = item['entry_time'], item['planned_exit_time']
        required_execution_times = (entry_time, planned_exit)
        if any(timestamp not in data[symbol]['spot'].index
               or timestamp not in data[symbol]['futures'].index
               for timestamp in required_execution_times):
            # A non-tradable decision cannot be counted as an executed episode.
            continue
        spot_reference = float(data[symbol]['spot'].at[entry_time, 'open'])
        futures_reference = float(data[symbol]['futures'].at[entry_time, 'open'])
        spot_fill = spot_reference * (1 + slip_spot)
        futures_fill = futures_reference * (1 - slip_futures)
        quantity = config.spot_notional_usd / spot_fill
        entry_spot_fee = quantity * spot_fill * fee_spot
        entry_futures_fee = quantity * futures_fill * fee_futures
        exit_time, reason = planned_exit, 'PRE_EXPIRY_EXIT'
        episode_min_equity = config.futures_margin_usd - entry_futures_fee
        episode_max_leverage = quantity * futures_fill / episode_min_equity

        # The bar stamped ``planned_exit`` closes one hour after the position
        # has already exited at that bar's open.  Stop at the preceding bar so
        # neither risk nor drawdown diagnostics can see post-exit prices.
        risk_path_end = planned_exit - pd.Timedelta(hours=1)
        for timestamp in pd.date_range(entry_time, risk_path_end, freq='1h'):
            futures_mark = float(data[symbol]['futures'].at[timestamp, 'close'])
            futures_equity = (
                config.futures_margin_usd - entry_futures_fee
                + quantity * (futures_fill - futures_mark))
            leverage = (quantity * futures_mark / futures_equity
                        if futures_equity > 0 else float('inf'))
            episode_min_equity = min(episode_min_equity, futures_equity)
            episode_max_leverage = max(episode_max_leverage, leverage)
            if timestamp in data[symbol]['spot'].index:
                spot_mark = float(data[symbol]['spot'].at[timestamp, 'close'])
                mtm = (
                    initial_capital + realised
                    + quantity * (spot_mark - spot_fill)
                    + quantity * (futures_fill - futures_mark)
                    - entry_spot_fee - entry_futures_fee)
                equity_points.append(mtm)
            if (futures_equity < config.minimum_futures_equity_usd
                    or leverage > config.maximum_futures_mark_leverage):
                requested = timestamp + pd.Timedelta(hours=1)
                if requested < planned_exit:
                    common_exit = next((candidate for candidate in pd.date_range(
                        requested, planned_exit, freq='1h')
                        if candidate in data[symbol]['spot'].index
                        and candidate in data[symbol]['futures'].index), None)
                    if common_exit is not None:
                        exit_time = common_exit
                        reason = ('RISK_FUTURES_EQUITY' if futures_equity
                                  < config.minimum_futures_equity_usd
                                  else 'RISK_FUTURES_LEVERAGE')
                        break

        spot_exit_reference = float(data[symbol]['spot'].at[exit_time, 'open'])
        futures_exit_reference = float(data[symbol]['futures'].at[exit_time, 'open'])
        spot_exit_fill = spot_exit_reference * (1 - slip_spot)
        futures_exit_fill = futures_exit_reference * (1 + slip_futures)
        spot_exit_fee = quantity * spot_exit_fill * fee_spot
        futures_exit_fee = quantity * futures_exit_fill * fee_futures
        spot_pnl = quantity * (spot_exit_fill - spot_fill)
        futures_pnl = quantity * (futures_fill - futures_exit_fill)
        reference_basis_pnl = quantity * (
            (spot_exit_reference - spot_reference)
            + (futures_reference - futures_exit_reference))
        price_pnl = spot_pnl + futures_pnl
        fees = entry_spot_fee + entry_futures_fee + spot_exit_fee + futures_exit_fee
        slippage_cost = reference_basis_pnl - price_pnl
        net = price_pnl - fees
        realised += net
        global_min_futures_equity = min(
            global_min_futures_equity, episode_min_equity)
        global_max_futures_leverage = max(
            global_max_futures_leverage, episode_max_leverage)
        trades.append({
            **item, **selected, 'opened_at': entry_time,
            'closed_at': exit_time, 'reason': reason,
            'spot_entry_reference': spot_reference,
            'futures_entry_reference': futures_reference,
            'spot_exit_reference': spot_exit_reference,
            'futures_exit_reference': futures_exit_reference,
            'quantity': quantity,
            'entry_basis_bps': (futures_reference / spot_reference - 1) * 10_000,
            'exit_basis_bps': (
                futures_exit_reference / spot_exit_reference - 1) * 10_000,
            'reference_basis_pnl': reference_basis_pnl,
            'price_pnl_after_slippage': price_pnl,
            'fees': fees, 'slippage_cost': slippage_cost,
            'net_pnl': net,
            'min_futures_equity_usd': episode_min_equity,
            'max_futures_mark_leverage': episode_max_leverage,
        })
        equity_points.append(initial_capital + realised)

    pnls = np.asarray([trade['net_pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.asarray(equity_points, dtype=float)
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    per_symbol = {
        symbol: {
            'episodes': sum(trade['symbol'] == symbol for trade in trades),
            'net_pnl': float(sum(
                trade['net_pnl'] for trade in trades if trade['symbol'] == symbol)),
        }
        for symbol in data
    }
    return {
        'config': {**asdict(config),
                   'combined_round_trip_bps': config.costs.combined_round_trip_bps},
        'window': [str(start), str(end)],
        'schedule': schedule,
        'trades': trades,
        'summary': {
            'quarterly_decisions': len(schedule),
            'qualified_decisions': sum(item['selected'] is not None for item in schedule),
            'episodes': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else ('Infinity' if gains else None),
            'reference_basis_pnl': float(sum(
                trade['reference_basis_pnl'] for trade in trades)),
            'fees': float(sum(trade['fees'] for trade in trades)),
            'slippage_cost': float(sum(trade['slippage_cost'] for trade in trades)),
            'net_pnl': float(pnls.sum()) if len(pnls) else 0.0,
            'return_pct': float(pnls.sum()) / initial_capital * 100 if len(pnls) else 0.0,
            'max_drawdown_pct': float(drawdowns.max()),
            'min_futures_equity_usd': global_min_futures_equity,
            'max_futures_mark_leverage': global_max_futures_leverage,
            'collateral_exhaustions': int(global_min_futures_equity <= 0),
            'per_symbol': per_symbol,
        },
    }
