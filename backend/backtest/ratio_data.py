"""Builds a synthetic single-instrument minute series for an A/B ratio
(e.g. ETHUSDT/BTCUSDT), so the existing single-instrument scalp machinery
(resample_closed, ATR/RSI/Bollinger features, execute_cluster) can be
reused unmodified to diagnose relative-value mean reversion, without
building a genuine two-leg execution engine.

Ratio OHLC uses interval arithmetic: since A/B is monotonically increasing
in A and decreasing in B, the true achievable extremes of the ratio within
one minute are exactly high=A.high/B.low and low=A.low/B.high (open/close
use each leg's own open/close directly, which always fall inside that
range) -- not an approximation of "which corner", the actual bound.
"""
import pandas as pd


def build_ratio_minutes(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    a, b = a.align(b, join='inner')
    ratio = pd.DataFrame(index=a.index)
    ratio['open'] = a.open / b.open
    ratio['close'] = a.close / b.close
    ratio['high'] = a.high / b.low
    ratio['low'] = a.low / b.high
    ratio['volume'] = a.volume
    ratio['taker_buy_volume'] = a.taker_buy_volume
    return ratio
