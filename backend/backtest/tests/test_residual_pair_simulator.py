import pandas as pd

from backtest.residual_pair_simulator import execute_residual_pairs
from l1_filter.asymmetric_residual_reversal import AsymmetricResidualConfig


def _flat(price):
    index = pd.date_range('2026-01-01', periods=60, freq='1min', tz='UTC')
    return pd.DataFrame({
        'open': price, 'high': price, 'low': price, 'close': price,
        'volume': 1.0, 'taker_buy_volume': 0.5,
    }, index=index)


def test_flat_pair_books_entry_and_exit_fee_on_both_legs():
    alt, btc = _flat(50.0), _flat(100.0)
    empty_funding = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz='UTC'))
    signal = {
        'timestamp': alt.index[0], 'symbol': 'ETHUSDT', 'beta': 1.0,
        'z': -3.5, 'score': 3.5, 'setup_id': 'flat',
    }
    result = execute_residual_pairs(
        {'BTCUSDT': (btc, empty_funding), 'ETHUSDT': (alt, empty_funding)},
        {'ETHUSDT': pd.DataFrame({'z': []}, index=pd.DatetimeIndex([], tz='UTC'))},
        {'ETHUSDT': [signal]}, AsymmetricResidualConfig(),
        alt.index[0], alt.index[-1] + pd.Timedelta(minutes=1),
        fee_bps=10.0, slippage_bps=0.0,
    )
    assert result['summary']['trades'] == 1
    assert abs(result['summary']['fees'] - 0.24) < 1e-9
    assert abs(result['summary']['net_pnl'] + 0.24) < 1e-9
