"""Route Book B quiet Donchian v1 vs v2 from daily breadth (chop vs bull)."""
from dataclasses import dataclass

import pandas as pd

from .book_a_small_tsmom import BookASmallTsmomConfig, build_daily_panel
from .book_b_quiet_breakout import (
    BOOK_B_QUIET_V2,
    BookBQuietBreakoutConfig,
    build_quiet_breakout_signals,
    filter_quiet_breakout_signals,
)
from .book_b_shared_risk import daily_indicator_table
from .hourly_donchian_adx import (
    generate_hourly_donchian_adx_signals,
    hourly_donchian_adx_features,
)


@dataclass(frozen=True)
class BookBQuietRouterConfig:
    name: str = 'S84_quiet_router'
    breadth_v2_threshold: float = 0.45
    low_vol_v2_threshold: float = 0.35
    low_vol_min_breadth: float = 0.25
    v1: BookBQuietBreakoutConfig = BookBQuietBreakoutConfig()
    v2: BookBQuietBreakoutConfig = BOOK_B_QUIET_V2


def pick_quiet_config(
    breadth: float,
    vol_pct: float,
    router: BookBQuietRouterConfig,
) -> BookBQuietBreakoutConfig:
    if breadth >= router.breadth_v2_threshold:
        return router.v2
    if vol_pct < router.low_vol_v2_threshold and breadth >= router.low_vol_min_breadth:
        return router.v2
    return router.v1


def build_routed_quiet_signals(
    minutes: pd.DataFrame,
    minutes_panel: dict[str, pd.DataFrame],
    symbol: str,
    router: BookBQuietRouterConfig,
) -> list[dict]:
    gate = BookASmallTsmomConfig()
    indicators = daily_indicator_table(minutes_panel, gate)
    raw = generate_hourly_donchian_adx_signals(
        hourly_donchian_adx_features(minutes, router.v1.donchian),
        router.v1.donchian,
        symbol,
    )
    out = []
    for signal in raw:
        day = pd.Timestamp(signal['timestamp']).normalize()
        if day not in indicators.index:
            continue
        row = indicators.loc[day]
        breadth = float(row.get('breadth_sma50', 0))
        vol_pct = float(row.get('btc_vol_percentile', 0.5))
        cfg = pick_quiet_config(breadth, vol_pct, router)
        filtered = filter_quiet_breakout_signals([signal], indicators, cfg)
        for item in filtered:
            tagged = dict(item)
            tagged['setup'] = f'{router.name}_{cfg.name}'
            out.append(tagged)
    return out
