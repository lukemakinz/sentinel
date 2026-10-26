"""Verified anonymous Binance inputs for S34 inverse COIN-M carry."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import requests

from backtest.dated_carry_data import (
    HOUR_MS,
    PAGE_LIMIT,
    _canonical_json,
    _load_spot_archives,
    _parse_hourly_ohlc,
    _request_json,
    _row_timestamp,
    _utc,
)


DAPI_BASE_URL = 'https://dapi.binance.com'
ENDPOINT = '/dapi/v1/continuousKlines'
CONTRACT_TYPE = 'CURRENT_QUARTER'
INTERVAL = '1h'
PAIR_BY_SPOT = {'BTCUSDT': 'BTCUSD', 'ETHUSDT': 'ETHUSD'}
RESEARCH_START = pd.Timestamp('2023-01-01 00:00:00Z')
RESEARCH_END = pd.Timestamp('2026-09-01 00:00:00Z')


def _validated_range(symbol, start, end):
    symbol = str(symbol).upper()
    if symbol not in PAIR_BY_SPOT:
        raise ValueError(f'Unsupported S34 symbol {symbol!r}')
    start, end = _utc(start), _utc(end)
    if start >= end or start != start.floor('h') or end != end.floor('h'):
        raise ValueError('S34 range must use ordered exact UTC hours')
    if start < RESEARCH_START or end > RESEARCH_END:
        raise ValueError(
            f'S34 range must stay within {RESEARCH_START}..{RESEARCH_END}')
    return symbol, start, end


def _milliseconds(timestamp):
    return int(timestamp.timestamp() * 1000)


def _fetch_rows(pair, start, end, session):
    """Page forward without invoking the API's 200-day response ambiguity."""
    cursor, end_ms = _milliseconds(start), _milliseconds(end)
    rows = []
    url = f'{DAPI_BASE_URL}{ENDPOINT}'
    while cursor < end_ms:
        page_end = min(end_ms - 1, cursor + PAGE_LIMIT * HOUR_MS - 1)
        page = _request_json(session, url, {
            'pair': pair,
            'contractType': CONTRACT_TYPE,
            'interval': INTERVAL,
            'startTime': cursor,
            'endTime': page_end,
            'limit': PAGE_LIMIT,
        })
        if not page:
            break
        timestamps = [_row_timestamp(row) for row in page]
        if min(timestamps) < cursor or max(timestamps) > page_end:
            raise ValueError('Binance COIN-M page exceeded requested bounds')
        rows.extend(page)
        next_cursor = max(timestamps) + HOUR_MS
        if next_cursor <= cursor:
            raise ValueError('Binance COIN-M pagination did not advance')
        cursor = next_cursor
    return sorted(
        (row for row in rows
         if _milliseconds(start) <= _row_timestamp(row) < end_ms),
        key=_row_timestamp,
    )


def _cache_path(cache, pair, start, end):
    return (Path(cache) / 'binance' / 'dapi' / 'v1' / 'continuousKlines'
            / pair / CONTRACT_TYPE / INTERVAL
            / f'{_milliseconds(start)}-{_milliseconds(end)}.json')


def _load_coin_m(symbol, start, end, cache, download_missing, session):
    pair = PAIR_BY_SPOT[symbol]
    path = _cache_path(cache, pair, start, end)
    if not path.exists():
        if not download_missing:
            raise FileNotFoundError(f'Binance COIN-M cache missing: {path}')
        rows = _fetch_rows(pair, start, end, session)
        document = {
            'schema_version': 1,
            'venue': 'binance',
            'market': 'coin_m',
            'endpoint': ENDPOINT,
            'pair': pair,
            'contract_type': CONTRACT_TYPE,
            'interval': INTERVAL,
            'start_ms': _milliseconds(start),
            'end_ms_exclusive': _milliseconds(end),
            'rows': rows,
        }
        payload = _canonical_json(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_bytes(payload)
        temporary.replace(path)

    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid Binance COIN-M cache JSON: {path}') from error
    expected_metadata = {
        'schema_version': 1,
        'venue': 'binance',
        'market': 'coin_m',
        'endpoint': ENDPOINT,
        'pair': pair,
        'contract_type': CONTRACT_TYPE,
        'interval': INTERVAL,
        'start_ms': _milliseconds(start),
        'end_ms_exclusive': _milliseconds(end),
    }
    if any(document.get(key) != value
           for key, value in expected_metadata.items()):
        raise ValueError(f'Binance COIN-M cache metadata mismatch: {path}')
    rows = document.get('rows')
    if not isinstance(rows, list):
        raise ValueError(f'Binance COIN-M cache rows missing: {path}')
    frame = _parse_hourly_ohlc(rows, start, end)
    return frame, [{
        'venue': 'binance',
        'market': 'coin_m',
        'pair': pair,
        'stream': 'current_quarter_h1',
        'cache_path': str(path),
        'sha256': sha256(payload).hexdigest(),
        'rows': len(rows),
        'start': str(start),
        'end_exclusive': str(end),
    }]


def load_coin_dated_carry_market(symbol, start, end, cache,
                                  download_missing=False, session=None,
                                  binance_cache=None,
                                  download_spot_missing=False):
    symbol, start, end = _validated_range(symbol, start, end)
    session = session or requests.Session()
    spot_cache = cache if binance_cache is None else binance_cache
    spot, spot_manifest = _load_spot_archives(
        symbol, start, end, spot_cache, download_spot_missing)
    futures, futures_manifest = _load_coin_m(
        symbol, start, end, cache, download_missing, session)
    return {'spot': spot, 'current_quarter': futures}, (
        spot_manifest + futures_manifest)
