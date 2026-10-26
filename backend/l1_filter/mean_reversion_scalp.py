"""S8 research strategy: regime-gated value-area / VWAP-band mean reversion.

Deliberately the opposite filter from S7's trend-only reclaim: entries are
taken only when the market is NOT trending (low ADX, range-contained), using
resting maker/limit orders at VAL/VAH or a VWAP band, targeting a small,
fixed fraction of the value-area width toward POC. No trend requirement, no
indicator-confluence scoring, no trailing. Pure, causal signals; no live
orders or DB access.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import ScalpConfig, build_features, resample_closed


@dataclass(frozen=True)
class S8Config:
    name: str
    minutes: int = 5
    tp_width_mult: float = 0.7
    max_hold_minutes: int = 90
    # scalp_simulator.execute() hard-floors any stop tighter than 0.5*ATR
    # (r < 0.5*atr -> blocked_stop_width_or_gap, unconditionally, since a
    # limit-order r is fixed at signal time). 0.6 clears that floor with a
    # small margin; anything <= 0.5 blocks every single trade.
    stop_atr_mult: float = 0.6
    vwap_window_hours: float = 6
    vwap_sigma_mult: float = 1.0
    adx_threshold: float = 20.0
    containment_lookback: int = 24
    limit_ttl_minutes: int = 120
    leverage: float = 20
    event_cooldown_bars: int = 5

    def execution(self):
        return ScalpConfig(name=self.name, minutes=self.minutes, target_r=3, partial_r=2,
                           partial_fraction=0, trailing=False, trail_atr=1.5,
                           max_hold_minutes=self.max_hold_minutes, min_reward_cost_ratio=2.0,
                           risk_fraction=0.003, leverage=self.leverage,
                           max_margin_fraction=1.0, max_notional_equity=3,
                           fee_bps=5.0, slippage_bps=2.0, maker_fee_bps=2.0,
                           limit_penetration_bps=2.0, margin_safety_reserve=0.01)


def s8_variants():
    # Stage 1 (develop, coarse): timeframe x target-width. Hold time is
    # narrowed in a second develop pass on the winning (timeframe, width)
    # before holdout, per protocol.json — not re-opened after holdout.
    return [S8Config(f'S8_mr_{minutes}m_tp{int(tp*100)}', minutes, tp, 90)
            for minutes in (5, 15) for tp in (0.6, 0.7, 0.8)]


def s8_hold_variants(minutes, tp):
    return [S8Config(f'S8_mr_{minutes}m_tp{int(tp*100)}_hold{hold}', minutes, tp, hold)
            for hold in (60, 90)]


def _contained(minutes, lookback):
    """True on 1h bars whose range stayed inside the prior `lookback` bars."""
    hourly = resample_closed(minutes, 60)
    prior_high = hourly.high.shift(1).rolling(lookback).max()
    prior_low = hourly.low.shift(1).rolling(lookback).min()
    return ((hourly.high <= prior_high) & (hourly.low >= prior_low)
             & prior_high.notna() & prior_low.notna())


def _vwap_bands(bars, window_bars, sigma_mult):
    typical = (bars.high + bars.low + bars.close) / 3
    vol = bars.volume
    vwap = (typical * vol).rolling(window_bars).sum() / vol.rolling(window_bars).sum()
    sigma = (typical - vwap).rolling(window_bars).std()
    return vwap - sigma_mult * sigma, vwap + sigma_mult * sigma


def s8_features(minutes, config):
    bars = build_features(minutes, config.minutes, 'previous_day')
    bars['contained'] = _contained(minutes, config.containment_lookback).reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)
    window_bars = max(2, int(config.vwap_window_hours * 60 / config.minutes))
    bars['vwap_lower'], bars['vwap_upper'] = _vwap_bands(bars, window_bars, config.vwap_sigma_mult)
    return bars


def s8_signals(bars, config):
    """Resting limit orders at value-area edges or a VWAP band, gated to
    range regimes only (low ADX, no fresh extreme). No trend requirement:
    this is the deliberate inverse of S7's trend-only filter."""
    regime_ok = (bars.htf_adx <= config.adx_threshold) & bars.contained & bars.atr.notna()
    width = bars.vah - bars.val
    records = []
    for side in (1, -1):
        edge_level = bars.val if side == 1 else bars.vah
        band_level = bars.vwap_lower if side == 1 else bars.vwap_upper
        for setup_name, level in (('profile_edge', edge_level), ('vwap_band', band_level)):
            valid = regime_ok & level.notna() & (width > 0)
            last_event = -10 ** 6
            for i in np.flatnonzero(valid.to_numpy()):
                if i - last_event < config.event_cooldown_bars:
                    continue
                row = bars.iloc[i]
                lvl = float(level.iloc[i])
                stop = lvl - side * config.stop_atr_mult * row.atr
                target = lvl + side * config.tp_width_mult * width.iloc[i]
                risk, reward = side * (lvl - stop), side * (target - lvl)
                if risk <= 0 or reward <= 0:
                    continue
                last_event = i
                records.append({'timestamp': bars.index[i], 'side': side,
                                'reference': float(row.close), 'stop': float(stop),
                                'atr': float(row.atr), 'score': 0, 'setup': setup_name,
                                'target_price': float(target), 'limit_price': lvl,
                                'limit_ttl_minutes': config.limit_ttl_minutes})
    # Unlike S7's single momentum reclaim, a resting bid near VAL and a
    # resting ask near VAH are both legitimate at the same bar (a range
    # market maker brackets both sides; whichever fills first wins — the
    # simulator only ever holds one pending order/position at a time). So,
    # unlike route_signals, same-timestamp long+short is not a conflict to
    # drop; just keep the single nearest resting level per timestamp.
    by_time = {}
    for record in records:
        by_time.setdefault(record['timestamp'], []).append(record)
    return [min(candidates, key=lambda x: abs(x['limit_price'] - x['reference']))
            for _, candidates in sorted(by_time.items())]
