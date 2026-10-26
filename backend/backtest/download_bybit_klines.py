"""Downloads Bybit USDT-perp 1-minute klines via REST (paginated, 1000
candles/request), cached to local parquet-free CSV per symbol/month,
matching this project's other cache conventions. Used for CE-1
(cross-exchange dislocation): Bybit is the reference price Binance is
compared against.
"""
import time
from pathlib import Path

import pandas as pd
import requests


BASE_URL = 'https://api.bybit.com/v5/market/kline'


def load_bybit_klines(symbol: str, start: str, end: str, cache: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz='UTC')
    end_ts = pd.Timestamp(end, tz='UTC')
    cache_path = Path(cache) / f'{symbol}_bybit_1m_{start}_{end}.csv'
    if cache_path.exists():
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        df.index = df.index.tz_localize('UTC') if df.index.tz is None else df.index
        return df

    session = requests.Session()
    all_rows = []
    cursor_end_ms = int(end_ts.timestamp() * 1000)
    start_ms = int(start_ts.timestamp() * 1000)
    n_requests = 0
    while cursor_end_ms > start_ms:
        resp = session.get(BASE_URL, params={
            'category': 'linear', 'symbol': symbol, 'interval': '1',
            'end': cursor_end_ms, 'limit': 1000,
        }, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get('result', {}).get('list', [])
        n_requests += 1
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])
        if oldest_ts >= cursor_end_ms:
            break
        cursor_end_ms = oldest_ts
        time.sleep(0.05)
        if n_requests > 400:
            break

    if not all_rows:
        raise ValueError(f'No data returned for {symbol} {start}..{end}')

    df = pd.DataFrame(all_rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
    df['ts'] = pd.to_datetime(df.ts.astype('int64'), unit='ms', utc=True)
    df = df.set_index('ts').sort_index()
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    df = df[(df.index >= start_ts) & (df.index < end_ts)]
    df = df[~df.index.duplicated(keep='last')]

    Path(cache).mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path)
    return df
