"""Checksum-verified public Binance spot monthly klines."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .scalp_data import COLUMNS, _get_with_read_retries, validate_minutes


BASE_URL = 'https://data.binance.vision/data/spot/monthly'


def _timestamp_index(values):
    numeric = pd.to_numeric(values)
    unit = 'us' if float(numeric.abs().median()) > 1e14 else 'ms'
    return pd.to_datetime(numeric, unit=unit, utc=True)


def spot_archive(symbol: str, month: str, cache: str):
    relative = f'klines/{symbol}/1m/{symbol}-1m-{month}.zip'
    path = Path(cache) / 'spot' / relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    if not path.exists() or not checksum_path.exists():
        session = requests.Session()
        session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
        response = _get_with_read_retries(session, f'{BASE_URL}/{relative}', timeout=60)
        response.raise_for_status()
        checksum = _get_with_read_retries(
            session, f'{BASE_URL}/{relative}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        digest = sha256(response.content).hexdigest()
        if digest != checksum.text.split()[0]:
            raise ValueError(f'Spot archive checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    if digest != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached spot archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            raw = pd.read_csv(source, header=None)
    if len(raw.columns) != len(COLUMNS):
        raise ValueError('Unexpected spot kline archive schema')
    raw.columns = COLUMNS
    raw.index = _timestamp_index(raw.timestamp)
    frame = raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float)
    return frame, {'url': f'{BASE_URL}/{relative}', 'sha256': digest, 'rows': len(frame)}


def load_spot_archives(symbol: str, start, end, cache: str):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    months = pd.period_range(
        start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None), freq='M')
    frames, manifest = [], []
    for month in months:
        frame, source = spot_archive(symbol, str(month), cache)
        frames.append(frame)
        manifest.append(source)
    result = pd.concat(frames).sort_index()
    result = result.loc[(result.index >= start) & (result.index < end)]
    validate_minutes(result)
    if result.index[0] != start or result.index[-1] + pd.Timedelta(minutes=1) != end:
        raise ValueError(f'Spot period not fully covered for {symbol}')
    return result, manifest
