"""Causal, delta-neutral funding-carry research helpers.

The model represents a long spot / short USD-M perpetual hedge with equal
quantity.  Perpetual minute prices are used as a spot/mark proxy, so price PnL
cancels by construction.  The caller must disclose the absent spot basis,
transfer and operational risks; this is a research model, not a live adapter.
"""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class FundingCarryCosts:
    spot_fee_bps: float = 10.0
    futures_fee_bps: float = 2.0
    spot_slippage_bps: float = 1.0
    futures_slippage_bps: float = 1.0

    @property
    def one_way_rate(self) -> float:
        return (
            self.spot_fee_bps + self.futures_fee_bps
            + self.spot_slippage_bps + self.futures_slippage_bps
        ) / 10_000

    @property
    def round_trip_bps(self) -> float:
        return 2 * self.one_way_rate * 10_000


@dataclass(frozen=True)
class FundingCarryConfig:
    name: str = 'S11_monthly_funding_carry'
    notional_usd: float = 100.0
    futures_margin_usd: float = 100.0
    entry_score_bps: float = 10.0
    exit_score_bps: float = 0.0
    switch_hurdle_bps: float = 28.0
    decision_delay_minutes: int = 1
    costs: FundingCarryCosts = FundingCarryCosts()

    def validate(self, capital: float) -> None:
        if self.notional_usd <= 0 or self.futures_margin_usd <= 0:
            raise ValueError('Notional and margin must be positive')
        # Long spot and isolated futures collateral are separately funded.
        if self.notional_usd + self.futures_margin_usd > capital:
            raise ValueError('Carry allocation exceeds portfolio capital')
        if self.notional_usd / self.futures_margin_usd > 1:
            raise ValueError('Research protocol caps the futures leg at 1x')
        if self.switch_hurdle_bps < self.costs.round_trip_bps:
            raise ValueError('Switch hurdle must cover a full base round trip')


def previous_month_scores(rates: dict[str, pd.Series], decision_time) -> dict[str, float]:
    """Return funding sums in bps using only the completed calendar month."""
    decision = _utc(decision_time)
    current_month = decision.tz_localize(None).to_period('M')
    start = (current_month - 1).start_time.tz_localize('UTC')
    end = current_month.start_time.tz_localize('UTC')
    return {
        symbol: float(series.loc[(series.index >= start) & (series.index < end)].sum() * 10_000)
        for symbol, series in rates.items()
    }


def decide_target(current: str | None, scores: dict[str, float],
                  config: FundingCarryConfig) -> tuple[str | None, str]:
    """One S11 decision step: given the currently-held symbol (or None) and
    the previous-month funding scores, return (target, reason). Pure and
    side-effect free so the live carry monitor can reuse the exact same rule
    as this backtest, not a hand-copied reimplementation of it."""
    if not scores:
        raise ValueError('At least one symbol is required')
    leader = max(scores, key=lambda symbol: (scores[symbol], symbol))
    leader_score = scores[leader]

    if current is None:
        if leader_score >= config.entry_score_bps:
            return leader, 'enter_leader'
        return None, 'hold_cash'

    current_score = scores[current]
    if current_score <= config.exit_score_bps:
        if leader_score >= config.entry_score_bps:
            return leader, 'replace_nonpositive'
        return None, 'exit_nonpositive'
    if (leader != current
            and leader_score >= config.entry_score_bps
            and leader_score - current_score >= config.switch_hurdle_bps):
        return leader, 'switch_after_cost_hurdle'
    return current, 'hold_position'


def monthly_targets(rates: dict[str, pd.Series], start, end,
                    config: FundingCarryConfig) -> list[dict]:
    """Build a causal monthly target schedule with entry/exit hysteresis."""
    start, end = _utc(start), _utc(end)
    if start != start.normalize() or start.day != 1:
        raise ValueError('Funding carry windows must start at a UTC month boundary')
    decisions = pd.date_range(start, end, freq='MS', inclusive='left')
    current = None
    schedule = []
    for decision in decisions:
        scores = previous_month_scores(rates, decision)
        target, reason = decide_target(current, scores, config)
        schedule.append({
            'decision_time': decision,
            'target': target,
            'previous_month_scores_bps': scores,
            'reason': reason,
        })
        current = target
    return schedule


def _price_at(frame: pd.DataFrame, timestamp: pd.Timestamp, column='open') -> float:
    try:
        value = float(frame.at[timestamp, column])
    except KeyError as exc:
        raise ValueError(f'Missing price at {timestamp}') from exc
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f'Invalid price at {timestamp}')
    return value


def simulate_monthly_carry(prices: dict[str, pd.DataFrame], rates: dict[str, pd.Series],
                           start, end, config: FundingCarryConfig,
                           initial_capital=250.0) -> dict:
    """Replay one equal-quantity spot/perpetual hedge at a time."""
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    schedule = monthly_targets(rates, start, end, config)
    delay = pd.Timedelta(minutes=config.decision_delay_minutes)
    cashflows, episodes = [], []
    position = None

    def add_cashflow(timestamp, amount, kind, symbol):
        cashflows.append({
            'timestamp': timestamp, 'amount': float(amount),
            'kind': kind, 'symbol': symbol,
        })

    def close_position(timestamp):
        nonlocal position
        if position is None:
            return
        symbol = position['symbol']
        frame = prices[symbol]
        exit_price = _price_at(frame, timestamp)
        exit_notional = position['quantity'] * exit_price
        exit_cost = exit_notional * config.costs.one_way_rate
        add_cashflow(timestamp, -exit_cost, 'exit_cost', symbol)
        settlements = rates[symbol].loc[
            (rates[symbol].index > position['opened_at'])
            & (rates[symbol].index < timestamp)
        ]
        funding_pnl = 0.0
        for funding_time, rate in settlements.items():
            mark = _price_at(frame, funding_time)
            payment = position['quantity'] * mark * float(rate)
            funding_pnl += payment
            add_cashflow(funding_time, payment, 'funding', symbol)
        episode_slice = frame.loc[
            (frame.index >= position['opened_at']) & (frame.index <= timestamp)
        ]
        max_price = float(episode_slice.high.max())
        pnl = funding_pnl - position['entry_cost'] - exit_cost
        episodes.append({
            **position,
            'closed_at': timestamp,
            'exit_price': exit_price,
            'exit_notional': exit_notional,
            'exit_cost': exit_cost,
            'funding_pnl': funding_pnl,
            'pnl': pnl,
            'funding_settlements': int(len(settlements)),
            'max_short_adverse_move_pct': (max_price / position['entry_price'] - 1) * 100,
        })
        position = None

    def open_position(symbol, timestamp):
        nonlocal position
        entry_price = _price_at(prices[symbol], timestamp)
        quantity = config.notional_usd / entry_price
        entry_cost = config.notional_usd * config.costs.one_way_rate
        add_cashflow(timestamp, -entry_cost, 'entry_cost', symbol)
        position = {
            'symbol': symbol,
            'opened_at': timestamp,
            'entry_price': entry_price,
            'entry_notional': config.notional_usd,
            'quantity': quantity,
            'entry_cost': entry_cost,
        }

    for item in schedule:
        action_time = item['decision_time'] + delay
        target = item['target']
        current = position['symbol'] if position else None
        if target != current:
            close_position(action_time)
            if target is not None:
                open_position(target, action_time)
    if position is not None:
        final_frame = prices[position['symbol']]
        # Archive windows are [start, end), so the exact boundary may be
        # absent.  In that case liquidate on the last observed minute without
        # inventing a price or downloading the following month.
        final_time = end if end in final_frame.index else final_frame.index[final_frame.index < end][-1]
        close_position(final_time)

    cashflows.sort(key=lambda row: (row['timestamp'], row['kind']))
    amounts = np.array([row['amount'] for row in cashflows], dtype=float)
    equity = initial_capital + np.r_[0.0, np.cumsum(amounts)]
    peaks = np.maximum.accumulate(equity)
    drawdowns = (1 - equity / peaks) * 100
    episode_pnls = np.array([episode['pnl'] for episode in episodes], dtype=float)
    gains = float(episode_pnls[episode_pnls > 0].sum()) if len(episode_pnls) else 0.0
    losses = float(-episode_pnls[episode_pnls < 0].sum()) if len(episode_pnls) else 0.0
    monthly = {}
    for row in cashflows:
        key = str(row['timestamp'].tz_localize(None).to_period('M'))
        monthly[key] = monthly.get(key, 0.0) + row['amount']

    serializable_schedule = [{
        **item,
        'decision_time': str(item['decision_time']),
    } for item in schedule]
    return {
        'config': {**asdict(config), 'round_trip_bps': config.costs.round_trip_bps},
        'window': [str(start), str(end)],
        'schedule': serializable_schedule,
        'episodes': episodes,
        'cashflows': cashflows,
        'monthly_pnl': monthly,
        'summary': {
            'episodes': len(episodes),
            'winning_episodes': int((episode_pnls > 0).sum()),
            'funding_settlements': int(sum(x['funding_settlements'] for x in episodes)),
            'gross_funding_pnl': float(sum(x['funding_pnl'] for x in episodes)),
            'costs': float(sum(x['entry_cost'] + x['exit_cost'] for x in episodes)),
            'net_pnl': float(amounts.sum()) if len(amounts) else 0.0,
            'return_pct': float(amounts.sum() / initial_capital * 100) if len(amounts) else 0.0,
            'episode_profit_factor': gains / losses if losses else None,
            'max_cashflow_drawdown_pct': float(drawdowns.max()),
            'max_short_adverse_move_pct': max(
                (x['max_short_adverse_move_pct'] for x in episodes), default=0.0),
        },
    }
