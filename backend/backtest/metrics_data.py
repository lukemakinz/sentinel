"""Public Binance USD-M 'metrics' archives (open interest, top-trader
position ratio, global long/short account ratio, taker buy/sell volume
ratio), cached locally; never touches the trading DB. Same free, unauthenticated
host as scalp_data.py's klines/fundingRate, different (daily, not monthly)
archive layout and 5-minute granularity.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .scalp_data import _get_with_read_retries

BASE_URL = 'https://data.binance.vision/data/futures/um/daily/metrics'
COLUMNS = ['create_time', 'symbol', 'sum_open_interest', 'sum_open_interest_value',
           'count_toptrader_long_short_ratio', 'sum_toptrader_long_short_ratio',
           'count_long_short_ratio', 'sum_taker_long_short_vol_ratio']


class MetricsDataIntegrityError(ValueError):
    """Required Binance metrics fields are missing or malformed."""


def _parse_metrics_csv(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Pure parsing/validation step, kept separate from the network fetch so
    it can be unit-tested without mocking HTTP."""
    if list(raw.columns) != COLUMNS:
        raise MetricsDataIntegrityError('Unexpected metrics archive schema')
    raw = raw.loc[raw.symbol == symbol]
    raw = raw.set_index(pd.to_datetime(raw.create_time, utc=True))
    return raw[['sum_open_interest', 'sum_open_interest_value',
               'count_toptrader_long_short_ratio', 'sum_toptrader_long_short_ratio',
               'count_long_short_ratio', 'sum_taker_long_short_vol_ratio']]


def _daily_archive(symbol: str, day: str, cache: str):
    relative = f'{symbol}/{symbol}-metrics-{day}.zip'
    path = Path(cache) / 'metrics' / relative
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


def load_metrics(symbol: str, start: str, end: str, cache: str,
                 include_freshness: bool = False, required_columns=None):
    """Load daily 'metrics' archives and verify [start, end) coverage.

    Returned frame is indexed by UTC timestamp at 5-minute resolution with
    columns open_interest, open_interest_value, toptrader_account_ratio,
    toptrader_position_ratio, retail_account_ratio, taker_buy_sell_vol_ratio.
    Small gaps (a handful of missing 5-minute samples around exchange
    incidents) are forward-filled rather than treated as fatal, unlike the
    1-minute kline archives — Binance's own metrics feed is not gap-free.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    days = pd.date_range(start.floor('D'), (end - pd.Timedelta(minutes=1)).floor('D'), freq='D')

    frames, manifest = [], []
    for day in days:
        raw, entry = _daily_archive(symbol, day.strftime('%Y-%m-%d'), cache)
        frames.append(_parse_metrics_csv(raw, symbol))
        manifest.append(entry)

    frame = pd.concat(frames)
    return _assemble_metrics(
        frame, start, end, include_freshness=include_freshness,
        required_columns=required_columns), manifest


def prefetch_metrics_archives(symbols, start: str, end: str, cache: str,
                              workers: int = 16) -> int:
    """Populate independent daily archives concurrently, preserving checksums."""
    if workers < 1:
        raise ValueError('workers must be positive')
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    if end <= start:
        raise ValueError('end must be after start')
    days = pd.date_range(
        start.floor('D'), (end - pd.Timedelta(minutes=1)).floor('D'), freq='D')
    tasks = [
        (symbol, day.strftime('%Y-%m-%d'), cache)
        for symbol in tuple(symbols) for day in days
    ]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(lambda task: _daily_archive(*task), tasks))
    return len(tasks)


def _assemble_metrics(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                      include_freshness: bool = False,
                      required_columns=None) -> pd.DataFrame:
    """Sort/dedup/clip/reindex/ffill step, pure and separately testable."""
    frame = frame.sort_index()
    frame = frame.loc[~frame.index.duplicated(keep='last')]
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    if frame.empty:
        raise MetricsDataIntegrityError('No metrics data for requested period')
    full_index = pd.date_range(start, end - pd.Timedelta(minutes=5), freq='5min')
    observed = pd.Series(full_index.isin(frame.index), index=full_index, dtype=bool)
    # Preserve the DatetimeIndex resolution instead of round-tripping through
    # ``asi8``.  Pandas 3 may store this index at microsecond resolution while
    # ``pd.to_datetime(integer)`` assumes nanoseconds; the old conversion then
    # moved every real 2024+ observation into January 1970 and made all metrics
    # appear millions of minutes stale.
    observed_at = pd.Series(full_index, index=full_index).where(observed).ffill()
    frame = frame.reindex(full_index).ffill()
    frame.columns = ['open_interest', 'open_interest_value', 'toptrader_account_ratio',
                     'toptrader_position_ratio', 'retail_account_ratio',
                     'taker_buy_sell_vol_ratio']
    required = tuple(required_columns or frame.columns)
    unknown = set(required).difference(frame.columns)
    if unknown:
        raise MetricsDataIntegrityError(
            f'Unknown required metrics columns: {sorted(unknown)}')
    if frame.loc[:, required].isna().any().any():
        raise MetricsDataIntegrityError(
            'Metrics data has a leading gap that ffill cannot cover')
    if not np.isfinite(frame.loc[:, required].to_numpy()).all():
        raise MetricsDataIntegrityError('Non-finite metrics data')
    if include_freshness:
        frame['metrics_age_minutes'] = (
            (frame.index.to_series() - observed_at).dt.total_seconds() / 60.0
        )
        frame['metrics_observed'] = observed
    return frame
