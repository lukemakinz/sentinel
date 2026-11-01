"""Public Binance USD-M archives, cached locally; never touches the trading DB."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import time
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = 'https://data.binance.vision/data/futures/um/monthly'
DAILY_BASE_URL = 'https://data.binance.vision/data/futures/um/daily'
COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
           'quote_volume', 'num_trades', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']


class MarketDataIntegrityError(ValueError):
    """Base class for unusable public market data."""


class MissingMarketDataError(MarketDataIntegrityError):
    """An exact public source could not supply required market minutes."""


class InvalidMarketDataError(MarketDataIntegrityError):
    """Public market data violates required OHLCV invariants."""


def _get_with_read_retries(
    session,
    url: str,
    timeout: float,
    attempts: int = 5,
    sleeper=time.sleep,
):
    """Retry failures raised while Requests materializes response content."""
    if attempts < 1:
        raise ValueError('attempts must be positive')
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=timeout)
            _ = response.content
            return response
        except (requests.ConnectionError, requests.Timeout):
            if attempt + 1 >= attempts:
                raise
            sleeper(min(2 ** attempt, 10))


def archive(symbol, month, kind, cache):
    if kind == 'klines':
        relative = f'klines/{symbol}/1m/{symbol}-1m-{month}.zip'
    elif kind == 'fundingRate':
        relative = f'fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip'
    else:
        raise ValueError(kind)
    path = Path(cache) / relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    if not path.exists() or not checksum_path.exists():
        session = requests.Session()
        session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
        response = _get_with_read_retries(
            session, f'{BASE_URL}/{relative}', timeout=60)
        response.raise_for_status()
        checksum = _get_with_read_retries(
            session, f'{BASE_URL}/{relative}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        if sha256(response.content).hexdigest() != checksum.text.split()[0]:
            raise ValueError(f'Archive checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    if digest != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            frame = pd.read_csv(source)
    return frame, {'url': f'{BASE_URL}/{relative}', 'sha256': digest, 'rows': len(frame)}


def validate_minutes(frame):
    """Refuse gaps, duplicates, malformed prices or absent aggressor volume."""
    if frame.empty or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise InvalidMarketDataError('Empty, unsorted or duplicate minute data')
    if not (frame.index.to_series().diff().dropna() == pd.Timedelta(minutes=1)).all():
        raise MissingMarketDataError(
            'Missing minutes: refusing an apparently continuous backtest')
    values = frame[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']]
    if not np.isfinite(values.to_numpy()).all():
        raise InvalidMarketDataError('Non-finite market data')
    if ((frame[['open', 'high', 'low', 'close']] <= 0).any().any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()
            or (frame.volume < 0).any()
            or (frame.taker_buy_volume < 0).any()
            or (frame.taker_buy_volume > frame.volume + 1e-8).any()
            or frame.taker_buy_volume.sum() <= 0):
        raise InvalidMarketDataError('Invalid OHLCV / taker volume')


REST_KLINES_URL = 'https://fapi.binance.com/fapi/v1/klines'


def _rest_day_klines(symbol: str, day: str, cache: str, session=None):
    """Exact 1m klines for one past UTC day from Binance REST.

    Fallback only for days Binance never published as a daily archive (e.g.
    2026-10-28 for every symbol).  REST has no checksum, so the day must be
    complete (1440 minutes) and is cached once it is.
    """
    path = Path(cache) / 'rest_daily' / symbol / f'{symbol}-1m-{day}.csv'
    if not path.exists():
        session = session or requests.Session()
        start = pd.Timestamp(day, tz='UTC')
        if start + pd.Timedelta(days=1) > pd.Timestamp.now(tz='UTC'):
            raise MissingMarketDataError(f'{symbol} {day}: day not complete yet')
        rows, cursor = [], int(start.value // 10**6)
        end_ms = cursor + 86_400_000
        while cursor < end_ms:
            response = session.get(REST_KLINES_URL, params={
                'symbol': symbol, 'interval': '1m', 'startTime': cursor,
                'endTime': end_ms - 1, 'limit': 1500,
            }, timeout=30)
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            cursor = int(batch[-1][0]) + 60_000
        raw = pd.DataFrame(rows, columns=COLUMNS)
        if len(raw) != 1440:
            raise MissingMarketDataError(f'{symbol} {day}: REST returned {len(raw)} of 1440 minutes')
        path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(path, index=False)
    raw = pd.read_csv(path)
    raw.index = pd.to_datetime(raw.timestamp, unit='ms', utc=True)
    frame = raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float)
    return frame, {'url': REST_KLINES_URL, 'symbol': symbol, 'day': day,
                   'source': 'rest_fallback_no_daily_archive', 'rows': len(frame)}


def _daily_kline_archive(symbol: str, day: str, cache: str):
    relative = f'klines/{symbol}/1m/{symbol}-1m-{day}.zip'
    path = Path(cache) / 'daily' / relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    url = f'{DAILY_BASE_URL}/{relative}'
    rest_cached = Path(cache) / 'rest_daily' / symbol / f'{symbol}-1m-{day}.csv'
    if (not path.exists() or not checksum_path.exists()) and rest_cached.exists():
        return _rest_day_klines(symbol, day, cache)
    if not path.exists() or not checksum_path.exists():
        session = requests.Session()
        session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
        response = _get_with_read_retries(session, url, timeout=60)
        if response.status_code == 404:
            return _rest_day_klines(symbol, day, cache)
        response.raise_for_status()
        checksum = _get_with_read_retries(
            session, f'{url}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        if sha256(response.content).hexdigest() != checksum.text.split()[0]:
            raise ValueError(f'Daily archive checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    if digest != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached daily archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            raw = pd.read_csv(source)
    if len(raw.columns) != len(COLUMNS):
        raise ValueError('Unexpected daily kline archive schema')
    raw.columns = COLUMNS
    raw.index = pd.to_datetime(raw.timestamp, unit='ms', utc=True)
    frame = raw[
        ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
    ].astype(float)
    return frame, {'url': url, 'sha256': digest, 'rows': len(frame)}


def _repair_missing_minutes(frame, start, end, fetch_day):
    """Fill archive packaging gaps only with exact checksumed daily candles."""
    expected = pd.date_range(start, end - pd.Timedelta(minutes=1), freq='1min')
    missing = expected.difference(frame.index)
    if missing.empty:
        return frame, []
    replacements, sources = [], []
    for day in sorted(set(missing.floor('D'))):
        daily, source = fetch_day(day.strftime('%Y-%m-%d'))
        selected = daily.loc[daily.index.intersection(missing)]
        if not selected.empty:
            replacements.append(selected)
        sources.append(source)
    if replacements:
        frame = pd.concat([frame, *replacements]).sort_index()
    unresolved = expected.difference(frame.index)
    if not unresolved.empty:
        raise MissingMarketDataError(
            f'Missing minutes remain after exact daily lookup: {unresolved[:5].tolist()}')
    validate_minutes(frame)
    return frame, sources


def load_archives(symbol, start, end, cache, repair_from_daily=False):
    """Load whole UTC months and verify requested [start, end) coverage."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    months = pd.period_range(start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None), freq='M')
    candles, funding, manifest = [], [], []
    for month in months:
        raw, entry = archive(symbol, str(month), 'klines', cache)
        if len(raw.columns) != len(COLUMNS):
            raise ValueError('Unexpected kline archive schema')
        raw.columns = COLUMNS
        raw.index = pd.to_datetime(raw.timestamp, unit='ms', utc=True)
        candles.append(raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float))
        manifest.append(entry)
        raw, entry = archive(symbol, str(month), 'fundingRate', cache)
        # Archive timestamps have millisecond jitter around the settlement minute.
        raw.index = pd.to_datetime(raw.calc_time, unit='ms', utc=True).dt.floor('min')
        funding.append(raw.last_funding_rate.astype(float))
        manifest.append(entry)
    frame = pd.concat(candles).sort_index().loc[
        lambda x: (x.index >= start) & (x.index < end)]
    if repair_from_daily:
        frame, repair_manifest = _repair_missing_minutes(
            frame, start, end,
            lambda day: _daily_kline_archive(symbol, day, cache),
        )
        manifest.extend(repair_manifest)
    validate_minutes(frame)
    if frame.index[0] != start or frame.index[-1] + pd.Timedelta(minutes=1) != end:
        raise MissingMarketDataError('Requested period is not fully covered')
    rates = pd.concat(funding).sort_index()
    if rates.index.has_duplicates or not np.isfinite(rates).all():
        raise InvalidMarketDataError('Invalid funding history')
    return frame, rates, manifest
