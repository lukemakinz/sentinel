import pandas as pd

from backtest.trend_carry_portfolio import (
    TrendPortfolioCosts,
    simulate_trend_portfolio,
)


def _frame(opens, closes=None):
    closes = opens if closes is None else closes
    index = pd.date_range('2025-01-06', periods=len(opens), freq='1D', tz='UTC')
    return pd.DataFrame({
        'open': opens,
        'high': [max(a, b) for a, b in zip(opens, closes)],
        'low': [min(a, b) for a, b in zip(opens, closes)],
        'close': closes,
    }, index=index)


def _market(frame, rates=None):
    return {'BTC': (frame, rates if rates is not None else pd.Series(dtype=float))}


def _target(timestamp, weight):
    return {'timestamp': timestamp, 'weights': {'BTC': weight}}


def test_quantity_is_held_between_rebalances_and_price_drift_is_real_pnl():
    frame = _frame([100.0, 100.0], [100.0, 110.0])
    start, end = frame.index[0], frame.index[-1] + pd.Timedelta(days=1)
    result = simulate_trend_portfolio(
        _market(frame), [_target(start, 0.5)], start, end, 500.0,
        TrendPortfolioCosts(0.0, 0.0))
    assert result['summary']['rebalances'] == 1
    assert result['summary']['net_pnl'] == 25.0


def test_turnover_costs_only_quantity_delta_plus_final_liquidation():
    frame = _frame([100.0, 100.0])
    start, end = frame.index[0], frame.index[-1] + pd.Timedelta(days=1)
    result = simulate_trend_portfolio(
        _market(frame), [_target(start, 0.4), _target(frame.index[1], 0.6)],
        start, end, 500.0, TrendPortfolioCosts(100.0, 0.0))
    assert abs(result['summary']['turnover_usd'] - 597.6) < 1e-9
    assert abs(result['summary']['fees'] - 5.976) < 1e-9
    assert abs(result['summary']['final_equity'] - 494.024) < 1e-9


def test_positive_funding_is_paid_by_long_and_received_by_short():
    frame = _frame([100.0])
    start, end = frame.index[0], frame.index[0] + pd.Timedelta(days=1)
    rates = pd.Series([0.001], index=pd.DatetimeIndex([start + pd.Timedelta(hours=8)]))
    long = simulate_trend_portfolio(
        _market(frame, rates), [_target(start, 0.5)], start, end, 500.0,
        TrendPortfolioCosts(0.0, 0.0))
    short = simulate_trend_portfolio(
        _market(frame, rates), [_target(start, -0.5)], start, end, 500.0,
        TrendPortfolioCosts(0.0, 0.0))
    assert abs(long['summary']['funding_pnl'] + 0.25) < 1e-12
    assert abs(short['summary']['funding_pnl'] - 0.25) < 1e-12
