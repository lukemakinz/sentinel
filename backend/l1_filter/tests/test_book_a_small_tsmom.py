import pandas as pd

from l1_filter.book_a_small_tsmom import (
    BookASmallTsmomConfig,
    build_daily_panel,
    target_weights_for_day,
)


def _fake_minutes(prices):
    idx = pd.date_range('2024-01-01', periods=len(prices) * 1440, freq='1min', tz='UTC')
    close = [p for p in prices for _ in range(1440)]
    frame = pd.DataFrame({'open': close, 'high': close, 'low': close, 'close': close,
                          'volume': 1.0, 'taker_buy_volume': 0.5}, index=idx)
    return frame


def test_gate_off_returns_empty_weights():
    config = BookASmallTsmomConfig(sma_gate_days=5, mom_lookback_days=3, top_n=2)
    # falling BTC -> gate off
    minutes = {
        'BTCUSDT': _fake_minutes([100, 99, 98, 97, 96, 95, 94, 93, 92, 91] * 30),
        'SOLUSDT': _fake_minutes([10] * 300),
    }
    panel = build_daily_panel(minutes, config)
    day = panel.index[-1]
    assert target_weights_for_day(panel, day, config) == {}
