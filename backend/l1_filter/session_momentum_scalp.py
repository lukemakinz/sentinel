"""S9 research strategy: session VWAP/EMA trend-pullback scalp.

This deliberately separates roles instead of treating correlated indicators as
independent votes:

* 1h bias + ADX define the tradable regime and direction.
* EMA20 / session VWAP define the pullback location.
* A closed rejection/displacement candle is the mandatory trigger.
* RSI(5), EMA9/20, candle delta (CVD increment) and relative volume provide an
  x-of-y quality score.

Signals are emitted at a completed bar timestamp and can only enter on a later
minute. The module is pure research code: no database or exchange access.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .scalp_strategy import ScalpConfig, build_features


@dataclass(frozen=True)
class SessionMomentumConfig:
    name: str
    minutes: int = 5
    min_score: int = 2
    target_r: float = 1.1
    entry_style: str = 'market'
    max_hold_minutes: int = 75
    leverage: float = 20

    def execution(self):
        return ScalpConfig(
            name=self.name,
            minutes=self.minutes,
            target_r=self.target_r,
            partial_r=0.60,
            partial_fraction=0.65,
            trailing=True,
            trail_atr=0.85,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=0.002,
            max_notional_equity=3.0,
            daily_loss_fraction=0.01,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=2.0,
            leverage=self.leverage,
            max_margin_fraction=0.15,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            margin_safety_reserve=0.01,
        )


def session_momentum_variants():
    return [
        SessionMomentumConfig(
            name=f'S9_session_pullback_{minutes}m_{score}of4_{entry}_tp{int(target * 100)}',
            minutes=minutes,
            min_score=score,
            target_r=target,
            entry_style=entry,
            max_hold_minutes=75 if minutes == 5 else 120,
        )
        for minutes in (5, 15)
        for score in (2, 3)
        for entry in ('market', 'limit')
        for target in (1.0, 1.25)
    ]


def session_momentum_features(minutes, interval):
    bars = build_features(minutes, interval, 'previous_day')
    typical = (bars.high + bars.low + bars.close) / 3
    day = bars.index.floor('D')
    cumulative_volume = bars.volume.groupby(day).cumsum().replace(0, np.nan)
    bars['session_vwap'] = (typical * bars.volume).groupby(day).cumsum() / cumulative_volume
    bars['delta_ratio'] = ((2 * bars.taker_buy_volume - bars.volume)
                           / bars.volume.replace(0, np.nan))
    bars['relative_volume'] = bars.volume / bars.volume.shift().rolling(
        max(12, int(6 * 60 / interval))).median()
    bars['prior_high3'] = bars.high.shift().rolling(3).max()
    bars['prior_low3'] = bars.low.shift().rolling(3).min()
    return bars


def session_momentum_signals(bars, config):
    records = []
    session = (bars.index.hour >= 7) & (bars.index.hour < 18)
    bar_range = (bars.high - bars.low).replace(0, np.nan)
    close_location = (bars.close - bars.low) / bar_range

    for side in (1, -1):
        extreme = bars.low if side == 1 else bars.high
        prior_extreme = bars.prior_low3 if side == 1 else bars.prior_high3

        # Location is checked on the previous closed bar, so the current bar is
        # a real response to a known pullback rather than the same-bar touch.
        ema_touch = side * (extreme.shift() - bars.ema20.shift()) <= 0.20 * bars.atr.shift()
        vwap_touch = side * (extreme.shift() - bars.session_vwap.shift()) <= 0.20 * bars.atr.shift()
        not_extended = side * (bars.close.shift() - bars.ema20.shift()) <= 0.75 * bars.atr.shift()
        location = (ema_touch | vwap_touch) & not_extended

        response_body = side * (bars.close - bars.open) >= 0.22 * bars.atr
        response_location = close_location >= 0.65 if side == 1 else close_location <= 0.35
        micro_break = side * (bars.close - (bars.high.shift() if side == 1 else bars.low.shift())) > 0
        trigger = response_body & response_location & micro_break

        rsi_recovery = ((bars.rsi5 > 50) & (bars.rsi5.shift() <= 50)) if side == 1 else (
            (bars.rsi5 < 50) & (bars.rsi5.shift() >= 50))
        ema_aligned = side * (bars.ema9 - bars.ema20) > 0
        flow_aligned = side * bars.delta_ratio > 0.05
        volume_confirms = bars.relative_volume >= 1.10
        score = (rsi_recovery.astype(int) + ema_aligned.astype(int)
                 + flow_aligned.astype(int) + volume_confirms.astype(int))

        regime = ((bars.htf_bias == side) & (bars.htf_adx >= 18)
                  & (bars.htf_adx <= 45) & session)
        selected = (regime & location & trigger & (score >= config.min_score)
                    & bars.atr.notna())

        last_event = -1000
        for i in np.flatnonzero(selected.fillna(False).to_numpy()):
            if i - last_event < max(2, int(15 / config.minutes)):
                continue
            row = bars.iloc[i]
            structural_stop = prior_extreme.iloc[i] - side * 0.18 * row.atr
            reference = row.close
            minimum_stop = reference - side * 0.55 * row.atr
            stop = min(structural_stop, minimum_stop) if side == 1 else max(
                structural_stop, minimum_stop)
            risk = side * (reference - stop)
            if not np.isfinite(risk) or not 0.5 * row.atr <= risk <= 2.2 * row.atr:
                continue
            record = {
                'timestamp': row.name,
                'side': side,
                'reference': float(reference),
                'stop': float(stop),
                'atr': float(row.atr),
                'score': int(score.iloc[i]),
                'setup': 'session_vwap_ema_pullback',
            }
            if config.entry_style == 'limit':
                record['limit_price'] = float(reference - side * 0.18 * row.atr)
                record['limit_ttl_minutes'] = 3 * config.minutes
                # Preserve the structural invalidation after improving entry.
                if side * (record['limit_price'] - record['stop']) < 0.5 * row.atr:
                    continue
            records.append(record)
            last_event = i

    records.sort(key=lambda x: x['timestamp'])
    counts = Counter(x['timestamp'] for x in records)
    return [x for x in records if counts[x['timestamp']] == 1]
