"""Verified public Binance spot/perpetual/mark/funding archives for carry research.

Only hourly prices are used.  The cache is deliberately separate from the
minute-scalping cache and contains no account or exchange API data.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SPOT_BASE = 'https://data.binance.vision/data/spot/monthly'
FUTURES_BASE = 'https://data.binance.vision/data/futures/um/monthly'
SPOT_DAILY_BASE = 'https://data.binance.vision/data/spot/daily'
FUTURES_DAILY_BASE = 'https://data.binance.vision/data/futures/um/daily'
KLINE_COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
    'quote_volume', 'num_trades', 'taker_buy_volume',
    'taker_buy_quote_volume', 'ignore',
]


@dataclass(frozen=True)
class ArchiveSpec:
    symbol: str
    month: str
    stream: str
    base_url: str
    relative: str

    @property
    def url(self) -> str:
        return f'{self.base_url}/{self.relative}'


def _utc(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _months(start, end) -> list[str]:
    start, end = _utc(start), _utc(end)
    return [
        str(month) for month in pd.period_range(
            start.tz_localize(None),
            (end - pd.Timedelta(hours=1)).tz_localize(None),
            freq='M',
        )
    ]


def archive_spec(symbol: str, month: str, stream: str) -> ArchiveSpec:
    if stream == 'spot':
        relative = f'klines/{symbol}/1h/{symbol}-1h-{month}.zip'
        return ArchiveSpec(symbol, month, stream, SPOT_BASE, f'spot/{relative}')
    if stream == 'spot_1m':
        relative = f'klines/{symbol}/1m/{symbol}-1m-{month}.zip'
        return ArchiveSpec(symbol, month, stream, SPOT_BASE, f'spot/{relative}')
    if stream == 'perpetual':
        relative = f'klines/{symbol}/1h/{symbol}-1h-{month}.zip'
    elif stream == 'perpetual_1m':
        relative = f'klines/{symbol}/1m/{symbol}-1m-{month}.zip'
    elif stream == 'mark':
        relative = f'markPriceKlines/{symbol}/1h/{symbol}-1h-{month}.zip'
    elif stream == 'mark_1m':
        relative = f'markPriceKlines/{symbol}/1m/{symbol}-1m-{month}.zip'
    elif stream == 'funding':
        relative = f'fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip'
    else:
        raise ValueError(f'Unknown stream: {stream}')
    return ArchiveSpec(symbol, month, stream, FUTURES_BASE, f'futures/{relative}')


def daily_archive_spec(symbol: str, day, stream: str) -> ArchiveSpec:
    """Exact daily 1m fallback, kept separate from the monthly cache."""
    day = str(pd.Timestamp(day).date())
    if stream == 'spot_1m':
        relative = f'klines/{symbol}/1m/{symbol}-1m-{day}.zip'
        return ArchiveSpec(
            symbol, day, stream, SPOT_DAILY_BASE, f'spot_daily/{relative}')
    if stream == 'perpetual_1m':
        relative = f'klines/{symbol}/1m/{symbol}-1m-{day}.zip'
    elif stream == 'mark_1m':
        relative = f'markPriceKlines/{symbol}/1m/{symbol}-1m-{day}.zip'
    else:
        raise ValueError(f'Unsupported daily fallback stream: {stream}')
    return ArchiveSpec(
        symbol, day, stream, FUTURES_DAILY_BASE, f'futures_daily/{relative}')


def required_archive_specs(symbols, spot_start, market_start, end) -> list[ArchiveSpec]:
    specs = []
    for symbol in symbols:
        specs.extend(archive_spec(symbol, month, 'spot') for month in _months(spot_start, end))
        for month in _months(market_start, end):
            specs.extend(archive_spec(symbol, month, stream)
                         for stream in ('perpetual', 'mark', 'funding'))
    return specs


def minute_archive_specs(months_by_symbol: dict[str, set[str]]) -> list[ArchiveSpec]:
    """Return exact 1m spot/perpetual/mark archives for selected symbol-months."""
    return [
        archive_spec(symbol, month, stream)
        for symbol in sorted(months_by_symbol)
        for month in sorted(months_by_symbol[symbol])
        for stream in ('spot_1m', 'perpetual_1m', 'mark_1m')
    ]


def _remote_url(spec: ArchiveSpec) -> str:
    # The cache path carries a spot/futures namespace; Binance's URL does not.
    return (spec.url
            .replace('/monthly/spot/', '/monthly/')
            .replace('/monthly/futures/', '/monthly/')
            .replace('/daily/spot_daily/', '/daily/')
            .replace('/daily/futures_daily/', '/daily/'))


def _session() -> requests.Session:
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504])))
    return session


def ensure_archive(spec: ArchiveSpec, cache, download_missing=False) -> dict:
    path = Path(cache) / spec.relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    if not path.exists() or not checksum_path.exists():
        if not download_missing:
            raise FileNotFoundError(f'Verified archive missing in offline mode: {path}')
        session = _session()
        url = _remote_url(spec)
        payload = session.get(url, timeout=60)
        payload.raise_for_status()
        checksum = session.get(f'{url}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        expected = checksum.text.split()[0]
        if sha256(payload.content).hexdigest() != expected:
            raise ValueError(f'Archive checksum mismatch: {url}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload.content)
        checksum_path.write_text(checksum.text)
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached archive checksum mismatch: {path}')
    return {
        'stream': spec.stream,
        'month': spec.month,
        'url': _remote_url(spec),
        'sha256': digest,
        'bytes': path.stat().st_size,
    }


def prepare_archives(specs, cache, download_missing=False, workers=8) -> list[dict]:
    """Download/verify independent small archives concurrently, in stable order."""
    specs = list(specs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(
            lambda spec: ensure_archive(spec, cache, download_missing), specs))
    return rows


def _read_csv(spec: ArchiveSpec, cache) -> pd.DataFrame:
    path = Path(cache) / spec.relative
    ensure_archive(spec, cache, download_missing=False)
    with ZipFile(BytesIO(path.read_bytes())) as zipped:
        names = [name for name in zipped.namelist() if not name.endswith('/')]
        if len(names) != 1:
            raise ValueError(f'Unexpected ZIP contents: {path}')
        with zipped.open(names[0]) as source:
            # Old kline archives have no header while newer ones do.  Reading
            # them with pandas' inferred header silently drops every old
            # month's 00:00 bar.  Funding archives consistently have names.
            return pd.read_csv(source, header=0 if spec.stream == 'funding' else None)


def _timestamp_unit(values: pd.Series) -> str:
    maximum = float(pd.to_numeric(values, errors='raise').max())
    # Binance spot archives use microseconds from 2025 onward; futures remain ms.
    return 'us' if maximum >= 100_000_000_000_000 else 'ms'


def _load_klines(specs, cache, start, end,
                 allow_initial_listing_gap=False,
                 require_full_range=True) -> tuple[pd.DataFrame, list[dict]]:
    frames, manifest = [], []
    for spec in specs:
        raw = _read_csv(spec, cache)
        if len(raw.columns) != len(KLINE_COLUMNS):
            raise ValueError(f'Unexpected kline schema: {spec.url}')
        raw.columns = KLINE_COLUMNS
        raw['timestamp'] = pd.to_numeric(raw.timestamp, errors='coerce')
        raw = raw.loc[raw.timestamp.notna()].copy()
        raw.index = pd.to_datetime(
            raw.timestamp, unit=_timestamp_unit(raw.timestamp), utc=True)
        frame = raw[['open', 'high', 'low', 'close']].astype(float)
        frames.append(frame)
        metadata = ensure_archive(spec, cache)
        manifest.append({**metadata, 'rows': len(frame)})
    start, end = _utc(start), _utc(end)
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    if (frame.empty or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing):
        raise ValueError('Empty, unsorted or duplicate hourly prices')
    intervals = {
        pd.Timedelta(minutes=1) if spec.stream.endswith('_1m')
        else pd.Timedelta(hours=1)
        for spec in specs
    }
    if len(intervals) != 1:
        raise ValueError('Mixed kline intervals are not supported')
    interval = intervals.pop()
    if require_full_range and (
            (not allow_initial_listing_gap and frame.index[0] != start)
            or frame.index[-1] + interval != end):
        raise ValueError('Requested kline range is not fully covered')
    values = frame.to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values <= 0).any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError('Invalid hourly OHLC data')
    return frame, manifest


def missing_mark_archive_specs(symbol: str, mark: pd.DataFrame, start, end) -> list[ArchiveSpec]:
    expected = pd.date_range(_utc(start), _utc(end), freq='1h', inclusive='left')
    missing = expected.difference(mark.index)
    months = sorted({str(time.tz_localize(None).to_period('M')) for time in missing})
    return [archive_spec(symbol, month, 'mark_1m') for month in months]


def missing_hour_archive_specs(symbol: str, frame: pd.DataFrame, start, end,
                               stream: str) -> list[ArchiveSpec]:
    """Return the 1m archives needed for exact missing-hour observations."""
    fallback_stream = {
        'spot': 'spot_1m',
        'perpetual': 'perpetual_1m',
        'mark': 'mark_1m',
    }.get(stream)
    if fallback_stream is None:
        raise ValueError(f'Unsupported hourly fallback stream: {stream}')
    expected = pd.date_range(_utc(start), _utc(end), freq='1h', inclusive='left')
    missing = expected.difference(frame.index)
    months = sorted({str(time.tz_localize(None).to_period('M')) for time in missing})
    return [archive_spec(symbol, month, fallback_stream) for month in months]


def load_hour_fallback(specs, cache, missing_hours, require_all=True
                       ) -> tuple[pd.DataFrame, list[dict]]:
    """Extract exact hourly opens from matching verified public 1m archives.

    This never interpolates or forward-fills.  ``require_all=False`` is used
    only for mark data, whose remaining omissions are filled by the exact
    same-hour perpetual open and disclosed by the research runner.
    """
    wanted = pd.DatetimeIndex(missing_hours)
    frames, manifest = [], []
    for spec in specs:
        raw = _read_csv(spec, cache)
        if len(raw.columns) != len(KLINE_COLUMNS):
            raise ValueError(f'Unexpected 1m kline schema: {spec.url}')
        raw.columns = KLINE_COLUMNS
        raw['timestamp'] = pd.to_numeric(raw.timestamp, errors='coerce')
        raw = raw.loc[raw.timestamp.notna()].copy()
        raw.index = pd.to_datetime(
            raw.timestamp, unit=_timestamp_unit(raw.timestamp), utc=True)
        selected = raw.loc[raw.index.intersection(wanted), ['open', 'high', 'low', 'close']]
        frames.append(selected.astype(float))
        metadata = ensure_archive(spec, cache)
        manifest.append({**metadata, 'rows': len(raw), 'selected_hour_rows': len(selected)})
    fallback = pd.concat(frames).sort_index() if frames else pd.DataFrame()
    remaining = wanted.difference(fallback.index)
    if require_all and len(remaining):
        raise ValueError(
            'Exact 1m fallback is also missing required hours: '
            + ', '.join(map(str, remaining[:10])))
    return fallback, manifest


def load_mark_hour_fallback(specs, cache, missing_hours) -> tuple[pd.DataFrame, list[dict]]:
    """Backward-compatible strict wrapper for the mark-only fallback."""
    return load_hour_fallback(specs, cache, missing_hours, require_all=True)


def _load_funding(specs, cache, start, end) -> tuple[pd.Series, list[dict]]:
    frames, manifest = [], []
    for spec in specs:
        raw = _read_csv(spec, cache)
        required = {'calc_time', 'last_funding_rate'}
        if not required.issubset(raw.columns):
            raise ValueError(f'Unexpected funding schema: {spec.url}')
        index = pd.to_datetime(raw.calc_time, unit='ms', utc=True).dt.floor('h')
        series = pd.Series(raw.last_funding_rate.astype(float).to_numpy(), index=index)
        frames.append(series)
        metadata = ensure_archive(spec, cache)
        manifest.append({**metadata, 'rows': len(series)})
    start, end = _utc(start), _utc(end)
    rates = pd.concat(frames).sort_index()
    rates = rates.loc[(rates.index >= start) & (rates.index < end)]
    if rates.empty or rates.index.has_duplicates or not np.isfinite(rates).all():
        raise ValueError('Invalid funding history')
    return rates.astype(float), manifest


def load_fcm_archives(symbol, spot_start, market_start, end, cache):
    """Load verified spot/perp/mark/funding data without touching the network."""
    spot_specs = [archive_spec(symbol, month, 'spot') for month in _months(spot_start, end)]
    market_months = _months(market_start, end)
    perp_specs = [archive_spec(symbol, month, 'perpetual') for month in market_months]
    mark_specs = [archive_spec(symbol, month, 'mark') for month in market_months]
    funding_specs = [archive_spec(symbol, month, 'funding') for month in market_months]
    spot, spot_manifest = _load_klines(
        spot_specs, cache, spot_start, end, allow_initial_listing_gap=True)
    perpetual, perp_manifest = _load_klines(perp_specs, cache, market_start, end)
    mark, mark_manifest = _load_klines(mark_specs, cache, market_start, end)
    funding, funding_manifest = _load_funding(
        funding_specs, cache, market_start, end)
    return {
        'spot': spot,
        'perpetual': perpetual,
        'mark': mark,
        'funding': funding,
    }, spot_manifest + perp_manifest + mark_manifest + funding_manifest


def load_fcm_minute_months(months_by_symbol: dict[str, set[str]], cache,
                           download_missing=False, workers=8):
    """Load complete verified 1m execution/risk series for active months only."""
    result, manifest = {}, {}
    stream_map = {
        'spot': 'spot_1m',
        'perpetual': 'perpetual_1m',
        'mark': 'mark_1m',
    }
    for symbol in sorted(months_by_symbol):
        result[symbol], manifest[symbol] = {}, []
        for output_stream, archive_stream in stream_map.items():
            frames = []
            for month in sorted(months_by_symbol[symbol]):
                period = pd.Period(month, freq='M')
                start = period.start_time.tz_localize('UTC')
                end = (period + 1).start_time.tz_localize('UTC')
                spec = archive_spec(symbol, month, archive_stream)
                frame, rows = _load_klines(
                    [spec], cache, start, end, require_full_range=False)
                expected = pd.date_range(
                    start, end, freq='1min', inclusive='left')
                missing = expected.difference(frame.index)
                if len(missing):
                    days = sorted({time.normalize() for time in missing})
                    daily_specs = [
                        daily_archive_spec(symbol, day, archive_stream)
                        for day in days
                    ]
                    prepare_archives(
                        daily_specs, cache,
                        download_missing=download_missing, workers=workers)
                    fallback_frames = []
                    for daily_spec, day in zip(daily_specs, days):
                        fallback, fallback_rows = _load_klines(
                            [daily_spec], cache, day,
                            day + pd.Timedelta(days=1))
                        fallback_frames.append(fallback.loc[
                            fallback.index.intersection(missing)])
                        rows.extend(fallback_rows)
                    frame = pd.concat([frame, *fallback_frames]).sort_index()
                remaining = expected.difference(frame.index)
                if output_stream == 'mark':
                    frame['risk_source'] = 'mark_1m'
                    if len(remaining):
                        hourly_spec = archive_spec(symbol, month, 'mark')
                        hourly, hourly_rows = _load_klines(
                            [hourly_spec], cache, start, end,
                            require_full_range=False)
                        rows.extend(hourly_rows)
                        for hour in sorted(set(remaining.floor('h'))):
                            if hour not in hourly.index:
                                raise ValueError(
                                    f'{symbol} {month} has no official mark '
                                    f'high envelope for {hour}')
                            audit_time = hour + pd.Timedelta(minutes=59)
                            high = float(hourly.at[hour, 'high'])
                            if audit_time in frame.index:
                                frame.at[audit_time, 'high'] = max(
                                    float(frame.at[audit_time, 'high']), high)
                                frame.at[audit_time, 'risk_source'] = (
                                    'mark_1m+hourly_high_envelope')
                            else:
                                frame.loc[audit_time, [
                                    'open', 'high', 'low', 'close', 'risk_source',
                                ]] = [high, high, high, high,
                                     'hourly_high_envelope']
                        frame = frame.sort_index()
                if frame.index.has_duplicates:
                    raise ValueError(
                        f'{symbol} {month} {archive_stream} lacks exact 1m data: '
                        f'{list(remaining[:5])}')
                frames.append(frame)
                manifest[symbol].extend(rows)
            result[symbol][output_stream] = pd.concat(frames).sort_index()
    return result, manifest
