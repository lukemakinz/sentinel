from unittest.mock import patch

import pandas as pd

from backtest.book_a_portfolio_sim import simulate_book_a
from l1_filter.book_a_risk_overlay import BookARiskOverlayConfig
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig


def test_risk_scaling_preserves_cash_instead_of_renormalizing_to_full_gross():
    index = pd.date_range('2026-01-05', periods=2, freq='1D', tz='UTC')
    panel = pd.DataFrame({
        'BTCUSDT': [100.0, 100.0],
        'ETHUSDT': [100.0, 110.0],
        'SOLUSDT': [100.0, 110.0],
    }, index=index)
    config = BookASmallTsmomConfig(
        min_position_usd=0.01,
        taker_fee_bps=0.0,
        include_btc_in_universe=False,
    )

    with patch(
        'backtest.book_a_portfolio_sim.build_daily_panel', return_value=panel,
    ), patch(
        'backtest.book_a_portfolio_sim.target_weights_for_day',
        return_value={'ETHUSDT': 0.4, 'SOLUSDT': 0.2},
    ), patch(
        'backtest.book_a_portfolio_sim.compute_risk_indicators',
        return_value={'valid': 1.0},
    ), patch(
        'backtest.book_a_portfolio_sim.exposure_multiplier', return_value=0.5,
    ):
        result = simulate_book_a(
            {}, config, index[0], index[-1] + pd.Timedelta(days=1),
            initial_capital=250.0,
            risk=BookARiskOverlayConfig(),
        )

    # Base gross 0.60 scaled by 0.50 leaves 0.30 invested and 0.70 cash.
    # A 10% move therefore earns 3%, not the 10% produced by the old
    # accidental re-normalisation to full gross.
    assert result.summary['final_equity'] == 257.5
    assert result.summary['net_pnl'] == 7.5


def test_weekly_holdings_drift_and_rebalance_turnover_uses_actual_notional():
    index = pd.date_range('2026-01-05', periods=8, freq='1D', tz='UTC')
    panel = pd.DataFrame({
        'BTCUSDT': [100.0] * 8,
        'ETHUSDT': [100.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0],
        'SOLUSDT': [100.0] * 8,
    }, index=index)
    config = BookASmallTsmomConfig(
        min_position_usd=0.01,
        taker_fee_bps=100.0,
        include_btc_in_universe=False,
    )

    with patch(
        'backtest.book_a_portfolio_sim.build_daily_panel', return_value=panel,
    ), patch(
        'backtest.book_a_portfolio_sim.target_weights_for_day',
        return_value={'ETHUSDT': 0.4, 'SOLUSDT': 0.4},
    ):
        result = simulate_book_a(
            {}, config, index[0], index[-1] + pd.Timedelta(days=1),
            initial_capital=100.0,
        )

    # First Monday buys $80 gross and pays $0.80.  ETH then doubles while the
    # unit quantities remain unchanged, so NAV is $139.20 before the second
    # Monday rebalance.  Restoring 40/40 targets trades $40 and costs $0.40.
    assert result.summary['rebalances'] == 2
    assert abs(result.summary['fees_paid'] - 1.2) < 1e-9
    assert abs(result.summary['final_equity'] - 138.8) < 1e-9


def _flat_run(eth=(100.0, 100.0, 100.0), **kwargs):
    index = pd.date_range('2026-01-05', periods=3, freq='1D', tz='UTC')
    panel = pd.DataFrame({'BTCUSDT': [100.0] * 3, 'ETHUSDT': list(eth),
                          'SOLUSDT': [100.0] * 3}, index=index)
    config = BookASmallTsmomConfig(min_position_usd=0.01, taker_fee_bps=0.0,
                                   include_btc_in_universe=False)
    with patch('backtest.book_a_portfolio_sim.build_daily_panel', return_value=panel), \
            patch('backtest.book_a_portfolio_sim.target_weights_for_day',
                  return_value={'ETHUSDT': 0.5}):
        return index, simulate_book_a({}, config, index[0], index[-1] + pd.Timedelta(days=1),
                                      initial_capital=100.0, **kwargs)


def test_long_holdings_pay_funding_settled_inside_each_day():
    index, _ = _flat_run()
    rates = pd.Series([0.001, 0.001, 0.001],
                      index=[index[1] - pd.Timedelta(hours=8), index[1], index[2]])
    _, result = _flat_run(funding={'ETHUSDT': rates}, funding_multiplier=2.0)

    # $50 of ETH held after the first rebalance; three settlements at 0.1% x2.
    assert abs(result.summary['funding_paid'] - 0.30) < 1e-9
    assert abs(result.summary['final_equity'] - 99.70) < 1e-9


def test_quantities_round_to_contract_steps_and_tiny_targets_vanish():
    rising = (100.0, 110.0, 110.0)
    _, exact = _flat_run(eth=rising)
    _, rounded = _flat_run(eth=rising, quantity_steps={'ETHUSDT': 0.3})
    _, vanished = _flat_run(eth=rising, quantity_steps={'ETHUSDT': 2.0})

    # Target 0.5 ETH: exact earns $5, 0.6 ETH (2 x 0.3) earns $6, step 2.0 -> 0 ETH.
    assert abs(exact.summary['net_pnl'] - 5.0) < 1e-9
    assert abs(rounded.summary['net_pnl'] - 6.0) < 1e-9
    assert abs(vanished.summary['net_pnl']) < 1e-9
