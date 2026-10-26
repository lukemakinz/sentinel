"""Verified public Binance archives for lower-frequency research.

The cache is independent from the application database.  Downloads are
anonymous monthly USD-M archives and are checksum-verified before parsing.
"""
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = 'https://data.binance.vision/data/futures/um/monthly'
COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
           'quote_volume', 'num_trades', 'taker_buy_volume',
           'taker_buy_quote_volume', 'ignore']
ALLOWED_INTERVALS = {'5m': 5, '1d': 1440}
FUNDING_COLUMNS = ['calc_time', 'funding_interval_hours', 'last_funding_rate']


def _timestamps(values):
    numeric = pd.to_numeric(values, errors='raise')
    unit = 'us' if float(numeric.abs().median()) >= 100_000_000_000_000 else 'ms'
    return pd.to_datetime(numeric, unit=unit, utc=True)


def _read_archive_csv(source, kind):
    """Parse both old headerless and newer header-bearing Binance CSVs."""
    frame = pd.read_csv(source, header=None)
    expected = COLUMNS if kind == 'klines' else FUNDING_COLUMNS
    if len(frame.columns) != len(expected):
        raise ValueError(f'Unexpected {kind} archive schema')
    frame.columns = expected
    numeric_time = pd.to_numeric(frame[expected[0]], errors='coerce')
    header_rows = numeric_time.isna()
    if header_rows.any():
        if header_rows.sum() != 1 or not header_rows.iloc[0]:
            raise ValueError(f'Malformed {kind} archive timestamp')
        frame = frame.loc[~header_rows].copy()
    if frame.empty:
        raise ValueError(f'Empty {kind} archive')
    return frame.reset_index(drop=True)


def _archive(symbol, month, kind, cache, interval='5m'):
    if kind == 'klines':
        if interval not in ALLOWED_INTERVALS:
            raise ValueError(f'Unsupported interval: {interval}')
        relative = f'klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip'
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
        response = session.get(f'{BASE_URL}/{relative}', timeout=60)
        response.raise_for_status()
        checksum = session.get(f'{BASE_URL}/{relative}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        expected = checksum.text.split()[0]
        if sha256(response.content).hexdigest() != expected:
            raise ValueError(f'Archive checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Each agent is assigned a disjoint cache phase, but replace from a
        # temporary sibling also avoids leaving a partial ZIP after failure.
        temporary = path.with_suffix('.zip.partial')
        temporary.write_bytes(response.content)
        temporary.replace(path)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    if digest != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        members = [name for name in zipped.namelist() if not name.endswith('/')]
        if len(members) != 1:
            raise ValueError(f'Unexpected ZIP contents: {path}')
        with zipped.open(members[0]) as source:
            frame = _read_archive_csv(source, kind)
    return frame, {
        'url': f'{BASE_URL}/{relative}',
        'sha256': digest,
        'rows': len(frame),
        'kind': kind,
        **({'interval': interval} if kind == 'klines' else {}),
    }


def validate_interval(frame, minutes=5, allow_gaps=False):
    """Refuse gaps, duplicate bars, invalid OHLCV or ambiguous coverage."""
    if minutes <= 0:
        raise ValueError('minutes must be positive')
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError('Empty, unsorted or duplicate interval data')
    expected = pd.Timedelta(minutes=minutes)
    differences = frame.index.to_series().diff().dropna()
    if (differences < expected).any():
        raise ValueError(f'Overlapping {minutes}m bars')
    if not allow_gaps and not (differences == expected).all():
        raise ValueError(f'Missing {minutes}m bars: refusing discontinuous market data')
    required = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
    if not set(required).issubset(frame):
        raise ValueError('Missing required OHLCV columns')
    values = frame[required].to_numpy(dtype=float)
    if (not np.isfinite(values).all()
            or (frame[['open', 'high', 'low', 'close']] <= 0).any().any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()
            or (frame.volume < 0).any()
            or (frame.taker_buy_volume < 0).any()
            or (frame.taker_buy_volume > frame.volume + 1e-8).any()):
        raise ValueError('Invalid interval OHLCV')


def load_interval_archives(symbol, start, end, cache, interval='5m', allow_gaps=False):
    """Load and verify an exact UTC ``[start, end)`` interval plus funding.

    Returns ``(frame, funding, manifest)``.  ``frame.close_time`` is a UTC
    timestamp, which lets daily signal code enforce candle availability.
    """
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f'Unsupported interval: {interval}')
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    if end <= start:
        raise ValueError('end must be after start')
    interval_delta = pd.Timedelta(minutes=ALLOWED_INTERVALS[interval])
    if start.floor(interval_delta) != start or end.floor(interval_delta) != end:
        raise ValueError('Requested bounds must align with the archive interval')
    months = pd.period_range(
        start.tz_localize(None), (end - interval_delta).tz_localize(None), freq='M')
    candles, funding_rows, manifest = [], [], []
    for month in months:
        raw, entry = _archive(symbol, str(month), 'klines', cache, interval)
        if len(raw.columns) != len(COLUMNS):
            raise ValueError('Unexpected kline archive schema')
        raw.columns = COLUMNS
        raw.index = _timestamps(raw.timestamp)
        frame = raw[['open', 'high', 'low', 'close', 'volume',
                     'taker_buy_volume']].astype(float)
        frame['close_time'] = _timestamps(raw.close_time).to_numpy()
        candles.append(frame)
        manifest.append(entry)

        raw, entry = _archive(symbol, str(month), 'fundingRate', cache)
        funding_index = pd.DatetimeIndex(_timestamps(raw.calc_time)).floor('min')
        funding_rows.append(pd.Series(
            raw.last_funding_rate.astype(float).to_numpy(), index=funding_index))
        manifest.append(entry)

    frame = pd.concat(candles).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    validate_interval(frame, ALLOWED_INTERVALS[interval], allow_gaps=allow_gaps)
    if (not allow_gaps
            and (frame.index[0] != start or frame.index[-1] + interval_delta != end)):
        raise ValueError('Requested period is not fully covered')
    expected_rows = int((end - start) / interval_delta)
    actual_rows = len(frame)
    missing_rows = expected_rows - actual_rows
    if missing_rows < 0:
        raise ValueError('Archive contains more rows than the requested grid')
    manifest.append({
        'kind': 'coverage',
        'interval': interval,
        'start': str(start),
        'end': str(end),
        'expected_rows': expected_rows,
        'actual_rows': actual_rows,
        'missing_rows': missing_rows,
        'missing_fraction': missing_rows / expected_rows,
        'first_bar': str(frame.index[0]),
        'last_bar': str(frame.index[-1]),
    })
    funding = pd.concat(funding_rows).sort_index()
    funding = funding.loc[(funding.index >= start) & (funding.index < end)]
    if funding.index.has_duplicates or not np.isfinite(funding.to_numpy(dtype=float)).all():
        raise ValueError('Invalid funding history')
    return frame, funding.astype(float), manifest


def regularize_interval(frame, start, end, minutes=5):
    """Reindex gaps as marked synthetic carry bars for conservative replay.

    A synthetic row carries the last *real* close into every OHLC field and
    has zero volume.  Callers must not enter, exit, or trigger stops/targets on
    those rows.  A leading gap is refused because it has no causal price.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    delta = pd.Timedelta(minutes=minutes)
    validate_interval(frame, minutes=minutes, allow_gaps=True)
    grid = pd.date_range(start, end, freq=delta, inclusive='left')
    if frame.index.min() > start:
        raise ValueError('Cannot causally fill a leading execution gap')
    original = frame.loc[(frame.index >= start) & (frame.index < end)].copy()
    result = original.reindex(grid)
    result['synthetic'] = ~result.index.isin(original.index)
    prior_close = result.close.ffill()
    if prior_close.isna().any():
        raise ValueError('Cannot causally fill a leading execution gap')
    for column in ('open', 'high', 'low', 'close'):
        result[column] = result[column].where(~result.synthetic, prior_close)
    for column in ('volume', 'taker_buy_volume'):
        if column in result:
            result[column] = result[column].where(~result.synthetic, 0.0)
    if 'close_time' in result:
        synthetic_close = result.index + delta - pd.Timedelta(milliseconds=1)
        result['close_time'] = result.close_time.where(
            ~result.synthetic, pd.Series(synthetic_close, index=result.index))
    validate_interval(result, minutes=minutes)
    return result
