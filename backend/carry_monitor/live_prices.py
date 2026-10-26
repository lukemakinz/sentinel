"""Public, unauthenticated Binance REST calls for the SAFE25 paper carry
monitor. No API key, no order placement — read-only market data only."""
from datetime import datetime, timezone

import pandas as pd
import requests

SPOT_URL = 'https://api.binance.com/api/v3/ticker/price'
SPOT_KLINES_URL = 'https://api.binance.com/api/v3/klines'
FUTURES_MARK_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'
FUTURES_PRICE_URL = 'https://fapi.binance.com/fapi/v1/ticker/price'
FUTURES_MARK_KLINES_URL = 'https://fapi.binance.com/fapi/v1/markPriceKlines'
FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/fundingRate'
TIMEOUT_SECONDS = 10


def get_spot_price(symbol: str) -> float:
    response = requests.get(SPOT_URL, params={'symbol': symbol}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    price = float(response.json()['price'])
    if price <= 0:
        raise ValueError(f'Invalid spot price for {symbol}: {price}')
    return price


def get_perp_mark_price(symbol: str) -> float:
    response = requests.get(FUTURES_MARK_URL, params={'symbol': symbol}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    price = float(response.json()['markPrice'])
    if price <= 0:
        raise ValueError(f'Invalid mark price for {symbol}: {price}')
    return price


def get_perp_price(symbol: str) -> float:
    response = requests.get(
        FUTURES_PRICE_URL, params={'symbol': symbol}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    price = float(response.json()['price'])
    if price <= 0:
        raise ValueError(f'Invalid perpetual price for {symbol}: {price}')
    return price


def get_completed_daily_spot_closes(symbol: str, end: datetime,
                                    limit=200) -> pd.DataFrame:
    """Completed daily spot closes strictly before ``end``."""
    response = requests.get(SPOT_KLINES_URL, params={
        'symbol': symbol,
        'interval': '1d',
        'endTime': int(end.timestamp() * 1000) - 1,
        'limit': limit,
    }, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    rows = response.json()
    index = pd.to_datetime([row[0] for row in rows], unit='ms', utc=True)
    frame = pd.DataFrame(
        {'close': [float(row[4]) for row in rows]}, index=index)
    if frame.empty or frame.index.has_duplicates or (frame.close <= 0).any():
        raise ValueError(f'Invalid daily spot history for {symbol}')
    return frame.sort_index()


def get_last_closed_mark_high(symbol: str, now: datetime) -> tuple[datetime, float]:
    """Return the latest fully closed real 1m mark bar, never the live bar."""
    response = requests.get(FUTURES_MARK_KLINES_URL, params={
        'symbol': symbol,
        'interval': '1m',
        'endTime': int(now.timestamp() * 1000) - 1,
        'limit': 2,
    }, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    completed = [row for row in response.json() if row[6] < int(now.timestamp() * 1000)]
    if not completed:
        raise ValueError(f'No completed mark minute for {symbol}')
    row = completed[-1]
    high = float(row[2])
    if high <= 0:
        raise ValueError(f'Invalid mark high for {symbol}: {high}')
    return datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc), high


def get_funding_settlements(symbol: str, start: datetime, end: datetime) -> list[dict]:
    """Raw funding settlements in [start, end): each {'time', 'rate', 'mark_price'}."""
    response = requests.get(FUTURES_FUNDING_URL, params={
        'symbol': symbol,
        'startTime': int(start.timestamp() * 1000),
        'endTime': int(end.timestamp() * 1000),
        'limit': 1000,
    }, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return [
        {
            'time': datetime.fromtimestamp(row['fundingTime'] / 1000, tz=timezone.utc),
            'rate': float(row['fundingRate']),
            'mark_price': float(row['markPrice']),
        }
        for row in response.json()
    ]


def funding_score_bps(symbol: str, start: datetime, end: datetime) -> float:
    """Sum of funding rate paid by longs to shorts over [start, end), in bps —
    the exact quantity S11's frozen rule (backtest.funding_carry) ranks on."""
    return sum(row['rate'] for row in get_funding_settlements(symbol, start, end)) * 10_000
