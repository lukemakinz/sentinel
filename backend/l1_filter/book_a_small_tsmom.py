"""Book A — frozen S73+BTC small-book daily TSMOM (long-only, BTC > SMA200)."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BookASmallTsmomConfig:
    name: str = 'BOOK_A_S73_BTC'
    mom_lookback_days: int = 20
    sma_gate_days: int = 200
    top_n: int = 6
    min_position_usd: float = 15.0
    vol_target_annual: float = 0.30
    rebalance_weekday: int = 0  # Monday UTC
    taker_fee_bps: float = 7.0
    include_btc_in_universe: bool = True
    min_mom_fraction: float = 0.0
    rebalance_every_n_weeks: int = 1

    def alt_symbols(self) -> tuple[str, ...]:
        return ('SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT', 'ETHUSDT')

    def gate_symbol(self) -> str:
        return 'BTCUSDT'


# S83 experiment: BTC stays macro gate only, not a held leg.
BOOK_A_ALT_RM = BookASmallTsmomConfig(
    name='BOOK_A_ALT_RM',
    include_btc_in_universe=False,
)


def daily_closes(minutes: pd.DataFrame) -> pd.Series:
    # Keep Book A independent from the intraday indicator stack.  Importing
    # scalp_strategy only for this six-line resample also imported TA-Lib,
    # even though the frozen daily strategy does not use a TA-Lib indicator.
    interval = 1440
    rule = f'{interval}min'
    bars = minutes.resample(rule, label='right', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum',
    })
    counts = minutes.close.resample(rule, label='right', closed='left').count()
    bars = bars.loc[counts == interval].copy()
    return bars['close'].astype(float)


def build_daily_panel(
    minutes_by_symbol: dict[str, pd.DataFrame],
    config: BookASmallTsmomConfig,
) -> pd.DataFrame:
    """Columns: one close per symbol, aligned on UTC days."""
    series = {}
    gate = config.gate_symbol()
    if gate not in minutes_by_symbol:
        raise ValueError(f'Missing gate symbol {gate}')
    series[gate] = daily_closes(minutes_by_symbol[gate])
    for symbol in config.alt_symbols():
        if symbol in minutes_by_symbol:
            series[symbol] = daily_closes(minutes_by_symbol[symbol])
    frame = pd.DataFrame(series).sort_index().ffill()
    return frame


def _realized_vol(returns: pd.Series, window: int = 20) -> float:
    tail = returns.dropna().tail(window)
    if len(tail) < 5:
        return np.nan
    return float(tail.std() * np.sqrt(365))


def target_weights_for_day(
    panel: pd.DataFrame,
    day: pd.Timestamp,
    config: BookASmallTsmomConfig,
) -> dict[str, float]:
    """Long-only weights summing to <= 1; empty when gate off."""
    history = panel.loc[:day]
    if len(history) < config.sma_gate_days + config.mom_lookback_days + 2:
        return {}
    gate = config.gate_symbol()
    btc = history[gate]
    if float(btc.iloc[-1]) <= float(btc.rolling(config.sma_gate_days).mean().iloc[-1]):
        return {}

    universe = list(config.alt_symbols())
    if config.include_btc_in_universe and gate not in universe:
        universe.append(gate)

    mom = {}
    vol = {}
    for symbol in universe:
        if symbol not in history.columns:
            continue
        px = history[symbol]
        if len(px) < config.mom_lookback_days + 2:
            continue
        m = float(px.iloc[-1] / px.iloc[-1 - config.mom_lookback_days] - 1.0)
        if m <= config.min_mom_fraction:
            continue
        mom[symbol] = m
        vol[symbol] = _realized_vol(px.pct_change(), 20)

    if not mom:
        return {}

    ranked = sorted(mom.keys(), key=lambda s: mom[s], reverse=True)[: config.top_n]
    inv_vol = {}
    for symbol in ranked:
        v = vol.get(symbol)
        inv_vol[symbol] = 1.0 / v if v and np.isfinite(v) and v > 1e-8 else 1.0
    raw = {s: inv_vol[s] for s in ranked}
    gross = sum(raw.values())
    weights = {s: raw[s] / gross for s in ranked}

    port_vol = config.vol_target_annual
    avg_vol = np.nanmean([vol.get(s, np.nan) for s in ranked])
    scale = 1.0
    if avg_vol and np.isfinite(avg_vol) and avg_vol > 1e-8:
        scale = min(1.0, port_vol / avg_vol)
    return {s: weights[s] * scale for s in ranked}
