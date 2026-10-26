import pandas as pd

from backtest.perp_spot_basis_reversion import execute_basis_compression
from l1_filter.basis_compression import BasisCompressionConfig


def _flat(price):
    index = pd.date_range('2026-01-01', periods=60, freq='1min', tz='UTC')
    return pd.DataFrame({
        'open': price, 'high': price, 'low': price, 'close': price,
        'volume': 1.0, 'taker_buy_volume': 0.5,
    }, index=index)


def test_flat_basis_pair_uses_same_quantity_and_charges_both_legs_round_trip():
    spot, perp = _flat(100.0), _flat(102.0)
    empty_funding = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz='UTC'))
    signal = {
        'timestamp': spot.index[0], 'symbol': 'ETHUSDT',
        'basis': 0.02, 'median': 0.0, 'score': 20.0, 'setup_id': 'flat',
    }
    result = execute_basis_compression(
        {'ETHUSDT': spot}, {'ETHUSDT': (perp, empty_funding)},
        {'ETHUSDT': pd.DataFrame({'basis': []}, index=pd.DatetimeIndex([], tz='UTC'))},
        {'ETHUSDT': [signal]}, BasisCompressionConfig(),
        spot.index[0], spot.index[-1] + pd.Timedelta(minutes=1),
        costs={'spot_side': 10.0, 'perp_side': 10.0, 'leg_risk': 0.0},
    )
    trade = result['trades'][0]
    expected_quantity = 60.0 / 102.0
    expected_cost = 2 * 0.001 * expected_quantity * (100.0 + 102.0)
    assert abs(trade['quantity'] - expected_quantity) < 1e-12
    assert abs(trade['costs'] - expected_cost) < 1e-9
    assert abs(result['summary']['net_pnl'] + expected_cost) < 1e-9
