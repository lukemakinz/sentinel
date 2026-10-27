"""Load 1m klines and funding through a date not yet covered by monthly archives.

Complete months come from checksumed monthly archives (``load_archives``); the
remaining days from checksumed daily kline archives; funding for months
without a monthly archive from Binance's public REST history.
"""
from __future__ import annotations

import pandas as pd
import requests

from .scalp_data import (
    MissingMarketDataError,
    _daily_kline_archive,
    load_archives,
    validate_minutes,
)

FUNDING_URL = 'https://fapi.binance.com/fapi/v1/fundingRate'


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def rest_funding(symbol: str, start, end, session=None) -> pd.Series:
    """Settled funding rates in [start, end), minute-floored like the archives."""
    session = session or requests.Session()
    start_ms, end_ms = int(_utc(start).value // 10**6), int(_utc(end).value // 10**6)
    rows = []
    while start_ms < end_ms:
        batch = session.get(FUNDING_URL, params={
            'symbol': symbol, 'startTime': start_ms, 'endTime': end_ms - 1, 'limit': 1000,
        }, timeout=30)
        batch.raise_for_status()
        batch = batch.json()
        if not batch:
            break
        rows.extend(batch)
        start_ms = int(batch[-1]['fundingTime']) + 1
    index = pd.to_datetime([int(r['fundingTime']) for r in rows], unit='ms', utc=True).floor('min')
    return pd.Series([float(r['fundingRate']) for r in rows], index=index).sort_index()


def load_through(symbol: str, start, end, cache: str, monthly_end) -> tuple:
    """Minutes and funding for [start, end); monthly archives only before monthly_end."""
    start, end, monthly_end = _utc(start), _utc(end), _utc(monthly_end)
    minutes, funding, manifest = load_archives(symbol, start, monthly_end, cache)
    frames = [minutes]
    for day in pd.date_range(monthly_end, end - pd.Timedelta(days=1), freq='D'):
        daily, source = _daily_kline_archive(symbol, day.strftime('%Y-%m-%d'), cache)
        frames.append(daily)
        manifest.append(source)
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    frame = frame.loc[~frame.index.duplicated(keep='first')]
    validate_minutes(frame)
    if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=1) != end:
        raise MissingMarketDataError(f'{symbol}: requested period is not fully covered')
    extra = rest_funding(symbol, monthly_end, end)
    manifest.append({'url': FUNDING_URL, 'symbol': symbol, 'rows': len(extra),
                     'from': str(monthly_end), 'to': str(end)})
    funding = pd.concat([funding, extra]).sort_index()
    funding = funding.loc[~funding.index.duplicated(keep='first')]
    return frame, funding, manifest
