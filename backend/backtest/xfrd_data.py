"""Public cross-exchange funding data for the S32 XFRD research.

The Bybit side uses anonymous V5 market-data endpoints only.  Responses are
cached as deterministic JSON documents so an experiment can be repeated
offline and every input can be pinned in a SHA256 manifest.  The Binance side
is intentionally delegated to :mod:`backtest.funding_carry_data`, whose ZIP
archives are verified against Binance's published checksums.

Official Bybit API references:
https://bybit-exchange.github.io/docs/v5/market/kline
https://bybit-exchange.github.io/docs/v5/market/mark-kline
https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
import requests

from backtest.funding_carry_data import (
    load_fcm_archives,
    load_hour_fallback,
    missing_hour_archive_specs,
)


BYBIT_BASE_URL = 'https://api.bybit.com'
SUPPORTED_SYMBOLS = frozenset({'ETHUSDT', 'SOLUSDT'})
HOUR_MS = 60 * 60 * 1000
CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BybitStreamSpec:
    stream: str
    endpoint: str
    limit: int
    timestamp_parameter: str

    def parameters(self, symbol: str, start_ms: int, end_ms: int) -> dict:
        params = {
            'category': 'linear',
            'symbol': symbol,
            'limit': self.limit,
        }
        if self.stream == 'funding':
            # Bybit rejects startTime without endTime, hence both are always
            # supplied.  ``end_ms`` is an inclusive pagination cursor.
            params.update(startTime=start_ms, endTime=end_ms)
        else:
            params.update(interval='60', start=start_ms, end=end_ms)
        return params


BYBIT_STREAMS = {
    'trade': BybitStreamSpec('trade', '/v5/market/kline', 1000, 'startTime'),
    'mark': BybitStreamSpec(
        'mark', '/v5/market/mark-price-kline', 1000, 'startTime'),
    'funding': BybitStreamSpec(
        'funding', '/v5/market/funding/history', 200,
        'fundingRateTimestamp'),
}


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return (timestamp.tz_localize('UTC') if timestamp.tzinfo is None
            else timestamp.tz_convert('UTC'))


def _validated_range(symbol: str, start, end) -> tuple[str, pd.Timestamp, pd.Timestamp]:
    symbol = str(symbol).upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(
            f'Unsupported XFRD symbol {symbol!r}; expected ETHUSDT or SOLUSDT')
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError('XFRD range must have start before end')
    if start != start.floor('h') or end != end.floor('h'):
        raise ValueError('XFRD range boundaries must be exact UTC hours')
    return symbol, start, end


def _milliseconds(timestamp: pd.Timestamp) -> int:
    return int(timestamp.timestamp() * 1000)


def _row_timestamp(row: Any, spec: BybitStreamSpec) -> int:
    try:
        value = (row[0] if spec.stream != 'funding'
                 else row[spec.timestamp_parameter])
        timestamp = int(value)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f'Invalid Bybit {spec.stream} timestamp row') from error
    if timestamp <= 0:
        raise ValueError(f'Invalid Bybit {spec.stream} timestamp')
    return timestamp


def _request_json(session, url: str, params: dict, retries: int = 4,
                  backoff_seconds: float = .25) -> dict:
    """Request one anonymous page, retrying transport/HTTP failures."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('Bybit returned a non-object JSON response')
            if payload.get('retCode') != 0:
                raise ValueError(
                    f"Bybit API error {payload.get('retCode')}: "
                    f"{payload.get('retMsg', '')}")
            result = payload.get('result')
            if not isinstance(result, dict) or not isinstance(result.get('list'), list):
                raise ValueError('Bybit response is missing result.list')
            return payload
        except (requests.RequestException, json.JSONDecodeError) as error:
            last_error = error
            if attempt == retries:
                break
            time.sleep(backoff_seconds * (2 ** attempt))
    raise RuntimeError(f'Bybit request failed after {retries + 1} attempts') from last_error


def _fetch_bybit_rows(spec: BybitStreamSpec, symbol: str,
                       start: pd.Timestamp, end: pd.Timestamp,
                       session) -> list:
    """Page backwards through one Bybit stream without using credentials."""
    start_ms, end_ms = _milliseconds(start), _milliseconds(end)
    cursor = end_ms - 1  # the public endpoint treats ``end`` as inclusive
    rows = []
    url = f'{BYBIT_BASE_URL}{spec.endpoint}'

    while cursor >= start_ms:
        payload = _request_json(
            session, url, spec.parameters(symbol, start_ms, cursor))
        page = payload['result']['list']
        if not page:
            break
        timestamps = [_row_timestamp(row, spec) for row in page]
        if max(timestamps) > cursor:
            raise ValueError(f'Bybit {spec.stream} page exceeded its end cursor')
        rows.extend(page)
        oldest = min(timestamps)
        if oldest <= start_ms:
            break
        next_cursor = oldest - 1
        if next_cursor >= cursor:
            raise ValueError(f'Bybit {spec.stream} pagination did not advance')
        cursor = next_cursor

    # Boundary filtering is defensive: the requested end is exclusive in the
    # research interface even though Bybit's pagination cursor is inclusive.
    return [row for row in rows
            if start_ms <= _row_timestamp(row, spec) < end_ms]


def _cache_path(cache, symbol: str, stream: str,
                start: pd.Timestamp, end: pd.Timestamp) -> Path:
    return (Path(cache) / 'bybit' / 'v5' / symbol / stream
            / f'{_milliseconds(start)}-{_milliseconds(end)}.json')


def _cache_document(spec: BybitStreamSpec, symbol: str,
                    start: pd.Timestamp, end: pd.Timestamp, rows: list) -> dict:
    return {
        'schema_version': CACHE_SCHEMA_VERSION,
        'venue': 'bybit',
        'stream': spec.stream,
        'symbol': symbol,
        'category': 'linear',
        'interval': '60' if spec.stream != 'funding' else None,
        'start_ms': _milliseconds(start),
        'end_ms_exclusive': _milliseconds(end),
        'endpoint': spec.endpoint,
        'rows': rows,
    }


def _canonical_json(document: dict) -> bytes:
    return (json.dumps(
        document, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')) + '\n').encode('utf-8')


def _read_or_fetch_cache(spec: BybitStreamSpec, symbol: str,
                         start: pd.Timestamp, end: pd.Timestamp, cache,
                         download_missing: bool, session) -> tuple[list, dict]:
    path = _cache_path(cache, symbol, spec.stream, start, end)
    if not path.exists():
        if not download_missing:
            raise FileNotFoundError(
                f'Bybit public cache missing in offline mode: {path}')
        rows = _fetch_bybit_rows(spec, symbol, start, end, session)
        document = _cache_document(spec, symbol, start, end, rows)
        payload = _canonical_json(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_bytes(payload)
        temporary.replace(path)

    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid Bybit cache JSON: {path}') from error
    if not isinstance(document, dict):
        raise ValueError(f'Invalid Bybit cache document: {path}')
    expected = _cache_document(spec, symbol, start, end, document.get('rows'))
    if document != expected or not isinstance(document.get('rows'), list):
        raise ValueError(f'Bybit cache scope/schema mismatch: {path}')

    return document['rows'], {
        'venue': 'bybit',
        'stream': spec.stream,
        'symbol': symbol,
        'url': f'{BYBIT_BASE_URL}{spec.endpoint}',
        'cache_path': str(path),
        'sha256': sha256(payload).hexdigest(),
        'bytes': len(payload),
        'rows': len(document['rows']),
    }


def _validate_unique_hourly_timestamps(timestamps: list[int], stream: str
                                       ) -> pd.DatetimeIndex:
    if not timestamps:
        raise ValueError(f'Empty Bybit {stream} history')
    if len(set(timestamps)) != len(timestamps):
        raise ValueError(f'Duplicate Bybit {stream} timestamps')
    index = pd.to_datetime(timestamps, unit='ms', utc=True)
    if any(timestamp % HOUR_MS for timestamp in timestamps):
        raise ValueError(f'Bybit {stream} timestamps are not aligned to UTC hours')
    return pd.DatetimeIndex(index)


def _parse_klines(rows: list, stream: str, start: pd.Timestamp,
                  end: pd.Timestamp) -> pd.DataFrame:
    timestamps, values = [], []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError(f'Invalid Bybit {stream} kline row')
        try:
            timestamps.append(int(row[0]))
            values.append([float(value) for value in row[1:5]])
        except (TypeError, ValueError) as error:
            raise ValueError(f'Invalid Bybit {stream} kline values') from error
    index = _validate_unique_hourly_timestamps(timestamps, stream)
    frame = pd.DataFrame(
        values, columns=['open', 'high', 'low', 'close'], index=index)
    frame = frame.sort_index()
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    if not frame.index.equals(expected):
        missing = expected.difference(frame.index)
        extra = frame.index.difference(expected)
        raise ValueError(
            f'Bybit {stream} does not exactly cover requested H1 range '
            f'(missing={len(missing)}, extra={len(extra)})')
    matrix = frame.to_numpy(dtype=float)
    if (not np.isfinite(matrix).all() or (matrix <= 0).any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError(f'Invalid Bybit {stream} OHLC data')
    return frame


def _parse_funding(rows: list, symbol: str, start: pd.Timestamp,
                   end: pd.Timestamp) -> pd.Series:
    timestamps, rates = [], []
    for row in rows:
        if not isinstance(row, dict) or row.get('symbol') != symbol:
            raise ValueError('Invalid Bybit funding row or symbol')
        try:
            timestamps.append(int(row['fundingRateTimestamp']))
            rates.append(float(row['fundingRate']))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Invalid Bybit funding values') from error
    index = _validate_unique_hourly_timestamps(timestamps, 'funding')
    series = pd.Series(rates, index=index, dtype=float).sort_index()
    if ((series.index < start).any() or (series.index >= end).any()):
        raise ValueError('Bybit funding timestamps fall outside requested range')
    if not series.index.is_monotonic_increasing or not np.isfinite(series).all():
        raise ValueError('Invalid or unsorted Bybit funding history')
    return series


def load_bybit_venue(symbol, start, end, cache, download_missing=False,
                      session=None) -> tuple[dict, list[dict]]:
    """Load Bybit linear-perpetual H1 trade/mark prices and funding.

    ``download_missing=False`` is deliberately the default: research replays
    are offline unless the caller explicitly opts into anonymous downloads.
    """
    symbol, start, end = _validated_range(symbol, start, end)
    session = session or requests.Session()
    rows, manifest = {}, []
    for stream, spec in BYBIT_STREAMS.items():
        rows[stream], entry = _read_or_fetch_cache(
            spec, symbol, start, end, cache, download_missing, session)
        manifest.append(entry)
    return {
        'trade': _parse_klines(rows['trade'], 'trade', start, end),
        'mark': _parse_klines(rows['mark'], 'mark', start, end),
        'funding': _parse_funding(rows['funding'], symbol, start, end),
    }, manifest


def load_binance_venue(symbol, start, end, cache) -> tuple[dict, list[dict]]:
    """Map the existing checksum-verified Binance loader to the XFRD shape."""
    symbol, start, end = _validated_range(symbol, start, end)
    data, source_manifest = load_fcm_archives(
        symbol, start, start, end, cache)
    stream_names = {
        'perpetual': 'trade',
        'mark': 'mark',
        'funding': 'funding',
    }
    manifest = [{
        **entry,
        'venue': 'binance',
        'source_stream': entry['stream'],
        'stream': stream_names[entry['stream']],
    } for entry in source_manifest if entry['stream'] in stream_names]
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    missing_mark = expected.difference(data['mark'].index)
    if len(missing_mark):
        specs = missing_hour_archive_specs(
            symbol, data['mark'], start, end, 'mark')
        fallback, fallback_manifest = load_hour_fallback(
            specs, cache, missing_mark, require_all=False)
        data['mark'] = pd.concat([data['mark'], fallback]).sort_index()
        manifest.extend({
            **entry, 'venue': 'binance', 'source_stream': entry['stream'],
            'stream': 'mark', 'exact_1m_fallback': True,
        } for entry in fallback_manifest)
        remaining = expected.difference(data['mark'].index)
        same_hour_trade = remaining.intersection(data['perpetual'].index)
        if len(same_hour_trade):
            data['mark'] = pd.concat([
                data['mark'], data['perpetual'].loc[same_hour_trade],
            ]).sort_index()
            manifest.append({
                'venue': 'binance', 'stream': 'mark',
                'source_stream': 'perpetual',
                'same_hour_mark_proxy': True,
                'selected_hour_rows': len(same_hour_trade),
                'reason': 'native H1 and exact 1m mark both absent',
            })
        unresolved = expected.difference(data['mark'].index)
        if len(unresolved):
            raise ValueError(
                'Unresolved Binance mark hours: '
                + ', '.join(map(str, unresolved[:10])))
    return {
        'trade': data['perpetual'],
        'mark': data['mark'],
        'funding': data['funding'],
    }, manifest


def load_xfrd_venues(symbol, start, end, cache, download_bybit=False,
                      bybit_session=None, binance_cache=None) -> tuple[dict, dict]:
    """Return comparable ``{trade, mark, funding}`` data for both venues."""
    binance, binance_manifest = load_binance_venue(
        symbol, start, end, binance_cache or cache)
    bybit, bybit_manifest = load_bybit_venue(
        symbol, start, end, cache, download_bybit, bybit_session)
    return {
        'binance': binance,
        'bybit': bybit,
    }, {
        'binance': binance_manifest,
        'bybit': bybit_manifest,
    }
