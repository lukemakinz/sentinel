"""Checksum-verified public Binance USD-M inputs for S36 research.

S36 deliberately reuses the exact archive specifications, checksum verifier,
listing dates, missing-data policy and causal funding timestamps frozen for
S35.  Its only extension is to retain the public perpetual-kline trade-flow
fields needed by the S36 deterministic classifier::

    num_trades, taker_buy_volume, taker_buy_quote_volume

No account endpoint, API key, private database, interpolation, resampling or
forward-fill is used.  Requested intervals are half-open ``[start, end)``.
"""

import numpy as np
import pandas as pd

from backtest.funding_carry_data import (
    KLINE_COLUMNS,
    _read_csv,
    _timestamp_unit,
    prepare_archives,
)
from backtest.s35_data import (
    FIVE_MINUTES,
    FIVE_MINUTES_MS,
    INTERVAL,
    LISTING_UTC,
    STREAMS,
    SUPPORTED_SYMBOLS,
    _coverage,
    _load_funding_stream,
    _validate_request,
    required_s35_archive_specs,
    s35_archive_spec,
)


OHLC_COLUMNS = ('open', 'high', 'low', 'close')
PERPETUAL_COLUMNS = (
    *OHLC_COLUMNS,
    'volume',
    'quote_volume',
    'num_trades',
    'taker_buy_volume',
    'taker_buy_quote_volume',
)


def s36_archive_spec(symbol: str, month: str, stream: str):
    """Return the exact checksum-pinned archive specification used by S35."""
    return s35_archive_spec(symbol, month, stream)


def required_s36_archive_specs(symbol: str, start, end):
    """Return the exact post-listing archive set used by the S35 data layer."""
    return required_s35_archive_specs(symbol, start, end)


def _validate_price_frame(frame: pd.DataFrame, stream: str) -> None:
    expected = set(PERPETUAL_COLUMNS if stream == 'perpetual'
                   else OHLC_COLUMNS)
    if stream not in ('perpetual', 'mark', 'index'):
        raise ValueError(f'Unknown S36 price stream: {stream}')
    if frame.empty or set(frame.columns) != expected:
        raise ValueError(f'Invalid Binance S36 {stream} schema')
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f'Duplicate or unsorted Binance S36 {stream} timestamps')
    timestamps_ms = frame.index.astype('int64') // 1_000_000
    if frame.index.tz is None or (timestamps_ms % FIVE_MINUTES_MS).any():
        raise ValueError(f'Binance S36 {stream} timestamps are not UTC 5m bars')

    ohlc = frame[list(OHLC_COLUMNS)]
    if (not np.isfinite(ohlc.to_numpy(dtype=float)).all()
            or (ohlc <= 0).any().any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError(f'Invalid Binance S36 {stream} OHLC data')

    if stream != 'perpetual':
        return
    flow_columns = [
        'volume', 'quote_volume', 'num_trades',
        'taker_buy_volume', 'taker_buy_quote_volume',
    ]
    flow = frame[flow_columns].to_numpy(dtype=float)
    if not np.isfinite(flow).all() or (flow < 0).any():
        raise ValueError('Invalid Binance S36 perpetual trade-flow data')
    trades = frame.num_trades.to_numpy(dtype=float)
    if not np.equal(trades, np.floor(trades)).all():
        raise ValueError('Binance S36 num_trades must be non-negative integers')
    tolerance = 1e-9
    if ((frame.taker_buy_volume > frame.volume + tolerance).any()
            or (frame.taker_buy_quote_volume
                > frame.quote_volume + tolerance).any()):
        raise ValueError('Binance S36 taker-buy volume exceeds total volume')


def _load_price_stream(specs, cache, start: pd.Timestamp, end: pd.Timestamp,
                       stream: str) -> tuple[pd.DataFrame, dict]:
    """Load raw S35 kline archives while retaining S36 trade-flow columns."""
    if stream not in ('perpetual', 'mark', 'index'):
        raise ValueError(f'Unknown S36 price stream: {stream}')
    columns = list(PERPETUAL_COLUMNS if stream == 'perpetual'
                   else OHLC_COLUMNS)
    frames = []
    for spec in specs:
        raw = _read_csv(spec, cache)
        if len(raw.columns) != len(KLINE_COLUMNS):
            raise ValueError(f'Unexpected Binance S36 {stream} kline schema')
        raw.columns = KLINE_COLUMNS
        raw['timestamp'] = pd.to_numeric(raw.timestamp, errors='coerce')
        raw = raw.loc[raw.timestamp.notna()].copy()
        raw.index = pd.to_datetime(
            raw.timestamp, unit=_timestamp_unit(raw.timestamp), utc=True)
        frame = raw[columns].apply(pd.to_numeric, errors='raise')
        frames.append(frame.astype(float))
    if not frames:
        raise ValueError(f'No Binance S36 {stream} archives selected')
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)].copy()
    _validate_price_frame(frame, stream)
    if stream == 'perpetual':
        # Preserve the semantic type after validating exact integrality.
        frame['num_trades'] = frame.num_trades.astype(np.int64)
    coverage_start = max(start, frame.index[0])
    return frame, _coverage(frame, coverage_start, end)


def load_s36_symbol(symbol: str, start, end, cache,
                    download_missing: bool = False, workers: int = 8
                    ) -> tuple[dict, dict]:
    """Load one S36 symbol from the checksum-verified S35 archive namespace."""
    symbol, start, end = _validate_request(symbol, start, end)
    specs = required_s36_archive_specs(symbol, start, end)
    archive_manifest = prepare_archives(
        specs, cache, download_missing=download_missing, workers=workers)
    specs_by_stream = {
        stream: [spec for spec in specs if spec.stream == stream]
        for stream in STREAMS
    }
    actual_start = max(start, LISTING_UTC[symbol])
    market, coverage = {}, {}
    for stream in ('perpetual', 'mark', 'index'):
        market[stream], coverage[stream] = _load_price_stream(
            specs_by_stream[stream], cache, actual_start, end, stream)
    market['funding'], coverage['funding'] = _load_funding_stream(
        specs_by_stream['funding'], cache, actual_start, end)

    common = (market['perpetual'].index
              .intersection(market['mark'].index)
              .intersection(market['index'].index))
    if common.empty:
        raise ValueError(f'{symbol} has no common S36 price observations')

    enriched_archives = [{
        **entry,
        'venue': 'binance',
        'symbol': symbol,
        'interval': None if spec.stream == 'funding' else INTERVAL,
        'relative_cache_path': spec.relative,
    } for spec, entry in zip(specs, archive_manifest)]
    return market, {
        'venue': 'binance',
        'symbol': symbol,
        'requested_start': start.isoformat(),
        'requested_end_exclusive': end.isoformat(),
        'configured_listing_utc': LISTING_UTC[symbol].isoformat(),
        'detected_common_available_from': common[0].isoformat(),
        'detected_common_available_to_exclusive': (
            common[-1] + FIVE_MINUTES).isoformat(),
        'coverage': coverage,
        'archives': enriched_archives,
        'perpetual_columns': list(PERPETUAL_COLUMNS),
        'order_flow_proxy': (
            '(2 * taker_buy_quote_volume - quote_volume) / quote_volume'),
    }


def load_s36_universe(symbols, start, end, cache,
                      download_missing: bool = False, workers: int = 8
                      ) -> tuple[dict, dict]:
    """Load the frozen five-symbol S36 public market-data contract."""
    normalized = tuple(str(symbol).upper() for symbol in symbols)
    if not normalized:
        raise ValueError('S36 universe must contain at least one symbol')
    if len(set(normalized)) != len(normalized):
        raise ValueError('S36 universe contains duplicate symbols')
    unsupported = [symbol for symbol in normalized
                   if symbol not in SUPPORTED_SYMBOLS]
    if unsupported:
        raise ValueError(
            'Unsupported S36 symbols: ' + ', '.join(unsupported))

    markets, symbol_manifests = {}, {}
    for symbol in normalized:
        markets[symbol], symbol_manifests[symbol] = load_s36_symbol(
            symbol, start, end, cache,
            download_missing=download_missing, workers=workers)
    return markets, {
        'source': 'anonymous public Binance Data Vision monthly archives',
        'archive_contract': 'exact checksum-verified S35 cache namespace',
        'interval': INTERVAL,
        'symbols': symbol_manifests,
        'no_api_key_or_account_data': True,
        'missing_policy': 'no interpolation, forward-fill or resampling',
        'perpetual_columns': list(PERPETUAL_COLUMNS),
        'order_flow_proxy': (
            '(2 * taker_buy_quote_volume - quote_volume) / quote_volume'),
    }
