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
