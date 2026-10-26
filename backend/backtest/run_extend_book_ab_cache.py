"""Download klines for Book A/B symbols from 2026-01-01 through yesterday UTC."""
import json
from pathlib import Path

import pandas as pd

from .extend_scalp_cache import data_end_exclusive, extend_symbols


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
CACHE = '/tmp/sentinel-scalp-cache'
FROM = '2026-01-01'


def main() -> None:
    # Lag 1 day: same-day daily zip often 404 on data.binance.vision
    end = data_end_exclusive() - pd.Timedelta(days=1)
    output = Path(__file__).resolve().parents[2] / 'docs/research/paper_forward'
    output.mkdir(parents=True, exist_ok=True)
    report = extend_symbols(SYMBOLS, CACHE, FROM, end)
    payload = {'from': FROM, 'end_exclusive': str(end), 'symbols': report}
    (output / 'cache_extend.json').write_text(json.dumps(payload, indent=2) + '\n')
    print('Wrote', output / 'cache_extend.json')


if __name__ == '__main__':
    main()
