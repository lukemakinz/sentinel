"""S7 sequential price-action setups, with explicit oscillator ablations."""
from dataclasses import dataclass
from collections import Counter

import numpy as np
import pandas as pd
import talib

from .profile_routes import route_features
from .scalp_strategy import ScalpConfig


def connors_rsi(close):
    values = close.to_numpy(dtype=float)
    streak = np.zeros(len(values))
    for i in range(1, len(values)):
        direction = np.sign(values[i] - values[i-1])
        streak[i] = streak[i-1] + direction if direction * streak[i-1] > 0 else direction
    change = close.pct_change()
    # Compare today's one-bar return with the previous 100 one-bar returns.
    rank = change.rolling(101).apply(lambda x: np.mean(x[:-1] < x[-1]) * 100, raw=True)
    return (talib.RSI(values, 3) + talib.RSI(streak, 2) + rank) / 3


def action_features(minutes, interval=5):
    bars = route_features(minutes, interval, 1)
    bars['crsi'] = connors_rsi(bars.close)
    minimum, maximum = bars.rsi14.rolling(14).min(), bars.rsi14.rolling(14).max()
    stochastic = 100 * (bars.rsi14 - minimum) / (maximum - minimum).replace(0, np.nan)
    bars['stoch_k'] = stochastic.rolling(3).mean()
    bars['stoch_d'] = bars.stoch_k.rolling(3).mean()
    _, _, bars['macd_hist'] = talib.MACD(bars.close.to_numpy(), 12, 26, 9)
    bars['prior_low6'] = bars.low.shift().rolling(6).min()
    bars['prior_high6'] = bars.high.shift().rolling(6).max()
    bars['prior_high3'] = bars.high.shift().rolling(3).max()
    bars['prior_low3'] = bars.low.shift().rolling(3).min()
    bars['relative_volume'] = bars.volume / bars.volume.shift().rolling(24).median()
    return bars


@dataclass(frozen=True)
class ActionConfig:
    name: str
    setup: str
    confirmation: str
    target_r: float = 3.0
    minutes: int = 5

    def execution(self):
        return ScalpConfig(name=self.name, minutes=self.minutes, target_r=self.target_r,
                           partial_r=min(2, self.target_r - .25), partial_fraction=0,
                           trailing=self.target_r > 2, trail_atr=2,
                           max_hold_minutes=180, min_reward_cost_ratio=3,
                           leverage=20, max_margin_fraction=.15, max_notional_equity=3)


def action_variants():
    return [ActionConfig(f'S7pa_{setup}_{confirmation}_{target:g}R', setup, confirmation, target)
            for setup in ('pullback', 'sweep_fvg')
            for confirmation in ('none', 'crsi', 'stoch_rsi', 'macd')
            for target in (1.5, 3)]


def action_signals(bars, config):
    records = []
    rows = list(bars.itertuples())
    for side, label in ((1, 'long'), (-1, 'short')):
        state = None
        for i, row in enumerate(rows):
            if i < 110 or not np.isfinite(row.atr):
                continue
            extreme = row.low if side == 1 else row.high
            with_trend = row.bias4h == side
            both_div = getattr(row, f'{label}_rsi_div') and getattr(row, f'{label}_cvd_div')
            prior_extreme = row.prior_low6 if side == 1 else row.prior_high6
            sweep = side * (extreme - prior_extreme) < 0 and side * (row.close - prior_extreme) > 0
            if state is not None:
                if i - state['armed'] > 6 or side * (extreme - state['anchor']) < -.25 * row.atr:
                    state = None
                elif not with_trend and not state['countertrend']:
                    state = None
                else:
                    state['crsi_extreme'] = min(state['crsi_extreme'], row.crsi) if side == 1 else max(state['crsi_extreme'], row.crsi)
                    state['stoch_extreme'] = min(state['stoch_extreme'], row.stoch_k) if side == 1 else max(state['stoch_extreme'], row.stoch_k)
                    displacement = (side * (row.close - row.open) >= .5 * row.atr
                                    and side * (row.close - state['break_level']) > 0
                                    and side * row.delta_ratio > 0 and row.relative_volume >= 1)
                    gap_low, gap_high = ((rows[i-2].high, row.low) if side == 1 else (row.high, rows[i-2].low))
                    fvg = gap_high > gap_low
                    confirmation = True
                    if config.confirmation == 'crsi':
                        confirmation = (state['crsi_extreme'] < 25 and row.crsi > rows[i-1].crsi) if side == 1 else (
                            state['crsi_extreme'] > 75 and row.crsi < rows[i-1].crsi)
                    elif config.confirmation == 'stoch_rsi':
                        confirmation = (state['stoch_extreme'] < 20 if side == 1 else state['stoch_extreme'] > 80)
                        confirmation &= side * (row.stoch_k - row.stoch_d) > 0
                    elif config.confirmation == 'macd':
                        confirmation = side * (row.macd_hist - rows[i-1].macd_hist) > 0
                    if displacement and confirmation and (config.setup != 'sweep_fvg' or fvg):
                        entry = (gap_low + gap_high) / 2 if fvg else (row.open + row.close) / 2
                        stop = state['anchor'] - side * .2 * row.atr
                        r = side * (entry - stop)
                        if .5 * row.atr <= r <= 3 * row.atr:
                            # Do not buy immediately beneath a known profile
                            # resistance (vice versa for short). Above value,
                            # permit trend continuation toward an R-based target.
                            obstacles = [x for x in (row.val, row.poc, row.vah) if side * (x - entry) > 0]
                            space = min([side * (x - entry) for x in obstacles], default=float('inf'))
                            if space >= config.target_r * r:
                                records.append({'timestamp': row.Index, 'side': side,
                                                'reference': row.close, 'stop': stop, 'atr': row.atr,
                                                'limit_price': entry, 'limit_ttl_minutes': 15,
                                                'score': 0, 'setup': config.setup,
                                                'countertrend': state['countertrend'],
                                                'confirmation': config.confirmation,
                                                'armed_at': str(rows[state['armed']].Index)})
                                state = None
                                continue
            if state is None:
                if config.setup == 'sweep_fvg':
                    arm = sweep and (with_trend or (both_div and row.bias4h == -side))
                else:
                    arm = with_trend and side * (extreme - row.ema20) <= 0
                    arm &= (row.rsi5 < 45 if side == 1 else row.rsi5 > 55)
                if arm:
                    state = {'armed': i, 'anchor': extreme,
                             'break_level': row.prior_high3 if side == 1 else row.prior_low3,
                             'crsi_extreme': row.crsi, 'stoch_extreme': row.stoch_k,
                             'countertrend': not with_trend}
    counts = Counter(x['timestamp'] for x in records)
    return sorted([x for x in records if counts[x['timestamp']] == 1], key=lambda x: x['timestamp'])
