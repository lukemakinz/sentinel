from unittest.mock import Mock

import pandas as pd

from backtest.coin_dated_carry_data import _fetch_rows


def _kline(timestamp):
    return [int(pd.Timestamp(timestamp).timestamp() * 1000),
            '100', '102', '99', '101', '1', 0, '1', 1, '1', '1', '0']


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_coin_m_fetch_uses_inverse_pair_and_causal_forward_pages():
    session = Mock()
    session.get.side_effect = [
        _Response([_kline('2026-01-01 00:00Z'),
                   _kline('2026-01-01 01:00Z')]),
        _Response([_kline('2026-01-01 02:00Z')]),
    ]
    rows = _fetch_rows(
        'BTCUSD', pd.Timestamp('2026-01-01 00:00Z'),
        pd.Timestamp('2026-01-01 03:00Z'), session)
    assert len(rows) == 3
    params = session.get.call_args_list[0].kwargs['params']
    assert params['pair'] == 'BTCUSD'
    assert params['contractType'] == 'CURRENT_QUARTER'
    assert session.get.call_args_list[1].kwargs['params']['startTime'] > params['startTime']
