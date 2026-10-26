"""Shared daily risk context for Book B (aligns with Book A indicators)."""
from dataclasses import dataclass

import pandas as pd

from .book_a_risk_overlay import (
    BookARiskOverlayConfig,
    BOOK_A_RISK_DEFAULT,
    compute_risk_indicators,
    exposure_multiplier,
)
from .book_a_small_tsmom import BookASmallTsmomConfig, build_daily_panel


@dataclass(frozen=True)
class BookBSharedRiskConfig:
    name: str = 'BOOK_B_RM_align_v1'
    book_a_gate: BookASmallTsmomConfig = BookASmallTsmomConfig()
    book_a_overlay: BookARiskOverlayConfig = BOOK_A_RISK_DEFAULT
    max_btc_vol_percentile: float = 0.78
    min_breadth_for_macro: float = 0.35
    min_signal_risk_scale: float = 0.20
    complement_when_a_throttled: bool = True
    complement_only: bool = False
    max_a_mult_for_complement: float = 0.55


def daily_indicator_table(
    minutes_by_symbol: dict[str, pd.DataFrame],
    gate: BookASmallTsmomConfig,
) -> pd.DataFrame:
    panel = build_daily_panel(minutes_by_symbol, gate)
    rows = []
    for day in panel.index:
        ind = compute_risk_indicators(panel, day, gate)
        if ind.get('valid', 0) < 1:
            continue
        ind['day'] = day
        rows.append(ind)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('day')


def macro_signal_risk_scale(
    day: pd.Timestamp,
    indicators: pd.DataFrame,
    config: BookBSharedRiskConfig,
) -> float | None:
    """Return risk_scale in [0,1] or None to skip the signal."""
    day = day.normalize()
    if day not in indicators.index:
        return None
    row = indicators.loc[day]
    if row.get('btc_above_sma200', 0) < 1:
        return None
    vol_pct = float(row.get('btc_vol_percentile', 0.5))
    if vol_pct > config.max_btc_vol_percentile:
        return None
    breadth = float(row.get('breadth_sma50', 0))
    if breadth < config.min_breadth_for_macro:
        return None

    a_mult = exposure_multiplier(row.to_dict(), config.book_a_overlay)
    if config.complement_only:
        if a_mult > config.max_a_mult_for_complement:
            return None
        b_mult = max(0.35, 1.0 - a_mult)
    elif config.complement_when_a_throttled:
        b_mult = 0.35 + 0.65 * (1.0 - min(1.0, a_mult))
    else:
        b_mult = a_mult
    vol_soft = max(0.0, 1.0 - vol_pct / config.max_btc_vol_percentile)
    scale = b_mult * vol_soft
    if scale < config.min_signal_risk_scale:
        return None
    return min(1.0, scale)


def apply_shared_risk_to_signals(
    signals: list[dict],
    indicators: pd.DataFrame,
    config: BookBSharedRiskConfig,
) -> list[dict]:
    out = []
    for signal in signals:
        day = pd.Timestamp(signal['timestamp']).normalize()
        scale = macro_signal_risk_scale(day, indicators, config)
        if scale is None:
            continue
        tagged = dict(signal)
        tagged['risk_scale'] = scale
        tagged['setup'] = f'{signal.get("setup", "macro")}_rm'
        out.append(tagged)
    return out
