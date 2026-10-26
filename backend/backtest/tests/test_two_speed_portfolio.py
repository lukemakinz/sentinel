import pandas as pd

from backtest.two_speed_portfolio import merge_sleeve_daily, short_only_targets


def test_short_only_targets_keeps_flat_records_and_does_not_mutate_parent():
    targets = [
        {
            'timestamp': '2026-01-05',
            'weights': {'ETHUSDT': 0.4, 'BTCUSDT': 0.2},
            'gross_weight': 0.6,
            'selected': {'ETHUSDT': {'score': 2}, 'BTCUSDT': {'score': 1}},
            'regime': 'UP',
        },
        {
            'timestamp': '2026-01-12',
            'weights': {'ETHUSDT': -0.3},
            'gross_weight': 0.3,
            'selected': {'ETHUSDT': {'score': 3}},
            'regime': 'DOWN',
        },
    ]

    result = short_only_targets(targets)

    assert len(result) == 2
    assert result[0]['weights'] == {}
    assert result[0]['gross_weight'] == 0.0
    assert result[0]['selected'] == {}
    assert result[0]['flat_reason'] == 'SHORT_ONLY_FILTER'
    assert result[1]['weights'] == {'ETHUSDT': -0.3}
    assert result[1]['gross_weight'] == 0.3
    assert targets[0]['weights'] == {'ETHUSDT': 0.4, 'BTCUSDT': 0.2}
    result[1]['selected']['ETHUSDT']['score'] = 99
    assert targets[1]['selected']['ETHUSDT']['score'] == 3


def test_merge_sleeve_daily_normalizes_dates_and_fills_missing_days():
    a = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(['2026-01-01', '2026-01-02'], utc=True),
    )
    b = pd.Series(
        [3.0, 4.0],
        index=pd.to_datetime(['2026-01-02 12:00', '2026-01-03 12:00'], utc=True),
    )

    result = merge_sleeve_daily(a, b)

    assert result.to_dict() == {
        pd.Timestamp('2026-01-01', tz='UTC'): 1.0,
        pd.Timestamp('2026-01-02', tz='UTC'): 5.0,
        pd.Timestamp('2026-01-03', tz='UTC'): 4.0,
    }
