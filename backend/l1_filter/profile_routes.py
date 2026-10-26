"""S7 profile routes: HTF bias, VAL/POC/VAH destinations and structural stops."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, build_features, resample_closed, volume_profile


@dataclass(frozen=True)
class ProfileRouteConfig:
    name: str
    minutes: int = 15
    profile_days: int = 1
    entry_style: str = 'limit'
    min_profit_usd: float = 0
    leverage: float = 20

    def execution(self):
        return ScalpConfig(name=self.name, minutes=self.minutes, target_r=3,
                           partial_r=2, partial_fraction=0, trailing=True, trail_atr=2,
                           max_hold_minutes=360, min_reward_cost_ratio=3,
                           leverage=self.leverage, max_margin_fraction=.15,
                           max_notional_equity=3, fixed_margin_usd=10, fixed_risk_usd=2.5)


def route_variants():
    # profile_days fixed at 1 (previous UTC day): a second free profile-window
    # dimension would just be another knob to fit, not a distinct hypothesis.
    return [ProfileRouteConfig(
        f'S7vp_trend_{minutes}m_{entry}_{"goal10" if goal else "RR"}',
        minutes, 1, entry, goal)
        for minutes in (5, 15) for entry in ('market', 'limit') for goal in (0, 10)]


def route_features(minutes, interval, profile_days):
    bars = build_features(minutes, interval, 'previous_day')
    if profile_days == 3:
        records = []
        for end in pd.date_range(minutes.index[0].ceil('D') + pd.Timedelta(days=3),
                                 minutes.index[-1] + pd.Timedelta(minutes=1), freq='D'):
            group = minutes.loc[(minutes.index >= end - pd.Timedelta(days=3)) & (minutes.index < end)]
            if len(group) == 4320:
                records.append({'timestamp': end, **volume_profile(group)})
        if records:
            profile = pd.DataFrame(records).set_index('timestamp').reindex(bars.index, method='ffill')
            bars[['val', 'poc', 'vah']] = profile[['val', 'poc', 'vah']]
        else:
            bars[['val', 'poc', 'vah']] = np.nan
    htf = resample_closed(minutes, 240)
    htf['ema20'] = talib.EMA(htf.close.to_numpy(), 20)
    htf['ema50'] = talib.EMA(htf.close.to_numpy(), 50)
    htf['bias'] = np.where((htf.close > htf.ema20) & (htf.ema20 > htf.ema50)
                           & (htf.ema20 > htf.ema20.shift(2)), 1,
                           np.where((htf.close < htf.ema20) & (htf.ema20 < htf.ema50)
                                    & (htf.ema20 < htf.ema20.shift(2)), -1, 0))
    bars['bias4h'] = htf.bias.reindex(bars.index, method='ffill')
    bars['prior_high'] = bars.high.shift().rolling(12).max()
    bars['prior_low'] = bars.low.shift().rolling(12).min()
    bars['delta_ratio'] = (2 * bars.taker_buy_volume - bars.volume) / bars.volume.replace(0, np.nan)
    return bars


def route_signals(bars, config):
    records = []
    for side, label in ((1, 'long'), (-1, 'short')):
        extreme = bars.low if side == 1 else bars.high
        targets = [('val', 'poc'), ('poc', 'vah'), ('vah', None)] if side == 1 else [
            ('vah', 'poc'), ('poc', 'val'), ('val', None)]
        response = side * (bars.close - bars.open) > 0
        rsi_recovery = (side * bars.rsi5.diff() > 0)
        flow = side * bars.delta_ratio > 0
        for source_name, destination_name in targets:
            last_event = -100
            source = bars[source_name]
            destination = bars[destination_name] if destination_name else source + side * (bars.vah - bars.val)
            # The candle must trade through and reclaim the source level. A
            # profile refresh alone never creates a reclaim from a shifted line.
            reclaim = (side * (extreme - source) < 0) & (side * (bars.close - source) > 0)
            # Trend-only: no countertrend exception. A prior revision allowed a
            # "strong reversal" branch (divergence + sweep + structure break at
            # the outer band); it did not survive holdout testing and is a known
            # overfitting hole, so it is removed rather than tuned further.
            with_trend = bars.bias4h == side
            selected = (reclaim & response & with_trend & (flow | rsi_recovery) & bars.atr.notna())
            for i in np.flatnonzero(selected.to_numpy()):
                if i - last_event < 3:
                    continue
                row = bars.iloc[i]
                entry_reference = source.iloc[i] if config.entry_style == 'limit' else row.close
                structural_stop = extreme.iloc[i] - side * .2 * row.atr
                # Keep the stop outside the sweep. Minimum noise buffer 0.5ATR.
                stop = min(structural_stop, entry_reference - .5 * row.atr) if side == 1 else max(
                    structural_stop, entry_reference + .5 * row.atr)
                reward = side * (destination.iloc[i] - entry_reference)
                risk = side * (entry_reference - stop)
                if reward < 2.5 * risk:
                    continue
                last_event = i
                record = {'timestamp': bars.index[i], 'side': side, 'reference': float(row.close),
                          'stop': float(stop), 'atr': float(row.atr), 'score': 0,
                          'setup': f'{source_name}_to_{destination_name or "extension"}',
                          'target_price': float(destination.iloc[i]), 'min_target_r': 2.5,
                          'min_profit_usd': config.min_profit_usd,
                          'countertrend': bool(not with_trend.iloc[i])}
                if config.entry_style == 'limit':
                    record.update(limit_price=float(source.iloc[i]), limit_ttl_minutes=30)
                records.append(record)
    # At a timestamp with several valid routes prefer the nearest destination;
    # skip opposing directions. Do not manufacture separate simultaneous trades.
    by_time = {}
    for record in records:
        by_time.setdefault(record['timestamp'], []).append(record)
    result = []
    for timestamp, candidates in sorted(by_time.items()):
        if len({x['side'] for x in candidates}) != 1:
            continue
        result.append(min(candidates, key=lambda x: abs(x['target_price'] - x['reference'])))
    return result
