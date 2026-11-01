"""Point-in-time Binance USD-M altcoin universe and gap-tolerant minute loading.

The candidate list comes from the public archive bucket, which keeps delisted
symbols, so selection is not limited to coins that survived. Ranking uses only
daily klines published before the selection date.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

import pandas as pd
import requests

from .scalp_data import (
    BASE_URL,
    COLUMNS,
    MarketDataIntegrityError,
    _daily_kline_archive,
    _repair_missing_minutes,
    archive,
    validate_minutes,
)

BUCKET = 'https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
NON_ALT_BASES = {'BTC', 'ETH', 'USDC', 'FDUSD', 'TUSD', 'BUSD', 'USDP', 'DAI', 'PAXG', 'XAUT'}
INDEX_SYMBOLS = {'BTCDOMUSDT', 'DEFIUSDT', 'FOOTBALLUSDT', 'BLUEBIRDUSDT'}
S113_SYMBOLS = {'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT',
                'AVAXUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT', 'DOTUSDT'}


def list_usdt_perpetuals(session=None) -> list[str]:
    """Every USDT-margined symbol that has (or had) monthly kline archives."""
    session = session or requests.Session()
    symbols, marker = [], ''
    while True:
        text = session.get(BUCKET, params={'prefix': 'data/futures/um/monthly/klines/',
                                           'delimiter': '/', 'marker': marker}, timeout=30).text
        symbols += re.findall(r'<Prefix>data/futures/um/monthly/klines/([^/<]+)/</Prefix>', text)
        if '<IsTruncated>true</IsTruncated>' not in text:
            break
        marker = re.findall(r'<NextMarker>([^<]+)</NextMarker>', text)[-1]
    return sorted(s for s in symbols if s.endswith('USDT') and '_' not in s)


def daily_klines(symbol: str, month: str, cache: str) -> pd.DataFrame | None:
    """Checksumed monthly 1d klines; None when the symbol had no archive that month."""
    relative = f'klines/{symbol}/1d/{symbol}-1d-{month}.zip'
    path = Path(cache) / 'daily_bars' / relative
    checksum_path = path.with_suffix('.zip.CHECKSUM')
    if not path.exists() or not checksum_path.exists():
        response = requests.get(f'{BASE_URL}/{relative}', timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        checksum = requests.get(f'{BASE_URL}/{relative}.CHECKSUM', timeout=30)
        checksum.raise_for_status()
        if sha256(response.content).hexdigest() != checksum.text.split()[0]:
            raise ValueError(f'Checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    with ZipFile(BytesIO(path.read_bytes())) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            raw = pd.read_csv(source, header=None)
    if not str(raw.iloc[0, 0]).isdigit():  # some archives carry a header row
        raw = raw.iloc[1:]
    raw = raw.iloc[:, :len(COLUMNS)]
    raw.columns = COLUMNS
    raw.index = pd.to_datetime(raw.timestamp.astype('int64'), unit='ms', utc=True)
    return raw.astype({'quote_volume': float})


def select_universe(cache: str, size: int = 48, rank_month: str = '2025-04',
                    eligibility_month: str = '2025-03',
                    listed_by: str = '2025-03-17') -> dict:
    """Top ``size`` alts by median daily quote volume in ``rank_month``."""
    candidates = [s for s in list_usdt_perpetuals()
                  if s not in S113_SYMBOLS and s not in INDEX_SYMBOLS
                  and s[:-4] not in NON_ALT_BASES]

    def score(symbol):
        early = daily_klines(symbol, eligibility_month, cache)
        if early is None or early.index[0] > pd.Timestamp(listed_by, tz='UTC'):
            return symbol, None, 'listed_too_late'
        april = daily_klines(symbol, rank_month, cache)
        if april is None or len(april) < 20:
            return symbol, None, 'no_rank_month_data'
        return symbol, float(april.quote_volume.median()), 'ok'

    with ThreadPoolExecutor(max_workers=16) as pool:
        scored = list(pool.map(score, candidates))
    eligible = sorted((s for s in scored if s[1] is not None), key=lambda s: -s[1])
    chosen = eligible[:size]
    tier = lambda v: 'tier_1' if v >= 100e6 else 'tier_2' if v >= 20e6 else 'tier_3'  # noqa: E731
    return {
        'candidates': len(candidates),
        'eligible': len(eligible),
        'rejected': {reason: sum(1 for s in scored if s[2] == reason)
                     for reason in ('listed_too_late', 'no_rank_month_data')},
        'symbols': {s: {'median_quote_volume_usd': v, 'tier': tier(v)} for s, v, _ in chosen},
    }


def load_available_minutes(symbol: str, start, end, cache: str) -> tuple:
    """Continuous minutes from ``start`` until the data ends (delisting-aware)."""
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    candles, funding, manifest = [], [], []
    for month in pd.period_range(start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None), freq='M'):
        try:
            raw, entry = archive(symbol, str(month), 'klines', cache)
        except requests.HTTPError:
            if candles:
                break  # delisted: the archive simply stops
            raise MarketDataIntegrityError(f'{symbol}: no archive for {month}')
        if not str(raw.iloc[0, 0]).isdigit():
            raw = raw.iloc[1:]
        raw = raw.iloc[:, :len(COLUMNS)]
        raw.columns = COLUMNS
        raw.index = pd.to_datetime(raw.timestamp.astype('int64'), unit='ms', utc=True)
        candles.append(raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float))
        manifest.append(entry)
        try:
            rates, entry = archive(symbol, str(month), 'fundingRate', cache)
            rates.index = pd.to_datetime(rates.calc_time, unit='ms', utc=True).dt.floor('min')
            funding.append(rates.last_funding_rate.astype(float))
            manifest.append(entry)
        except requests.HTTPError:
            pass
    frame = pd.concat(candles).sort_index()
    frame = frame.loc[~frame.index.duplicated(keep='first')]
    frame = frame.loc[(frame.index >= start) & (frame.index < end)]
    # A halted contract can keep publishing flat zero-volume candles; a
    # trailing run of >= 24h without trades is treated as the end of trading.
    traded = frame.index[frame.volume > 0]
    if len(traded) and frame.index[-1] - traded[-1] >= pd.Timedelta(hours=24):
        frame = frame.loc[frame.index <= traded[-1]]
    data_end = frame.index[-1] + pd.Timedelta(minutes=1)
    frame, repairs = _repair_missing_minutes(
        frame, start, data_end, lambda day: _daily_kline_archive(symbol, day, cache))
    manifest.extend(repairs)
    validate_minutes(frame)
    rates = pd.concat(funding).sort_index() if funding else pd.Series(dtype=float)
    rates = rates.loc[~rates.index.duplicated(keep='first')]
    return frame, rates, data_end, manifest
