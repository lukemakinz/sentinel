"""Risk indicators and exposure overlay for Book A (S73+BTC)."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .book_a_small_tsmom import BookASmallTsmomConfig


@dataclass(frozen=True)
class BookARiskOverlayConfig:
    """Frozen risk-management hypotheses — no parameter grid in runners."""

    name: str = 'RM_composite_v1'
    min_breadth_sma50: float = 0.35
    vol_pct_soft_cap: float = 0.75
    vol_pct_hard_cap: float = 0.92
    drawdown_half_scale: float = 0.10
    drawdown_flat_scale: float = 0.18
    drawdown_half_multiplier: float = 0.50
    max_gross_exposure: float = 0.85
    use_breadth: bool = True
    use_vol_penalty: bool = True
    use_drawdown_throttle: bool = True


def _alt_columns(panel: pd.DataFrame, config: BookASmallTsmomConfig) -> list[str]:
    return [s for s in config.alt_symbols() if s in panel.columns]


def compute_risk_indicators(
    panel: pd.DataFrame,
    day: pd.Timestamp,
    config: BookASmallTsmomConfig,
    equity: float | None = None,
    peak_equity: float | None = None,
) -> dict[str, float]:
    """Causal indicators known at end of `day` (daily close)."""
    history = panel.loc[:day]
    gate = config.gate_symbol()
    if len(history) < config.sma_gate_days + 5 or gate not in history.columns:
        return {'valid': 0.0}

    btc = history[gate].astype(float)
    close = float(btc.iloc[-1])
    sma200 = float(btc.rolling(config.sma_gate_days).mean().iloc[-1])
    sma50 = float(btc.rolling(50).mean().iloc[-1])
    ret = btc.pct_change()
    vol20 = float(ret.tail(20).std() * np.sqrt(365)) if len(ret) >= 20 else np.nan
    vol_hist = ret.rolling(20).std() * np.sqrt(365)
    vol_hist = vol_hist.dropna()
    vol_pct = 0.5
    if len(vol_hist) >= 60 and np.isfinite(vol20):
        vol_pct = float((vol_hist <= vol20).mean())

    alts = _alt_columns(history, config)
    breadth = 0.0
    if alts:
        above = 0
        for symbol in alts:
            px = history[symbol].astype(float)
            if len(px) < 50:
                continue
            sma = float(px.rolling(50).mean().iloc[-1])
            if float(px.iloc[-1]) > sma:
                above += 1
        breadth = above / len(alts)

    moms = []
    for symbol in alts:
        px = history[symbol].astype(float)
        if len(px) < config.mom_lookback_days + 2:
            continue
        moms.append(float(px.iloc[-1] / px.iloc[-1 - config.mom_lookback_days] - 1.0))
    dispersion = float(np.std(moms)) if len(moms) >= 2 else 0.0

    dd_frac = 0.0
    if equity is not None and peak_equity is not None and peak_equity > 0:
        dd_frac = max(0.0, 1.0 - equity / peak_equity)

    return {
        'valid': 1.0,
        'btc_above_sma200': 1.0 if close > sma200 else 0.0,
        'btc_above_sma50': 1.0 if close > sma50 else 0.0,
        'btc_vol20_ann': vol20 if np.isfinite(vol20) else 0.0,
        'btc_vol_percentile': vol_pct,
        'breadth_sma50': breadth,
        'mom_dispersion': dispersion,
        'equity_drawdown': dd_frac,
    }


def exposure_multiplier(
    indicators: dict[str, float],
    risk: BookARiskOverlayConfig,
) -> float:
    if indicators.get('valid', 0.0) < 1:
        return 0.0
    if indicators.get('btc_above_sma200', 0.0) < 1:
        return 0.0

    mult = 1.0
    if risk.use_breadth:
        breadth = indicators.get('breadth_sma50', 0.0)
        if breadth < risk.min_breadth_sma50:
            return 0.0
        mult *= min(1.0, breadth / risk.min_breadth_sma50)

    if risk.use_vol_penalty:
        vol_pct = indicators.get('btc_vol_percentile', 0.5)
        if vol_pct >= risk.vol_pct_hard_cap:
            return 0.0
        if vol_pct > risk.vol_pct_soft_cap:
            span = risk.vol_pct_hard_cap - risk.vol_pct_soft_cap
            mult *= max(0.0, 1.0 - (vol_pct - risk.vol_pct_soft_cap) / span)

    if risk.use_drawdown_throttle:
        dd = indicators.get('equity_drawdown', 0.0)
        if dd >= risk.drawdown_flat_scale:
            return 0.0
        if dd >= risk.drawdown_half_scale:
            mult *= risk.drawdown_half_multiplier

    return min(mult, risk.max_gross_exposure)


# Frozen default after book_a_risk_overlay research (validation DD −11.1% vs −17%).
BOOK_A_RISK_DEFAULT = BookARiskOverlayConfig(name='RM_composite_v1')


def risk_overlay_variants() -> list[BookARiskOverlayConfig]:
    return [
        BookARiskOverlayConfig(
            name='RM_breadth_only',
            use_vol_penalty=False,
            use_drawdown_throttle=False,
        ),
        BookARiskOverlayConfig(
            name='RM_vol_only',
            use_breadth=False,
            use_drawdown_throttle=False,
        ),
        BookARiskOverlayConfig(
            name='RM_drawdown_only',
            use_breadth=False,
            use_vol_penalty=False,
        ),
        BookARiskOverlayConfig(name='RM_composite_v1'),
        BookARiskOverlayConfig(
            name='RM_composite_tight',
            min_breadth_sma50=0.45,
            drawdown_half_scale=0.08,
            drawdown_flat_scale=0.14,
            max_gross_exposure=0.65,
        ),
    ]


def indicator_research_frame(
    panel: pd.DataFrame,
    config: BookASmallTsmomConfig,
) -> pd.DataFrame:
    """Daily indicators + forward 5d equal-weight alt return (research only)."""
    alts = _alt_columns(panel, config)
    if not alts:
        raise ValueError('No alt columns for research')
    alt_px = panel[alts].astype(float)
    ew_ret = alt_px.pct_change().mean(axis=1)
    fwd5 = ew_ret.rolling(5).sum().shift(-5)

    rows = []
    for day in panel.index:
        ind = compute_risk_indicators(panel, day, config)
        if ind.get('valid', 0) < 1:
            continue
        row = {**ind, 'fwd5_ew_alt': float(fwd5.loc[day]) if day in fwd5.index else np.nan}
        row['day'] = day
        rows.append(row)
    return pd.DataFrame(rows).set_index('day')
