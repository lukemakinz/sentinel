"""Bulk historical tick-trade downloaders for CE-2 (cross-exchange
lead-lag), one function per venue, all returning a DataFrame indexed by
UTC timestamp with columns price, quantity, side ('buy'/'sell', the
AGGRESSOR side). All three venues publish bulk daily archives (not just
paginated REST), confirmed working:
    Binance: data.binance.vision/.../futures/um/daily/aggTrades/...
    Bybit:   public.bybit.com/trading/<SYMBOL>/<SYMBOL><date>.csv.gz
    OKX:     static.okx.com/cdn/okex/traderecords/trades/daily/<YYYYMMDD>/...
"""
import gzip
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import requests

from .download_agg_trades import load_agg_trades_day  # Binance, already built for M1/M3


def load_binance_trades_day(symbol: str, day: str, cache: str) -> pd.DataFrame:
    trades = load_agg_trades_day(symbol, day, cache)
    out = trades.copy()
    out['side'] = out.is_buyer_maker.map({True: 'sell', False: 'buy'})  # taker side
    return out[['price', 'quantity', 'side']]


def load_bybit_trades_day(symbol: str, day: str, cache: str) -> pd.DataFrame:
    cache_path = Path(cache) / f'bybit_trades_{symbol}_{day}.parquet'
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    url = f'https://public.bybit.com/trading/{symbol}/{symbol}{day}.csv.gz'
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with gzip.open(BytesIO(resp.content)) as f:
        df = pd.read_csv(f)
    df.index = pd.to_datetime(df.timestamp, unit='s', utc=True)
    df = df.rename(columns={'size': 'quantity'})
    df['side'] = df.side.str.lower()
    out = df[['price', 'quantity', 'side']].sort_index()
    Path(cache).mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path)
    return out


OKX_INST = {'BTCUSDT': 'BTC-USDT-SWAP', 'ETHUSDT': 'ETH-USDT-SWAP', 'SOLUSDT': 'SOL-USDT-SWAP'}


def load_okx_trades_day(symbol: str, day: str, cache: str) -> pd.DataFrame:
    cache_path = Path(cache) / f'okx_trades_{symbol}_{day}.parquet'
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    inst = OKX_INST[symbol]
    yyyymmdd = day.replace('-', '')
    url = f'https://static.okx.com/cdn/okex/traderecords/trades/daily/{yyyymmdd}/{inst}-trades-{day}.zip'
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with ZipFile(BytesIO(resp.content)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            df = pd.read_csv(f)
    df.columns = [c.strip() for c in df.columns]
    ts_col = next(c for c in df.columns if 'time' in c.lower() or 'ts' in c.lower())
    price_col = next(c for c in df.columns if c.lower() in ('px', 'price'))
    size_col = next(c for c in df.columns if c.lower() in ('sz', 'size', 'quantity'))
    side_col = next(c for c in df.columns if 'side' in c.lower())
    df.index = pd.to_datetime(df[ts_col].astype('int64'), unit='ms', utc=True)
    out = pd.DataFrame({
        'price': df[price_col].astype(float),
        'quantity': df[size_col].astype(float),
        'side': df[side_col].str.lower(),
    }, index=df.index).sort_index()
    Path(cache).mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path)
    return out
