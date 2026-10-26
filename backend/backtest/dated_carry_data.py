"""Verified public Binance inputs for S33 dated cash-and-carry research.

The quarterly leg comes from Binance USD-M's anonymous ``continuousKlines``
endpoint.  Raw API rows are stored in canonical JSON so every research run can
pin the exact response with SHA256 and replay it without network access.  Spot
prices are loaded from :mod:`backtest.funding_carry_data`; those ZIP archives
are verified against Binance's published ``.CHECKSUM`` files.

The public API stream is a roll-adjusted ``CURRENT_QUARTER`` series.  Contract
selection and roll/expiry accounting belong to the strategy simulator, not to
this data-access module.
"""

from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests

from backtest.funding_carry_data import (
    _load_klines,
    _months,
    archive_spec,
    load_hour_fallback,
    missing_hour_archive_specs,
    prepare_archives,
)


BINANCE_FAPI_BASE_URL = 'https://fapi.binance.com'
CONTINUOUS_KLINES_ENDPOINT = '/fapi/v1/continuousKlines'
CONTRACT_TYPE = 'CURRENT_QUARTER'
INTERVAL = '1h'
PAGE_LIMIT = 1500
HOUR_MS = 60 * 60 * 1000
CACHE_SCHEMA_VERSION = 1
SUPPORTED_SYMBOLS = frozenset({'BTCUSDT', 'ETHUSDT'})
RESEARCH_START = pd.Timestamp('2023-01-01 00:00:00Z')
RESEARCH_END = pd.Timestamp('2026-09-01 00:00:00Z')


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return (timestamp.tz_localize('UTC') if timestamp.tzinfo is None
            else timestamp.tz_convert('UTC'))


def _validated_range(symbol: str, start, end
                     ) -> tuple[str, pd.Timestamp, pd.Timestamp]:
    symbol = str(symbol).upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(
            f'Unsupported S33 symbol {symbol!r}; expected BTCUSDT or ETHUSDT')
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError('S33 range must have start before end')
    if start != start.floor('h') or end != end.floor('h'):
        raise ValueError('S33 range boundaries must be exact UTC hours')
    if start < RESEARCH_START or end > RESEARCH_END:
        raise ValueError(
            f'S33 range must stay within {RESEARCH_START}..{RESEARCH_END}')
    return symbol, start, end


def _milliseconds(timestamp: pd.Timestamp) -> int:
    return int(timestamp.timestamp() * 1000)


def _request_json(session, url: str, params: dict, retries: int = 4,
                  backoff_seconds: float = .25) -> list:
    """Request one anonymous Binance page with bounded exponential retry."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                if isinstance(payload, dict) and 'code' in payload:
                    raise ValueError(
                        f"Binance API error {payload.get('code')}: "
                        f"{payload.get('msg', '')}")
                raise ValueError('Binance returned a non-array JSON response')
            return payload
        except (requests.RequestException, json.JSONDecodeError) as error:
            last_error = error
            if attempt == retries:
                break
            time.sleep(backoff_seconds * (2 ** attempt))
    raise RuntimeError(
        f'Binance request failed after {retries + 1} attempts') from last_error


def _row_timestamp(row) -> int:
    if not isinstance(row, (list, tuple)) or len(row) < 5:
        raise ValueError('Invalid Binance CURRENT_QUARTER kline row')
    try:
        timestamp = int(row[0])
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid Binance CURRENT_QUARTER timestamp') from error
    if timestamp <= 0:
        raise ValueError('Invalid Binance CURRENT_QUARTER timestamp')
    return timestamp


def _fetch_continuous_rows(symbol: str, start: pd.Timestamp,
                           end: pd.Timestamp, session) -> list:
    """Page forwards through Binance CURRENT_QUARTER H1 history."""
    start_ms, end_ms = _milliseconds(start), _milliseconds(end)
    cursor = start_ms
    rows = []
    url = f'{BINANCE_FAPI_BASE_URL}{CONTINUOUS_KLINES_ENDPOINT}'

    while cursor < end_ms:
        params = {
            'pair': symbol,
            'contractType': CONTRACT_TYPE,
            'interval': INTERVAL,
            'startTime': cursor,
            'endTime': end_ms - 1,
            'limit': PAGE_LIMIT,
        }
        page = _request_json(session, url, params)
        if not page:
            break
        timestamps = [_row_timestamp(row) for row in page]
        if min(timestamps) < cursor or max(timestamps) >= end_ms:
            raise ValueError(
                'Binance CURRENT_QUARTER page exceeded its requested bounds')
        rows.extend(page)
        next_cursor = max(timestamps) + HOUR_MS
        if next_cursor <= cursor:
            raise ValueError('Binance CURRENT_QUARTER pagination did not advance')
        cursor = next_cursor

    # Sorting makes the cached document independent of API page ordering.
    return sorted(
        (row for row in rows
         if start_ms <= _row_timestamp(row) < end_ms),
        key=_row_timestamp,
    )


def _cache_path(cache, symbol: str, start: pd.Timestamp,
                end: pd.Timestamp) -> Path:
    return (Path(cache) / 'binance' / 'fapi' / 'v1' / 'continuousKlines'
            / symbol / CONTRACT_TYPE / INTERVAL
            / f'{_milliseconds(start)}-{_milliseconds(end)}.json')


def _cache_document(symbol: str, start: pd.Timestamp,
                    end: pd.Timestamp, rows: list) -> dict:
    return {
        'schema_version': CACHE_SCHEMA_VERSION,
        'venue': 'binance',
        'endpoint': CONTINUOUS_KLINES_ENDPOINT,
        'pair': symbol,
        'contract_type': CONTRACT_TYPE,
        'interval': INTERVAL,
        'start_ms': _milliseconds(start),
        'end_ms_exclusive': _milliseconds(end),
        'rows': rows,
    }


def _canonical_json(document: dict) -> bytes:
    return (json.dumps(
        document, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')) + '\n').encode('utf-8')


def _read_or_fetch_cache(symbol: str, start: pd.Timestamp,
                         end: pd.Timestamp, cache, download_missing: bool,
                         session) -> tuple[list, dict]:
    path = _cache_path(cache, symbol, start, end)
    if not path.exists():
        if not download_missing:
            raise FileNotFoundError(
                f'Binance CURRENT_QUARTER cache missing in offline mode: {path}')
        rows = sorted(
            _fetch_continuous_rows(symbol, start, end, session),
            key=_row_timestamp,
        )
        document = _cache_document(symbol, start, end, rows)
        payload = _canonical_json(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_bytes(payload)
        temporary.replace(path)

    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid Binance cache JSON: {path}') from error
    if not isinstance(document, dict) or not isinstance(document.get('rows'), list):
        raise ValueError(f'Invalid Binance cache document: {path}')
    if document != _cache_document(symbol, start, end, document['rows']):
        raise ValueError(f'Binance cache scope/schema mismatch: {path}')
    if payload != _canonical_json(document):
        raise ValueError(f'Binance cache is not canonical JSON: {path}')

    return document['rows'], {
        'venue': 'binance',
        'stream': 'current_quarter',
        'symbol': symbol,
        'contract_type': CONTRACT_TYPE,
        'interval': INTERVAL,
        'url': f'{BINANCE_FAPI_BASE_URL}{CONTINUOUS_KLINES_ENDPOINT}',
        'cache_path': str(path),
        'sha256': sha256(payload).hexdigest(),
        'bytes': len(payload),
        'rows': len(document['rows']),
    }


def _parse_hourly_ohlc(rows: list, start: pd.Timestamp,
                       end: pd.Timestamp) -> pd.DataFrame:
    timestamps, values = [], []
    for row in rows:
        timestamp = _row_timestamp(row)
        try:
            values.append([float(value) for value in row[1:5]])
        except (TypeError, ValueError) as error:
            raise ValueError(
                'Invalid Binance CURRENT_QUARTER OHLC values') from error
        timestamps.append(timestamp)

    if not timestamps:
        raise ValueError('Empty Binance CURRENT_QUARTER history')
    if len(set(timestamps)) != len(timestamps):
        raise ValueError('Duplicate Binance CURRENT_QUARTER timestamps')
    if any(timestamp % HOUR_MS for timestamp in timestamps):
        raise ValueError(
            'Binance CURRENT_QUARTER timestamps are not aligned to UTC hours')

    frame = pd.DataFrame(
        values, columns=['open', 'high', 'low', 'close'],
        index=pd.to_datetime(timestamps, unit='ms', utc=True),
    ).sort_index()
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    if not frame.index.equals(expected):
        missing = expected.difference(frame.index)
        extra = frame.index.difference(expected)
        raise ValueError(
            'Binance CURRENT_QUARTER does not exactly cover requested H1 range '
            f'(missing={len(missing)}, extra={len(extra)})')

    matrix = frame.to_numpy(dtype=float)
    if (not np.isfinite(matrix).all() or (matrix <= 0).any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError('Invalid Binance CURRENT_QUARTER OHLC data')
    return frame


def load_current_quarter_klines(symbol, start, end, cache,
                                download_missing=False, session=None
                                ) -> tuple[pd.DataFrame, list[dict]]:
    """Load a complete Binance USD-M CURRENT_QUARTER H1 series.

    Network access is opt-in.  The returned manifest pins the canonical cache
    bytes with SHA256; subsequent calls can replay the same file offline.
    """
    symbol, start, end = _validated_range(symbol, start, end)
    session = session or requests.Session()
    rows, manifest = _read_or_fetch_cache(
        symbol, start, end, cache, download_missing, session)
    return _parse_hourly_ohlc(rows, start, end), [manifest]


def _load_spot_archives(symbol: str, start: pd.Timestamp, end: pd.Timestamp,
                        cache, download_missing: bool
                        ) -> tuple[pd.DataFrame, list[dict]]:
    specs = [archive_spec(symbol, month, 'spot')
             for month in _months(start, end)]
    if download_missing:
        prepare_archives(specs, cache, download_missing=True)
    frame, manifest = _load_klines(specs, cache, start, end)
    expected = pd.date_range(start, end, freq='1h', inclusive='left')
    missing = expected.difference(frame.index)
    if len(missing):
        fallback_specs = missing_hour_archive_specs(
            symbol, frame, start, end, 'spot')
        if download_missing:
            prepare_archives(
                fallback_specs, cache, download_missing=True)
        # A venue-wide spot halt can leave the exact H1 bar absent from both
        # the H1 and 1m archives.  Preserve that real non-tradable gap rather
        # than inventing a price.  The simulator separately requires every
        # feature/entry/exit timestamp and keeps evaluating futures collateral
        # during a missing spot mark.
        fallback, fallback_manifest = load_hour_fallback(
            fallback_specs, cache, missing, require_all=False)
        frame = pd.concat([frame, fallback]).sort_index()
        manifest.extend({
            **entry, 'exact_1m_fallback': True,
        } for entry in fallback_manifest)
    return frame, [{**entry, 'venue': 'binance'} for entry in manifest]


def load_dated_carry_market(symbol, start, end, cache,
                            download_missing=False, session=None,
                            binance_cache=None, download_spot_missing=False
                            ) -> tuple[dict, list[dict]]:
    """Return checksum-verified spot and cached CURRENT_QUARTER H1 prices.

    ``cache`` stores the deterministic API response.  ``binance_cache`` may
    point at an existing archive cache; if omitted, both sources use ``cache``.
    Spot archive downloading has a separate explicit switch because API-cache
    creation and checksum-verified ZIP acquisition are distinct operations.
    """
    symbol, start, end = _validated_range(symbol, start, end)
    spot_cache = cache if binance_cache is None else binance_cache
    spot, spot_manifest = _load_spot_archives(
        symbol, start, end, spot_cache, download_spot_missing)
    quarterly, quarterly_manifest = load_current_quarter_klines(
        symbol, start, end, cache, download_missing, session)
    return {
        'spot': spot,
        'current_quarter': quarterly,
    }, spot_manifest + quarterly_manifest
