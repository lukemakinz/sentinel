"""S8v2: same regime filter as S8 (mean_reversion_scalp.py), fixed exit
geometry. S8 v1 lost because its stop (0.6*ATR, close to the level) was far
tighter than its target (0.6-0.8x the value-area width, toward POC): plain
noise at the range edge hit the stop long before price could travel that far.

Two changes, no new indicators:
  1. Entry requires a rejection candle at the level first (wick through it,
     close back on the inside, body in the reversal direction) before a
     retest limit order is armed — filters levels the market just runs
     through without reacting.
  2. Target is measured in the same ATR unit as the stop (1.0-1.5x ATR)
     instead of a large fraction of the value-area width, and the stop sits
     behind the rejection wick (+ a small buffer) instead of a fixed
     fraction of ATR off the raw level.
"""
from dataclasses import dataclass

import numpy as np

from .mean_reversion_scalp import _contained, _vwap_bands
from .scalp_strategy import ScalpConfig, build_features


@dataclass(frozen=True)
class S8v2Config:
    name: str
    minutes: int = 5
    target_atr_mult: float = 1.25
    max_hold_minutes: int = 90
    stop_buffer_atr_mult: float = 0.12
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


def s8v2_variants():
    return [S8v2Config(f'S8v2_mr_{minutes}m_tp{int(tp*100)}', minutes, tp, 90)
            for minutes in (5, 15) for tp in (1.0, 1.25, 1.5)]


def s8v2_hold_variants(minutes, tp):
    return [S8v2Config(f'S8v2_mr_{minutes}m_tp{int(tp*100)}_hold{hold}', minutes, tp, hold)
            for hold in (60, 90)]


def s8v2_features(minutes, config):
    bars = build_features(minutes, config.minutes, 'previous_day')
    bars['contained'] = _contained(minutes, config.containment_lookback).reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)
    window_bars = max(2, int(config.vwap_window_hours * 60 / config.minutes))
    bars['vwap_lower'], bars['vwap_upper'] = _vwap_bands(bars, window_bars, config.vwap_sigma_mult)
    return bars


def s8v2_signals(bars, config):
    """Resting limit orders at value-area edges or a VWAP band, armed only
    after a rejection candle (wick through the level, close back inside,
    body in the reversal direction) — the deliberate fix over v1, which
    armed on the level alone with no evidence the market actually reacted
    to it. Stop sits behind the rejection wick; target is a small, fixed
    multiple of ATR, not a large fraction of the value-area width."""
    regime_ok = (bars.htf_adx <= config.adx_threshold) & bars.contained & bars.atr.notna()
    o, h, l, c, atr = bars.open.to_numpy(), bars.high.to_numpy(), bars.low.to_numpy(), \
        bars.close.to_numpy(), bars.atr.to_numpy()
    records = []
    for side in (1, -1):
        edge_level = bars.val if side == 1 else bars.vah
        band_level = bars.vwap_lower if side == 1 else bars.vwap_upper
        for setup_name, level in (('profile_edge', edge_level), ('vwap_band', band_level)):
            lvl_arr = level.to_numpy()
            valid = (regime_ok & level.notna()).to_numpy()
            last_event = -10 ** 6
            for i in np.flatnonzero(valid):
                if i - last_event < config.event_cooldown_bars:
                    continue
                lvl = lvl_arr[i]
                if side == 1:
                    rejected = l[i] < lvl and c[i] >= lvl and c[i] > o[i]
                else:
                    rejected = h[i] > lvl and c[i] <= lvl and c[i] < o[i]
                if not rejected:
                    continue
                wick = l[i] if side == 1 else h[i]
                stop = wick - side * config.stop_buffer_atr_mult * atr[i]
                target = lvl + side * config.target_atr_mult * atr[i]
                risk, reward = side * (lvl - stop), side * (target - lvl)
                if risk <= 0 or reward <= 0:
                    continue
                last_event = i
                records.append({'timestamp': bars.index[i], 'side': side,
                                'reference': float(c[i]), 'stop': float(stop),
                                'atr': float(atr[i]), 'score': 0, 'setup': setup_name,
                                'target_price': float(target), 'limit_price': float(lvl),
                                'limit_ttl_minutes': config.limit_ttl_minutes})
    by_time = {}
    for record in records:
        by_time.setdefault(record['timestamp'], []).append(record)
    return [min(candidates, key=lambda x: abs(x['limit_price'] - x['reference']))
            for _, candidates in sorted(by_time.items())]
