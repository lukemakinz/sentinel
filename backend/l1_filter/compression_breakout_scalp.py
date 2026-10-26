"""S10 candidate: compression breakout followed by first accepted retest.

All timestamps represent bar-close availability.  Session boxes and their
compression ranks are frozen before the tradable window, and every box can
produce at most one signal.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class CompressionBreakoutConfig:
    name: str
    compression_quantile: float = 0.40
    breakout_atr: float = 0.10
    target_r: float = 2.50
    leverage: float = 20.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.25,
            partial_fraction=0.50,
            trailing=True,
            trail_atr=1.0,
            max_hold_minutes=180,
            risk_fraction=0.0025,
            max_notional_equity=1.0,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=self.leverage,
            max_margin_fraction=0.05,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            margin_safety_reserve=0.01,
        )


def compression_breakout_variants() -> list[CompressionBreakoutConfig]:
    """One central rule plus four one-dimensional sensitivity checks."""
    return [
        CompressionBreakoutConfig('S10_cbar_central'),
        CompressionBreakoutConfig('S10_cbar_compress30', compression_quantile=0.30),
        CompressionBreakoutConfig('S10_cbar_compress50', compression_quantile=0.50),
        CompressionBreakoutConfig('S10_cbar_break05', breakout_atr=0.05),
        CompressionBreakoutConfig('S10_cbar_break15', breakout_atr=0.15),
    ]


def _confirmed_structure(hourly: pd.DataFrame) -> pd.Series:
    """Two-left/two-right pivots, published two bars after the pivot."""
    bias = np.zeros(len(hourly), dtype=int)
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    highs, lows = hourly.high.to_numpy(), hourly.low.to_numpy()
    for known in range(4, len(hourly)):
        pivot = known - 2
        if highs[pivot] == np.max(highs[pivot - 2:pivot + 3]):
            swing_highs.append(float(highs[pivot]))
        if lows[pivot] == np.min(lows[pivot - 2:pivot + 3]):
            swing_lows.append(float(lows[pivot]))
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            if swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]:
                bias[known] = 1
            elif swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]:
                bias[known] = -1
        if known and bias[known] == 0:
            bias[known] = bias[known - 1]
    return pd.Series(bias, index=hourly.index)


def _attach_session_boxes(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    for column in ('box_high', 'box_low', 'box_ratio',
                   'compression_cutoff_30', 'compression_cutoff_40',
                   'compression_cutoff_50'):
        result[column] = np.nan
    result['session'] = None
    result['session_date'] = None

    local_dates = sorted(set(result.index.tz_convert('America/New_York').date))
    history: dict[str, list[float]] = {'london': [], 'new_york': []}
    for local_date in local_dates:
        midnight = pd.Timestamp(local_date, tz='America/New_York')
        sessions = (
            ('london', midnight + pd.Timedelta(hours=2), midnight + pd.Timedelta(hours=5)),
            ('new_york', midnight + pd.Timedelta(hours=9, minutes=30),
             midnight + pd.Timedelta(hours=12, minutes=30)),
        )
        for name, session_open, session_close in sessions:
            open_utc = session_open.tz_convert('UTC')
            close_utc = session_close.tz_convert('UTC')
            box = result.loc[(result.index > open_utc - pd.Timedelta(hours=4))
                             & (result.index <= open_utc)]
            if box.empty:
                continue
            atr_at_open = result.atr.loc[:open_utc].dropna()
            if atr_at_open.empty or atr_at_open.iloc[-1] <= 0:
                continue
            high, low = float(box.high.max()), float(box.low.min())
            ratio = (high - low) / float(atr_at_open.iloc[-1])
            prior = history[name][-40:]
            cutoffs = ({q: float(np.quantile(prior, q)) for q in (0.30, 0.40, 0.50)}
                       if len(prior) >= 20 else {q: np.nan for q in (0.30, 0.40, 0.50)})
            mask = (result.index >= open_utc) & (result.index < close_utc)
            result.loc[mask, 'box_high'] = high
            result.loc[mask, 'box_low'] = low
            result.loc[mask, 'box_ratio'] = ratio
            for quantile, cutoff in cutoffs.items():
                result.loc[mask, f'compression_cutoff_{int(quantile * 100)}'] = cutoff
            result.loc[mask, 'session'] = name
            result.loc[mask, 'session_date'] = str(local_date)
            history[name].append(ratio)
    return result


def compression_breakout_features(minutes: pd.DataFrame) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['prior_volume_median'] = bars.volume.shift().rolling(20).median()
    bars['relative_volume'] = bars.volume / bars.prior_volume_median

    hourly = resample_closed(minutes, 60)
    hourly['structure_bias'] = _confirmed_structure(hourly)
    bars['structure_bias'] = hourly.structure_bias.reindex(bars.index, method='ffill')
    return _attach_session_boxes(bars)


def compression_breakout_signals(
    bars: pd.DataFrame,
    config: CompressionBreakoutConfig,
) -> list[dict]:
    rows = list(bars.itertuples())
    records: list[dict] = []
    used: set[tuple] = set()

    for side in (1, -1):
        state = None
        for i, row in enumerate(rows):
            cutoff = getattr(row, f'compression_cutoff_{int(config.compression_quantile * 100)}')
            if (row.session is None or not np.isfinite(row.atr)
                    or not np.isfinite(cutoff)):
                state = None
                continue
            setup_id = (row.session_date, row.session, side)
            if setup_id in used:
                state = None
                continue
            boundary = row.box_high if side == 1 else row.box_low

            if state is not None and state['setup_id'] != setup_id:
                state = None
            if state is not None:
                if i - state['breakout_i'] > 4:
                    state = None
                else:
                    deep_failure = side * (row.close - boundary) < -0.35 * row.atr
                    if deep_failure:
                        used.add(setup_id)
                        state = None
                    else:
                        extreme = row.low if side == 1 else row.high
                        close_location = ((row.close - row.low) / max(row.high - row.low, 1e-12)
                                          if side == 1 else
                                          (row.high - row.close) / max(row.high - row.low, 1e-12))
                        retest = (
                            side * (extreme - boundary) <= 0.15 * row.atr
                            and side * (extreme - boundary) >= -0.35 * row.atr
                            and side * (row.close - boundary) > 0
                            and side * (row.close - row.open) > 0
                            and close_location >= 0.65
                        )
                        if retest:
                            entry = float(row.close)
                            raw_stop = (min(row.low, boundary - 0.10 * row.atr) - 0.05 * row.atr
                                        if side == 1 else
                                        max(row.high, boundary + 0.10 * row.atr) + 0.05 * row.atr)
                            risk = side * (entry - raw_stop)
                            if (0.60 * row.atr <= risk <= 1.40 * row.atr
                                    and risk / entry <= 0.0125):
                                records.append({
                                    'timestamp': row.Index,
                                    'side': side,
                                    'reference': entry,
                                    'stop': float(raw_stop),
                                    'atr': float(row.atr),
                                    'score': 0,
                                    'setup': 'compression_breakout_acceptance_retest',
                                    'setup_id': (
                                        f'{row.session_date}:{row.session}:'
                                        f'{"long" if side == 1 else "short"}'
                                    ),
                                })
                                used.add(setup_id)
                                state = None
                                continue

            if state is None:
                candle_range = row.high - row.low
                body_ratio = abs(row.close - row.open) / max(candle_range, 1e-12)
                compressed = row.box_ratio <= cutoff
                breakout = (
                    side * (row.close - boundary) > config.breakout_atr * row.atr
                    and body_ratio >= 0.60
                    and 1.0 * row.atr <= candle_range <= 2.2 * row.atr
                    and side * (row.close - boundary) <= 0.75 * row.atr
                    and row.relative_volume >= 1.20
                    and row.structure_bias == side
                )
                if compressed and breakout:
                    state = {'setup_id': setup_id, 'breakout_i': i}

    records.sort(key=lambda x: x['timestamp'])
    counts = Counter(x['timestamp'] for x in records)
    return [x for x in records if counts[x['timestamp']] == 1]
