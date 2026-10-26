"""S91: first-contact reclaim of 15m levels aligned with 1h S/R and BTC regime."""
from dataclasses import dataclass

import pandas as pd

from .fresh_level_sweep_reclaim import FreshLevelSweepReclaimConfig
from .scalp_strategy import resample_closed


@dataclass(frozen=True)
class IntradayLevelReclaimConfig(FreshLevelSweepReclaimConfig):
    name: str = 'S91_intraday_level_reclaim'
    level_minutes: int = 15
    htf_minutes: int = 60
    structure_lookback: int = 480
    htf_distance_atr: float = 0.50
    validity_hours: int = 48
    require_distal_sweep: bool = False


def btc_sma200_regime_filter(
    levels: list[dict],
    btc_minutes: pd.DataFrame,
    sma_days: int = 200,
) -> list[dict]:
    """Keep longs above and shorts below the last completed BTC daily SMA200."""
    daily = resample_closed(btc_minutes, 1440)[['close']].copy()
    daily['sma'] = daily.close.rolling(sma_days).mean()
    out = []
    for level in levels:
        known = daily.loc[daily.index <= level['created_at']]
        if known.empty or pd.isna(known.iloc[-1].sma):
            continue
        row = known.iloc[-1]
        regime_side = 1 if row.close > row.sma else -1
        if level['side'] != regime_side:
            continue
        tagged = dict(level)
        evidence = dict(tagged.get('evidence') or {})
        evidence.update({
            'btc_daily_close': float(row.close),
            'btc_daily_sma200': float(row.sma),
            'btc_regime_side': regime_side,
        })
        tagged['evidence'] = evidence
        out.append(tagged)
    return out
