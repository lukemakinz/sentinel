"""Downloads Binance USDT-M futures daily aggTrades archives with the
same checksum-verified pattern as scalp_data.archive(), for the M1
microstructure predictiveness screen. Separate from scalp_data.py since
aggTrades archives are daily (not monthly) and orders of magnitude more
granular -- not something the rest of this project's minute-bar pipeline
needs.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = 'https://data.binance.vision/data/futures/um/daily/aggTrades'
COLUMNS = ['agg_trade_id', 'price', 'quantity', 'first_trade_id', 'last_trade_id',
           'transact_time', 'is_buyer_maker']


def load_agg_trades_day(symbol: str, day: str, cache: str) -> pd.DataFrame:
    """`day`: 'YYYY-MM-DD'. Returns a DataFrame indexed by UTC timestamp
    (transact_time), columns price, quantity, is_buyer_maker."""
    relative = f'{symbol}/{symbol}-aggTrades-{day}.zip'
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
        if sha256(response.content).hexdigest() != checksum.text.split()[0]:
            raise ValueError(f'Archive checksum mismatch: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        checksum_path.write_text(checksum.text)
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != checksum_path.read_text().split()[0]:
        raise ValueError(f'Cached archive checksum mismatch: {path}')
    with ZipFile(BytesIO(payload)) as zipped:
        with zipped.open(zipped.namelist()[0]) as source:
            frame = pd.read_csv(source, header=0, names=COLUMNS)
    frame.index = pd.to_datetime(frame.transact_time, unit='ms', utc=True)
    return frame[['price', 'quantity', 'is_buyer_maker']].astype(
        {'price': float, 'quantity': float, 'is_buyer_maker': bool})
