"""Causal two-venue funding-dispersion and basis-convergence replay."""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


VENUES = ('binance', 'bybit')


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class XFRDCosts:
    fee_bps: float = 2.0
    slippage_bps: float = 1.0

    @property
    def combined_round_trip_bps(self) -> float:
        return 4 * (self.fee_bps + self.slippage_bps)


@dataclass(frozen=True)
class XFRDConfig:
    name: str = 'S32_XFRD'
    collateral_each_venue_usd: float = 100.0
    reserve_usd: float = 50.0
    notional_each_leg_usd: float = 60.0
    ewma_observations: int = 9
    ewma_half_life: float = 3.0
    persistence_observations: int = 6
    persistence_required: int = 5
    entry_projected_7d_bps: float = 60.0
    exit_projected_7d_bps: float = 10.0
    basis_min_bps: float = 0.0
    basis_max_bps: float = 100.0
    adverse_basis_exit_bps: float = 150.0
    minimum_hold_hours: int = 72
    maximum_hold_hours: int = 336
    minimum_venue_equity_usd: float = 75.0
    maximum_mark_leverage: float = .80
    execution_delay_hours: int = 1
    max_execution_wait_hours: int = 24
    cooldown_observations: int = 2
    costs: XFRDCosts = XFRDCosts()

    def validate(self, initial_capital: float = 250.0):
        if (2 * self.collateral_each_venue_usd + self.reserve_usd
                > initial_capital):
            raise ValueError('Venue collateral plus reserve exceeds capital')
        if not 0 < self.notional_each_leg_usd <= self.collateral_each_venue_usd:
            raise ValueError('Invalid per-leg notional')
        if (self.ewma_observations < self.persistence_observations
                or self.persistence_required > self.persistence_observations):
            raise ValueError('Invalid funding persistence window')
        if (self.entry_projected_7d_bps <= self.exit_projected_7d_bps
                or self.minimum_hold_hours >= self.maximum_hold_hours):
            raise ValueError('Invalid entry/exit hysteresis')
        if self.basis_min_bps > self.basis_max_bps:
            raise ValueError('Invalid basis band')
        if not 0 < self.maximum_mark_leverage <= 1:
            raise ValueError('Invalid venue leverage gate')


def normalize_funding_hourly(rates: pd.Series) -> pd.DataFrame:
    """Normalize each settled rate by its causal, realized interval length."""
    if rates.empty:
        raise ValueError('Empty funding series')
    series = rates.astype(float).copy()
    series.index = pd.DatetimeIndex(series.index).floor('h')
    if series.index.has_duplicates:
        raise ValueError('Duplicate funding settlement hour')
    series = series.sort_index()
    hours = series.index.to_series().diff().dt.total_seconds().div(3600)
    valid = hours.between(1, 24)
    return pd.DataFrame({
        'rate': series,
        'interval_hours': hours,
        'hourly_rate': series / hours,
    }).loc[valid]


def paired_funding_features(binance: pd.Series, bybit: pd.Series,
                            config: XFRDConfig) -> pd.DataFrame:
    """Return features known immediately after each shared settlement."""
    left = normalize_funding_hourly(binance).add_prefix('binance_')
    right = normalize_funding_hourly(bybit).add_prefix('bybit_')
    paired = left.join(right, how='inner')
    paired['difference_hourly'] = (
        paired.binance_hourly_rate - paired.bybit_hourly_rate)
    paired['ewma_difference_hourly'] = paired.difference_hourly.ewm(
        halflife=config.ewma_half_life, adjust=False,
        min_periods=config.ewma_observations,
    ).mean()
    signs = np.sign(paired.difference_hourly)
    positive = (signs > 0).rolling(
        config.persistence_observations,
        min_periods=config.persistence_observations,
    ).sum()
    negative = (signs < 0).rolling(
        config.persistence_observations,
        min_periods=config.persistence_observations,
    ).sum()
    paired['positive_persistence'] = positive
    paired['negative_persistence'] = negative
    paired['projected_signed_7d_bps'] = (
        paired.ewma_difference_hourly * 168 * 10_000)
    return paired


def _validate_hourly(frame: pd.DataFrame, start, end, label: str):
    start, end = _utc(start), _utc(end)
    required = {'open', 'high', 'low', 'close'}
    if (not required.issubset(frame) or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing):
        raise ValueError(f'Invalid {label} hourly data')
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    if not expected.equals(frame.loc[(frame.index >= start) & (frame.index < end)].index):
        raise ValueError(f'Incomplete {label} hourly data')
    values = frame.loc[(frame.index >= start) & (frame.index < end), list(required)]
    if not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any().any():
        raise ValueError(f'Invalid {label} prices')


def _basis_at(data: dict, symbol: str, short_venue: str,
              long_venue: str, decision_time) -> tuple[float, pd.Timestamp]:
    cutoff = _utc(decision_time) - pd.Timedelta(hours=1)
    short = data[symbol][short_venue]['mark']
    long = data[symbol][long_venue]['mark']
    if cutoff not in short.index or cutoff not in long.index:
        raise ValueError(f'Missing completed mark bar at {cutoff}')
    short_mark = float(short.at[cutoff, 'close'])
    long_mark = float(long.at[cutoff, 'close'])
    return float(np.log(short_mark / long_mark) * 10_000), cutoff


def funding_candidate(data: dict, features: dict[str, pd.DataFrame],
                      symbol: str, timestamp, config: XFRDConfig):
    """Build one causal entry candidate or return None."""
    timestamp = _utc(timestamp)
    frame = features[symbol]
    if timestamp not in frame.index:
        return None
    row = frame.loc[timestamp]
    signed = float(row.projected_signed_7d_bps)
    if not np.isfinite(signed):
        return None
    if signed > 0:
        short_venue, long_venue = 'binance', 'bybit'
        persistence = float(row.positive_persistence)
    elif signed < 0:
        short_venue, long_venue = 'bybit', 'binance'
        persistence = float(row.negative_persistence)
    else:
        return None
    projected = abs(signed)
    if (persistence < config.persistence_required
            or projected < config.entry_projected_7d_bps):
        return None
    basis_bps, basis_cutoff = _basis_at(
        data, symbol, short_venue, long_venue, timestamp)
    if not config.basis_min_bps <= basis_bps <= config.basis_max_bps:
        return None
    return {
        'decision_time': timestamp,
        'planned_fill_time': timestamp + pd.Timedelta(
            hours=config.execution_delay_hours),
        'symbol': symbol,
        'short_venue': short_venue,
        'long_venue': long_venue,
        'projected_7d_bps': projected,
        'signed_binance_minus_bybit_7d_bps': signed,
        'persistence': int(persistence),
        'entry_basis_bps': basis_bps,
        'basis_feature_cutoff': basis_cutoff,
        'setup_id': (
            f'XFRD|{symbol}|{short_venue}|{long_venue}|{timestamp.isoformat()}'),
    }


def simulate_xfrd(data: dict, start, end, config: XFRDConfig,
                   initial_capital: float = 250.0) -> dict:
    """Replay a single global same-asset hedge with separate venue equity."""
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    warmup = start - pd.Timedelta(days=31)
    for symbol, venues in data.items():
        if set(venues) != set(VENUES):
            raise ValueError(f'Invalid venue set for {symbol}')
        for venue in VENUES:
            _validate_hourly(
                venues[venue]['trade'], start, end, f'{symbol} {venue} trade')
            _validate_hourly(
                venues[venue]['mark'], warmup, end, f'{symbol} {venue} mark')

    features = {
        symbol: paired_funding_features(
            venues['binance']['funding'], venues['bybit']['funding'], config)
        for symbol, venues in data.items()
    }
    all_events = sorted(set().union(*(
        set(frame.index[(frame.index >= start) & (frame.index < end)])
        for frame in features.values()
    )))
    events_by_time = {timestamp: [] for timestamp in all_events}
    for timestamp in all_events:
        for symbol in sorted(data):
            if timestamp in features[symbol].index:
                events_by_time[timestamp].append(symbol)

    fee = config.costs.fee_bps / 10_000
    slip = config.costs.slippage_bps / 10_000
    balances = {venue: config.collateral_each_venue_usd for venue in VENUES}
    position = pending_entry = pending_exit = None
    cooldown_remaining = 0
    trades, equity_curve, diagnostics = [], [], {
        'qualified_candidates': 0, 'entries': 0, 'risk_exits': 0,
        'normal_exits': 0, 'skipped_execution': 0,
    }
    used_setups = set()
    global_min_venue_equity = {venue: balances[venue] for venue in VENUES}
    global_max_venue_leverage = {venue: 0.0 for venue in VENUES}

    def common_real_open(symbol, requested):
        deadline = requested + pd.Timedelta(hours=config.max_execution_wait_hours)
        expected = pd.date_range(requested, min(deadline, end), freq='1h')
        for timestamp in expected:
            if all(timestamp in data[symbol][venue]['trade'].index for venue in VENUES):
                return timestamp
        return None

    def current_mark_equity(timestamp):
        if position is None:
            return balances.copy(), {venue: 0.0 for venue in VENUES}
        equities, leverages = {}, {}
        for venue in VENUES:
            mark = float(data[position['symbol']][venue]['mark'].at[timestamp, 'close'])
            side = position['sides'][venue]
            unrealised = side * position['quantity'] * (
                mark - position['entry_fills'][venue])
            equities[venue] = balances[venue] + unrealised
            leverages[venue] = (
                position['quantity'] * mark / equities[venue]
                if equities[venue] > 0 else float('inf'))
        return equities, leverages

    def open_position(candidate, timestamp):
        nonlocal position
        symbol = candidate['symbol']
        sides = {candidate['short_venue']: -1, candidate['long_venue']: 1}
        references = {
            venue: float(data[symbol][venue]['trade'].at[timestamp, 'open'])
            for venue in VENUES
        }
        fills = {
            venue: references[venue] * (1 + sides[venue] * slip)
            for venue in VENUES
        }
        quantity = config.notional_each_leg_usd / max(fills.values())
        entry_fees = {
            venue: quantity * fills[venue] * fee for venue in VENUES
        }
        cash_before = sum(balances.values())
        for venue in VENUES:
            balances[venue] -= entry_fees[venue]
        position = {
            **candidate, 'opened_at': timestamp, 'quantity': quantity,
            'sides': sides, 'entry_references': references,
            'entry_fills': fills, 'entry_fees': entry_fees,
            'cash_before': cash_before,
            'funding_pnl': {venue: 0.0 for venue in VENUES},
            'weak_updates': 0, 'reversed_updates': 0,
            'min_venue_equity': {venue: balances[venue] for venue in VENUES},
            'max_venue_leverage': {venue: 0.0 for venue in VENUES},
        }
        diagnostics['entries'] += 1

    def close_position(timestamp, reason):
        nonlocal position, cooldown_remaining
        symbol, quantity = position['symbol'], position['quantity']
        exit_references, exit_fills, exit_fees = {}, {}, {}
        gross_price_pnl, reference_price_pnl = {}, {}
        for venue in VENUES:
            side = position['sides'][venue]
            reference = float(data[symbol][venue]['trade'].at[timestamp, 'open'])
            fill = reference * (1 - side * slip)
            exit_fee = quantity * fill * fee
            gross = side * quantity * (fill - position['entry_fills'][venue])
            reference_gross = side * quantity * (
                reference - position['entry_references'][venue])
            balances[venue] += gross - exit_fee
            exit_references[venue], exit_fills[venue] = reference, fill
            exit_fees[venue], gross_price_pnl[venue] = exit_fee, gross
            reference_price_pnl[venue] = reference_gross
        fees = sum(position['entry_fees'].values()) + sum(exit_fees.values())
        slippage_cost = (
            sum(reference_price_pnl.values()) - sum(gross_price_pnl.values()))
        funding_pnl = sum(position['funding_pnl'].values())
        net = sum(balances.values()) - position['cash_before']
        trades.append({
            **position, 'closed_at': timestamp, 'reason': reason,
            'exit_references': exit_references, 'exit_fills': exit_fills,
            'exit_fees': exit_fees,
            'price_pnl_after_slippage': sum(gross_price_pnl.values()),
            'reference_basis_price_pnl': sum(reference_price_pnl.values()),
            'funding_pnl_total': funding_pnl, 'fees': fees,
            'slippage_cost': slippage_cost, 'net_pnl': net,
            'funding_minus_costs': funding_pnl - fees - slippage_cost,
        })
        diagnostics['risk_exits' if reason.startswith('RISK_') else 'normal_exits'] += 1
        position = None
        cooldown_remaining = config.cooldown_observations

    timeline = pd.date_range(start, end, freq='1h', inclusive='left')
    for timestamp in timeline:
        if pending_exit is not None and timestamp >= pending_exit['requested']:
            actual = common_real_open(position['symbol'], timestamp) if position else None
            if actual == timestamp:
                close_position(timestamp, pending_exit['reason'])
                pending_exit = None
                pending_entry = None
            elif actual is None:
                diagnostics['skipped_execution'] += 1
                pending_exit = None

        if (pending_entry is not None and position is None
                and timestamp >= pending_entry['planned_fill_time']):
            actual = common_real_open(pending_entry['symbol'], timestamp)
            if actual == timestamp:
                open_position(pending_entry, timestamp)
                used_setups.add(pending_entry['setup_id'])
                pending_entry = None
            elif actual is None:
                diagnostics['skipped_execution'] += 1
                pending_entry = None

        if position is not None and position['opened_at'] < timestamp:
            for venue in VENUES:
                rates = data[position['symbol']][venue]['funding']
                normalized_index = pd.DatetimeIndex(rates.index).floor('h')
                matches = np.flatnonzero(normalized_index == timestamp)
                if len(matches) > 1:
                    raise ValueError('Duplicate funding settlement after normalization')
                if len(matches) == 1:
                    rate = float(rates.iloc[matches[0]])
                    mark = float(data[position['symbol']][venue]['mark'].at[
                        timestamp, 'open'])
                    payment = (-position['sides'][venue]
                               * position['quantity'] * mark * rate)
                    balances[venue] += payment
                    position['funding_pnl'][venue] += payment

        if timestamp in events_by_time:
            if cooldown_remaining > 0 and position is None:
                cooldown_remaining -= 1
            if position is not None and timestamp in features[position['symbol']].index:
                row = features[position['symbol']].loc[timestamp]
                raw = float(row.projected_signed_7d_bps)
                oriented = raw if position['short_venue'] == 'binance' else -raw
                position['weak_updates'] = (
                    position['weak_updates'] + 1
                    if oriented <= config.exit_projected_7d_bps else 0)
                position['reversed_updates'] = (
                    position['reversed_updates'] + 1 if oriented <= 0 else 0)
                held = (timestamp - position['opened_at']).total_seconds() / 3600
                if (pending_exit is None and held >= config.minimum_hold_hours
                        and position['weak_updates'] >= 2):
                    pending_exit = {
                        'requested': timestamp + pd.Timedelta(hours=1),
                        'reason': 'FUNDING_EDGE_FADED',
                    }
                elif (pending_exit is None and held >= config.minimum_hold_hours
                      and position['reversed_updates'] >= 2):
                    pending_exit = {
                        'requested': timestamp + pd.Timedelta(hours=1),
                        'reason': 'FUNDING_ORIENTATION_REVERSED',
                    }

            if position is None and pending_entry is None and cooldown_remaining == 0:
                candidates = []
                for symbol in events_by_time[timestamp]:
                    candidate = funding_candidate(
                        data, features, symbol, timestamp, config)
                    if candidate is not None and candidate['setup_id'] not in used_setups:
                        candidates.append(candidate)
                diagnostics['qualified_candidates'] += len(candidates)
                if candidates:
                    candidates.sort(key=lambda row: (
                        -row['projected_7d_bps'], row['symbol']))
                    pending_entry = candidates[0]

        if position is not None:
            cutoff = timestamp - pd.Timedelta(hours=1)
            if cutoff >= position['opened_at'] and all(
                    cutoff in data[position['symbol']][venue]['mark'].index
                    for venue in VENUES):
                equities, leverages = current_mark_equity(cutoff)
                for venue in VENUES:
                    position['min_venue_equity'][venue] = min(
                        position['min_venue_equity'][venue], equities[venue])
                    position['max_venue_leverage'][venue] = max(
                        position['max_venue_leverage'][venue], leverages[venue])
                    global_min_venue_equity[venue] = min(
                        global_min_venue_equity[venue], equities[venue])
                    global_max_venue_leverage[venue] = max(
                        global_max_venue_leverage[venue], leverages[venue])
                short_mark = float(data[position['symbol']][position['short_venue']][
                    'mark'].at[cutoff, 'close'])
                long_mark = float(data[position['symbol']][position['long_venue']][
                    'mark'].at[cutoff, 'close'])
                basis = float(np.log(short_mark / long_mark) * 10_000)
                reason = None
                if basis - position['entry_basis_bps'] >= config.adverse_basis_exit_bps:
                    reason = 'RISK_ADVERSE_BASIS'
                elif min(equities.values()) < config.minimum_venue_equity_usd:
                    reason = 'RISK_VENUE_EQUITY'
                elif max(leverages.values()) > config.maximum_mark_leverage:
                    reason = 'RISK_MARK_LEVERAGE'
                if reason is not None and pending_exit is None:
                    pending_exit = {
                        'requested': timestamp + pd.Timedelta(hours=1),
                        'reason': reason,
                    }
            held = (timestamp - position['opened_at']).total_seconds() / 3600
            if held >= config.maximum_hold_hours and pending_exit is None:
                pending_exit = {
                    'requested': timestamp + pd.Timedelta(hours=1),
                    'reason': 'MAX_HOLD_14D',
                }

        portfolio_equity = config.reserve_usd + sum(balances.values())
        if position is not None:
            cutoff = timestamp - pd.Timedelta(hours=1)
            if cutoff >= position['opened_at']:
                equities, _leverages = current_mark_equity(cutoff)
                portfolio_equity = config.reserve_usd + sum(equities.values())
        equity_curve.append(portfolio_equity)

    if position is not None:
        common = set(data[position['symbol']]['binance']['trade'].index)
        common &= set(data[position['symbol']]['bybit']['trade'].index)
        eligible = sorted(timestamp for timestamp in common if timestamp < end)
        close_position(eligible[-1], 'END_OF_WINDOW')

    pnls = np.asarray([trade['net_pnl'] for trade in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.r_[initial_capital, np.asarray(equity_curve, dtype=float),
                   config.reserve_usd + sum(balances.values())]
    peaks = np.maximum.accumulate(values)
    drawdown = (1 - values / peaks) * 100
    symbol_net = {
        symbol: float(sum(t['net_pnl'] for t in trades if t['symbol'] == symbol))
        for symbol in data
    }
    total_positive = sum(max(value, 0) for value in symbol_net.values())
    return {
        'config': {**asdict(config),
                   'combined_round_trip_bps': config.costs.combined_round_trip_bps},
        'window': [str(start), str(end)],
        'summary': {
            'episodes': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': (
                gains / losses if losses else ('Infinity' if gains else None)),
            'net_pnl': float(pnls.sum()) if len(pnls) else 0.0,
            'return_pct': float(pnls.sum()) / initial_capital * 100 if len(pnls) else 0.0,
            'funding_pnl': float(sum(t['funding_pnl_total'] for t in trades)),
            'reference_basis_price_pnl': float(sum(
                t['reference_basis_price_pnl'] for t in trades)),
            'fees': float(sum(t['fees'] for t in trades)),
            'slippage_cost': float(sum(t['slippage_cost'] for t in trades)),
            'funding_minus_costs': float(sum(
                t['funding_minus_costs'] for t in trades)),
            'max_drawdown_pct': float(drawdown.max()),
            'min_venue_equity': global_min_venue_equity,
            'max_venue_mark_leverage': global_max_venue_leverage,
            'collateral_exhaustions': int(any(
                value <= 0 for value in global_min_venue_equity.values())),
            'symbol_net_pnl': symbol_net,
            'largest_positive_symbol_share_pct': (
                max((max(value, 0) for value in symbol_net.values()), default=0)
                / total_positive * 100 if total_positive else None),
            'diagnostics': diagnostics,
        },
        'trades': trades,
    }
