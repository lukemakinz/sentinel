"""Checksum-verified public Binance USD-M inputs for S35 research.

This module reads Binance Data Vision monthly archives only.  It never uses an
API key, an account endpoint, the trading database, or a private application.
Every ZIP is verified against Binance's published ``.CHECKSUM`` sidecar by the
shared :mod:`backtest.funding_carry_data` archive layer.

The loader deliberately does *not* interpolate, forward-fill, resample, or
inner-join the price streams.  Missing 5-minute observations stay missing so
the S35 simulator can invalidate only the rolling window/event/position that
touches them.  Funding ``calc_time`` is retained in the checksum-pinned source
archive and any off-grid timestamp is conservatively mapped to the next 5m
boundary with ``ceil('5min')`` -- never to an earlier, non-causal boundary.

Public interface::

    markets, manifest = load_s35_universe(symbols, start, end, cache)

    markets[symbol] = {
        'perpetual': DataFrame(open, high, low, close, volume, quote_volume),
        'mark': DataFrame(open, high, low, close),
        'index': DataFrame(open, high, low, close),
        'funding': Series,  # realized rate indexed by causal settlement T
    }

All indexes are sorted, unique and UTC.  Requested ranges are half-open
``[start, end)`` and their boundaries must lie on the 5-minute grid.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.funding_carry_data import (
    ArchiveSpec,
    FUTURES_BASE,
    KLINE_COLUMNS,
    _read_csv,
    _timestamp_unit,
    _utc,
    prepare_archives,
)


INTERVAL = '5m'
FIVE_MINUTES = pd.Timedelta(minutes=5)
FIVE_MINUTES_MS = int(FIVE_MINUTES.total_seconds() * 1000)
SUPPORTED_SYMBOLS = (
    'ETHUSDT',
    'SOLUSDT',
    'XRPUSDT',
    'DOGEUSDT',
    'SUIUSDT',
)

# Launch instants are used to avoid requesting archives from months in which
# the contract did not exist.  ETH/XRP announcements identify the UTC launch
# date but not a minute; their first usable timestamp is therefore discovered
# from the checksum-verified archive.  The remaining announcements give the
# precise time.  In every case ``detected_available_from`` in the manifest is
# the actual first common public-data timestamp seen by the requested load.
LISTING_UTC = {
    'ETHUSDT': pd.Timestamp('2019-11-29 00:00:00Z'),
    'XRPUSDT': pd.Timestamp('2020-01-06 00:00:00Z'),
    'DOGEUSDT': pd.Timestamp('2020-07-10 09:00:00Z'),
    'SOLUSDT': pd.Timestamp('2020-09-14 07:00:00Z'),
    'SUIUSDT': pd.Timestamp('2023-05-03 16:00:00Z'),
}


@dataclass(frozen=True)
class StreamDefinition:
    stream: str
    directory: str
    output_name: str


STREAMS = {
    'perpetual': StreamDefinition('perpetual', 'klines', 'perpetual'),
    'mark': StreamDefinition('mark', 'markPriceKlines', 'mark'),
    'index': StreamDefinition('index', 'indexPriceKlines', 'index'),
    'funding': StreamDefinition('funding', 'fundingRate', 'funding'),
}


def _validate_request(symbol: str, start, end
                      ) -> tuple[str, pd.Timestamp, pd.Timestamp]:
    symbol = str(symbol).upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(
            f'Unsupported S35 symbol {symbol!r}; expected one of '
            + ', '.join(SUPPORTED_SYMBOLS))
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError('S35 range must have start before end')
    if start != start.floor('5min') or end != end.floor('5min'):
        raise ValueError('S35 range boundaries must be exact UTC 5m times')
    if end <= LISTING_UTC[symbol]:
        raise ValueError(
            f'{symbol} was not listed during the requested range')
    return symbol, start, end


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [
        str(month) for month in pd.period_range(
            start.tz_localize(None),
            (end - FIVE_MINUTES).tz_localize(None),
            freq='M',
        )
    ]


def s35_archive_spec(symbol: str, month: str, stream: str) -> ArchiveSpec:
    """Build a Binance Data Vision monthly archive specification."""
    if stream not in STREAMS:
        raise ValueError(f'Unknown S35 stream: {stream}')
    definition = STREAMS[stream]
    if stream == 'funding':
        leaf = f'{symbol}-fundingRate-{month}.zip'
        relative = f'fundingRate/{symbol}/{leaf}'
    else:
        leaf = f'{symbol}-{INTERVAL}-{month}.zip'
        relative = f'{definition.directory}/{symbol}/{INTERVAL}/{leaf}'
    # ``futures/`` is a local cache namespace.  The shared archive verifier
    # strips it when constructing the public Data Vision URL.
    return ArchiveSpec(
        symbol, month, stream, FUTURES_BASE, f'futures/{relative}')


def required_s35_archive_specs(symbol: str, start, end) -> list[ArchiveSpec]:
    """Return only post-listing archive months for one supported symbol."""
    symbol, start, end = _validate_request(symbol, start, end)
    archive_start = max(start, LISTING_UTC[symbol])
    months = _months(archive_start, end)
    return [
        s35_archive_spec(symbol, month, stream)
        for month in months
        for stream in STREAMS
    ]


def _validate_price_frame(frame: pd.DataFrame, stream: str) -> None:
    if frame.empty:
        raise ValueError(f'Empty Binance {stream} history')
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f'Duplicate or unsorted Binance {stream} timestamps')
    timestamps_ms = frame.index.astype('int64') // 1_000_000
    if (timestamps_ms % FIVE_MINUTES_MS).any():
        raise ValueError(f'Binance {stream} timestamps are not on the 5m grid')
    ohlc = frame[['open', 'high', 'low', 'close']]
    values = frame.to_numpy(dtype=float)
    if (not np.isfinite(values).all()
            or (ohlc <= 0).any().any()
            or (frame.high < frame[['open', 'close', 'low']].max(axis=1)).any()
            or (frame.low > frame[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError(f'Invalid Binance {stream} OHLC data')
    if stream == 'perpetual' and (
            (frame[['volume', 'quote_volume']] < 0).any().any()
            or not np.isfinite(frame[['volume', 'quote_volume']]
                               .to_numpy()).all()):
        raise ValueError('Invalid Binance perpetual volume')


def _coverage(frame: pd.DataFrame, start: pd.Timestamp,
              end: pd.Timestamp) -> dict:
    """Describe holes without manufacturing observations to fill them."""
    expected = pd.date_range(start, end, freq=FIVE_MINUTES, inclusive='left')
    missing = expected.difference(frame.index)
    return {
        'available_from': frame.index[0].isoformat(),
        'available_to_exclusive': (frame.index[-1] + FIVE_MINUTES).isoformat(),
        'rows': int(len(frame)),
        'expected_rows_from_first_observation': int(len(expected)),
        'missing_5m_bars_from_first_observation': int(len(missing)),
        'first_missing_5m': [timestamp.isoformat() for timestamp in missing[:20]],
        'missing_policy': 'preserved; never filled or interpolated',
    }


def _load_price_stream(specs: list[ArchiveSpec], cache,
                       start: pd.Timestamp, end: pd.Timestamp,
                       stream: str) -> tuple[pd.DataFrame, dict]:
    frames = []
    for spec in specs:
        raw = _read_csv(spec, cache)
        if len(raw.columns) != len(KLINE_COLUMNS):
            raise ValueError(f'Unexpected Binance {stream} kline schema')
        raw.columns = KLINE_COLUMNS
        raw['timestamp'] = pd.to_numeric(raw.timestamp, errors='coerce')
        raw = raw.loc[raw.timestamp.notna()].copy()
        raw.index = pd.to_datetime(
            raw.timestamp, unit=_timestamp_unit(raw.timestamp), utc=True)
        columns = ['open', 'high', 'low', 'close']
        if stream == 'perpetual':
            columns.extend(['volume', 'quote_volume'])
        frames.append(raw[columns].astype(float))
    if not frames:
        raise ValueError(f'No Binance {stream} archives selected')
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    _validate_price_frame(frame, stream)
    coverage_start = max(start, frame.index[0])
    return frame, _coverage(frame, coverage_start, end)


def _load_funding_stream(specs: list[ArchiveSpec], cache,
                         start: pd.Timestamp, end: pd.Timestamp
                         ) -> tuple[pd.Series, dict]:
    frames = []
    timestamp_adjustments = []
    for spec in specs:
        raw = _read_csv(spec, cache)
        required = {'calc_time', 'last_funding_rate'}
        if not required.issubset(raw.columns):
            raise ValueError('Unexpected Binance funding archive schema')
        numeric_time = pd.to_numeric(raw.calc_time, errors='raise')
        raw_index = pd.to_datetime(
            numeric_time, unit=_timestamp_unit(numeric_time), utc=True)
        # Ceil is causal: a payment recorded just after 08:00 cannot influence
        # the already-open 08:00 bar.  Flooring here would create lookahead.
        causal_index = pd.DatetimeIndex(raw_index).ceil('5min')
        for raw_time, causal_time in zip(raw_index, causal_index):
            if raw_time != causal_time:
                timestamp_adjustments.append({
                    'raw_calc_time': raw_time.isoformat(),
                    'causal_5m_time': causal_time.isoformat(),
                })
        frames.append(pd.Series(
            pd.to_numeric(raw.last_funding_rate, errors='raise').to_numpy(
                dtype=float),
            index=causal_index,
            dtype=float,
        ))
    rates = pd.concat(frames).sort_index() if frames else pd.Series(dtype=float)
    rates = rates.loc[(rates.index >= start) & (rates.index < end)]
    if rates.index.has_duplicates:
        raise ValueError('Duplicate Binance funding timestamp after causal ceil')
    if not rates.index.is_monotonic_increasing or not np.isfinite(rates).all():
        raise ValueError('Invalid Binance funding history')
    audit = {
        'rows': int(len(rates)),
        'raw_calc_time_retained_in_checksum_pinned_archives': True,
        'signal_timestamp_rule': "raw calc_time ceil('5min'); never floor",
        'adjusted_timestamp_count_all_loaded_months': len(timestamp_adjustments),
        'timestamp_adjustments_first_20': timestamp_adjustments[:20],
        'missing_policy': 'sparse realized settlements; never filled',
    }
    return rates, audit


def load_s35_symbol(symbol: str, start, end, cache,
                    download_missing: bool = False, workers: int = 8
                    ) -> tuple[dict, dict]:
    """Load one checksum-pinned S35 market without filling any time-series gap."""
    symbol, start, end = _validate_request(symbol, start, end)
    specs = required_s35_archive_specs(symbol, start, end)
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
        raise ValueError(f'{symbol} has no common S35 price observations')

    enriched_archives = []
    for spec, entry in zip(specs, archive_manifest):
        enriched_archives.append({
            **entry,
            'venue': 'binance',
            'symbol': symbol,
            'interval': None if spec.stream == 'funding' else INTERVAL,
            'relative_cache_path': spec.relative,
        })
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
    }


def load_s35_universe(symbols, start, end, cache,
                      download_missing: bool = False, workers: int = 8
                      ) -> tuple[dict, dict]:
    """Load the requested subset of the five frozen S35 USD-M markets.

    The output market dictionaries contain exactly ``perpetual``, ``mark``,
    ``index`` and ``funding``.  The companion manifest contains archive hashes,
    source coverage and the conservative funding timestamp audit.
    """
    normalized = tuple(str(symbol).upper() for symbol in symbols)
    if not normalized:
        raise ValueError('S35 universe must contain at least one symbol')
    if len(set(normalized)) != len(normalized):
        raise ValueError('S35 universe contains duplicate symbols')
    unsupported = [symbol for symbol in normalized
                   if symbol not in SUPPORTED_SYMBOLS]
    if unsupported:
        raise ValueError(
            'Unsupported S35 symbols: ' + ', '.join(unsupported))

    markets, symbol_manifests = {}, {}
    for symbol in normalized:
        markets[symbol], symbol_manifests[symbol] = load_s35_symbol(
            symbol, start, end, cache,
            download_missing=download_missing, workers=workers)
    return markets, {
        'source': 'anonymous public Binance Data Vision monthly archives',
        'interval': INTERVAL,
        'symbols': symbol_manifests,
        'no_api_key_or_account_data': True,
        'missing_policy': 'no interpolation, forward-fill or resampling',
    }
