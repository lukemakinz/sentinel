"""Recent open-interest history for S20's OI confirmation, from Binance's
public futures REST 'openInterestHist' endpoint (5-minute granularity, ~30
days retention) — no API key, no order placement. Only `open_interest` is
populated for real; the other columns exist purely so the returned frame
matches backtest.metrics_data's schema, which
l1_filter.order_block_oi_confirmation_scalp.oi_features expects — S20's
route='oi' never reads them.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

OPEN_INTEREST_HIST_URL = 'https://fapi.binance.com/futures/data/openInterestHist'
TIMEOUT_SECONDS = 15


def fetch_recent_open_interest(symbol: str, hours: int = 12) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    response = requests.get(OPEN_INTEREST_HIST_URL, params={
        'symbol': symbol, 'period': '5m',
        'startTime': int(start.timestamp() * 1000), 'endTime': int(end.timestamp() * 1000),
        'limit': 500,
    }, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise ValueError(f'No open interest history returned for {symbol}')
    index = pd.to_datetime([row['timestamp'] for row in rows], unit='ms', utc=True)
    open_interest = pd.Series([float(row['sumOpenInterest']) for row in rows], index=index)
    frame = pd.DataFrame({
        'open_interest': open_interest,
        'open_interest_value': open_interest,  # unused by route='oi'; placeholder
        'toptrader_account_ratio': 0.0,
        'toptrader_position_ratio': 0.0,
        'retail_account_ratio': 0.0,
        'taker_buy_sell_vol_ratio': 0.0,
    }).sort_index()
    return frame.loc[~frame.index.duplicated(keep='last')]
