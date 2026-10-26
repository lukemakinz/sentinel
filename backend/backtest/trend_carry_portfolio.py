"""One-ledger daily futures replay for S97 slow trend targets."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


@dataclass(frozen=True)
class TrendPortfolioCosts:
    fee_bps: float = 5.0
    slippage_bps: float = 2.0

    def validate(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError('Costs cannot be negative')


def simulate_trend_portfolio(
    markets: dict[str, tuple[pd.DataFrame, pd.Series]],
    targets: list[dict],
    start,
    end,
    initial_capital: float = 500.0,
    costs: TrendPortfolioCosts = TrendPortfolioCosts(),
) -> dict:
    """Replay signed futures quantities with variation-margin accounting.

    Funding is exact by settlement rate and uses that UTC day's close as a
    conservative daily-bar mark proxy.  Fees and slippage apply only to the
    actual quantity delta at a rebalance, never to unchanged holdings.
    """
    costs.validate()
    start, end = _utc(start), _utc(end)
    if initial_capital <= 0 or end <= start:
        raise ValueError('Invalid capital or window')
    symbols = tuple(markets)
    frames, funding, common_index = {}, {}, None
    for symbol, (frame, rates) in markets.items():
        selected = frame.loc[(frame.index >= start) & (frame.index < end)].copy()
        required = {'open', 'high', 'low', 'close'}
        if not required.issubset(selected):
            raise ValueError('Daily data lacks OHLC')
        if selected.empty or selected.index.has_duplicates or not selected.index.is_monotonic_increasing:
            raise ValueError('Daily data must be non-empty, sorted and unique')
        if not (selected.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all():
            raise ValueError('Daily execution data must be continuous')
        if selected.index[0] != start or selected.index[-1] + pd.Timedelta(days=1) != end:
            raise ValueError(f'Incomplete execution period for {symbol}')
        values = selected[list(required)].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('Invalid OHLC values')
        if common_index is None:
            common_index = selected.index
        elif not common_index.equals(selected.index):
            raise ValueError('Execution indices are not aligned')
        if rates.index.has_duplicates or not np.isfinite(rates.to_numpy(dtype=float)).all():
            raise ValueError('Invalid funding series')
        frames[symbol] = selected
        if rates.empty:
            funding[symbol] = pd.Series(
                dtype=float, index=pd.DatetimeIndex([], tz='UTC'))
        else:
            if not isinstance(rates.index, pd.DatetimeIndex):
                raise ValueError('Funding requires a DatetimeIndex')
            funding[symbol] = rates.loc[(rates.index >= start) & (rates.index < end)]

    target_map = {}
    for target in targets:
        timestamp = _utc(target['timestamp'])
        if not start <= timestamp < end:
            continue
        if timestamp in target_map:
            raise ValueError('Duplicate target timestamp')
        weights = target['weights']
        if not set(weights).issubset(symbols):
            raise ValueError('Target references an unavailable symbol')
        if not np.isfinite(np.array(list(weights.values()), dtype=float)).all():
            raise ValueError('Invalid target weights')
        if sum(abs(weight) for weight in weights.values()) > 1 + 1e-12:
            raise ValueError('Target exceeds 1x gross exposure')
        target_map[timestamp] = target

    fee = costs.fee_bps / 10_000
    slip = costs.slippage_bps / 10_000
    cash = float(initial_capital)
    quantities = {symbol: 0.0 for symbol in symbols}
    previous_close = None
    daily_pnl, equity_points, rebalance_log = {}, {}, []
    fees_paid = slippage_paid = funding_pnl = turnover = 0.0
    previous_equity = cash

    for timestamp in common_index:
        rows = {symbol: frames[symbol].loc[timestamp] for symbol in symbols}
        if previous_close is not None:
            for symbol in symbols:
                cash += quantities[symbol] * (float(rows[symbol].open) - previous_close[symbol])

        if timestamp in target_map:
            target = target_map[timestamp]
            equity_before = cash
            target_quantities = {
                symbol: target['weights'].get(symbol, 0.0) * equity_before / float(rows[symbol].open)
                for symbol in symbols
            }
            event_turnover = event_fee = event_slippage = 0.0
            for symbol in symbols:
                delta = target_quantities[symbol] - quantities[symbol]
                notional = abs(delta) * float(rows[symbol].open)
                event_turnover += notional
                event_fee += notional * fee
                event_slippage += notional * slip
            cash -= event_fee + event_slippage
            quantities = target_quantities
            turnover += event_turnover
            fees_paid += event_fee
            slippage_paid += event_slippage
            rebalance_log.append({
                'timestamp': str(timestamp),
                'equity_before_costs': equity_before,
                'turnover': event_turnover,
                'fees': event_fee,
                'slippage': event_slippage,
                'weights': target['weights'],
            })

        for symbol in symbols:
            day_rates = funding[symbol].loc[
                (funding[symbol].index >= timestamp)
                & (funding[symbol].index < timestamp + pd.Timedelta(days=1))
            ]
            if not day_rates.empty and quantities[symbol] != 0:
                payment = -quantities[symbol] * float(rows[symbol].close) * float(day_rates.sum())
                cash += payment
                funding_pnl += payment
            cash += quantities[symbol] * (float(rows[symbol].close) - float(rows[symbol].open))

        equity_points[timestamp] = cash
        daily_pnl[timestamp] = cash - previous_equity
        previous_equity = cash
        previous_close = {symbol: float(rows[symbol].close) for symbol in symbols}

    # Realistic end-of-study liquidation at the final observed close.
    liquidation_turnover = sum(
        abs(quantities[symbol]) * previous_close[symbol] for symbol in symbols
    )
    liquidation_fee = liquidation_turnover * fee
    liquidation_slippage = liquidation_turnover * slip
    cash -= liquidation_fee + liquidation_slippage
    turnover += liquidation_turnover
    fees_paid += liquidation_fee
    slippage_paid += liquidation_slippage
    last_timestamp = common_index[-1]
    daily_pnl[last_timestamp] += cash - equity_points[last_timestamp]
    equity_points[last_timestamp] = cash

    daily = pd.Series(daily_pnl, dtype=float).sort_index()
    equity = pd.Series(equity_points, dtype=float).sort_index()
    peak = pd.concat([
        pd.Series([initial_capital], index=[equity.index[0] - pd.Timedelta(days=1)]),
        equity,
    ]).cummax().iloc[1:]
    drawdown = 1 - equity / peak
    returns = daily / (initial_capital + daily.cumsum().shift(1).fillna(0.0))
    return {
        'summary': {
            'initial_capital': initial_capital,
            'final_equity': float(cash),
            'net_pnl': float(cash - initial_capital),
            'return_pct': float((cash / initial_capital - 1) * 100),
            'max_drawdown_pct': float(drawdown.max() * 100),
            'annualized_sharpe': (
                float(returns.mean() / returns.std(ddof=1) * np.sqrt(365))
                if returns.std(ddof=1) > 0 else 0.0
            ),
            'rebalances': len(rebalance_log),
            'turnover_usd': float(turnover),
            'fees': float(fees_paid),
            'slippage': float(slippage_paid),
            'funding_pnl': float(funding_pnl),
        },
        'daily_pnl': daily,
        'equity_curve': equity,
        'rebalances': rebalance_log,
    }
