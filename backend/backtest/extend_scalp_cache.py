"""Extend local Binance UM cache with monthly + daily archives."""
from datetime import datetime, timezone

import pandas as pd
import requests

from .scalp_data import (
    MissingMarketDataError,
    _daily_kline_archive,
    _repair_missing_minutes,
    archive,
    load_archives,
    validate_minutes,
)


def data_end_exclusive(now: datetime | None = None) -> pd.Timestamp:
    """Exclusive end bound; uses start of today UTC (Binance daily may lag 1d)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return pd.Timestamp(now.date(), tz='UTC')


def prefetch_month(symbol: str, month: str, cache: str) -> bool:
    for kind in ('klines', 'fundingRate'):
        try:
            archive(symbol, month, kind, cache)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return False
            raise
    return True


def load_range_resilient(symbol: str, start: pd.Timestamp, end: pd.Timestamp, cache: str):
    """Monthly chunks where available; daily repair for gaps and missing months."""
    start = start.tz_convert('UTC') if start.tzinfo else start.tz_localize('UTC')
    end = end.tz_convert('UTC') if end.tzinfo else end.tz_localize('UTC')
    months = pd.period_range(start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None), freq='M')
    candles, funding, manifest = [], [], []
    for month in months:
        label = str(month)
        if not prefetch_month(symbol, label, cache):
            continue
        raw, entry = archive(symbol, label, 'klines', cache)
        raw.columns = [
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
            'quote_volume', 'num_trades', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore',
        ]
        raw.index = pd.to_datetime(raw.timestamp, unit='ms', utc=True)
        candles.append(raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float))
        manifest.append(entry)
        raw, entry = archive(symbol, label, 'fundingRate', cache)
        raw.index = pd.to_datetime(raw.calc_time, unit='ms', utc=True).dt.floor('min')
        funding.append(raw.last_funding_rate.astype(float))
        manifest.append(entry)
    if not candles:
        raise MissingMarketDataError(f'No monthly data for {symbol} in range')
    frame = pd.concat(candles).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    def fetch_day(day: str):
        try:
            return _daily_kline_archive(symbol, day, cache)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise MissingMarketDataError(f'Daily not published: {day}') from exc
            raise

    try:
        frame, repair_manifest = _repair_missing_minutes(frame, start, end, fetch_day)
        manifest.extend(repair_manifest)
        validate_minutes(frame)
    except MissingMarketDataError:
        # Trim to last contiguous minute if today's daily zip is not on Binance yet.
        if frame.empty:
            raise
        end = frame.index[-1] + pd.Timedelta(minutes=1)
        frame = frame.loc[frame.index < end]
        validate_minutes(frame)
    rates = pd.concat(funding).sort_index() if funding else pd.Series(dtype=float)
    return frame, rates, manifest


def extend_symbols(symbols, cache: str, from_date: str, end: pd.Timestamp | None = None):
    end = end or data_end_exclusive()
    start = pd.Timestamp(from_date, tz='UTC')
    report = {}
    for symbol in symbols:
        try:
            frame, rates, _ = load_range_resilient(symbol, start, end, cache)
            report[symbol] = {
                'rows': len(frame),
                'from': str(frame.index[0]),
                'to': str(frame.index[-1]),
                'funding_points': len(rates),
            }
            print(symbol, 'OK', report[symbol], flush=True)
        except Exception as exc:
            report[symbol] = {'error': str(exc)}
            print(symbol, 'FAIL', exc, flush=True)
    return report
