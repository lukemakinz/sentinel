"""H3 Double Sweep Divergence v1 — causal range-reversal research strategy.

The edge hypothesis is a liquidity trap, not the visual M/W shape alone:
the second confirmed swing narrowly sweeps the first, closes back inside,
regular RSI divergence shows non-confirmation, and price then breaks the
intervening neckline.  Entry is a limit retest of that neckline.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class H3DoubleSweepConfig:
    name: str = 'H3_DOUBLE_SWEEP_DIVERGENCE_V1'
    swing_width: int = 2
    minimum_separation_bars: int = 6
    maximum_separation_bars: int = 32
    minimum_sweep_atr: float = 0.03
    maximum_sweep_atr: float = 0.35
    minimum_rsi_divergence: float = 3.0
    bullish_first_rsi_maximum: float = 35.0
    bearish_first_rsi_minimum: float = 65.0
    mss_window_bars: int = 4
    mss_break_atr: float = 0.03
    h1_adx_maximum: float = 25.0
    h4_adx_maximum: float = 30.0
    stop_buffer_atr: float = 0.15
    minimum_stop_pct: float = 0.60
    maximum_stop_pct: float = 1.25
    first_entry_hour_utc: int = 6
    last_entry_hour_utc: int = 18
    limit_ttl_minutes: int = 30
    target_r: float = 1.50

    def __post_init__(self) -> None:
        if self.swing_width < 1:
            raise ValueError('H3 swing width must be positive')
        if not 2 * self.swing_width < self.minimum_separation_bars <= self.maximum_separation_bars:
            raise ValueError('Invalid H3 swing separation')
        if not 0 < self.minimum_sweep_atr < self.maximum_sweep_atr < 1:
            raise ValueError('Invalid H3 sweep geometry')
        if self.minimum_rsi_divergence <= 0 or self.mss_window_bars < 1:
            raise ValueError('Invalid H3 divergence/MSS contract')
        if not 0 < self.minimum_stop_pct < self.maximum_stop_pct:
            raise ValueError('Invalid H3 stop contract')
        if not 0 <= self.first_entry_hour_utc < self.last_entry_hour_utc <= 24:
            raise ValueError('Invalid H3 session')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=0.75,
            partial_fraction=0.0,
            trailing=False,
            max_hold_minutes=240,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            weekly_loss_fraction=0.018,
            drawdown_risk_scale_fraction=0.04,
            drawdown_halt_fraction=0.06,
            fee_bps=5.0,
            maker_fee_bps=2.0,
            slippage_bps=2.0,
            limit_penetration_bps=2.0,
            min_reward_cost_ratio=6.0,
            leverage=3.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
            max_positions=1,
        )


def build_h3_features(minutes: pd.DataFrame) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    close = bars.close.to_numpy(float)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(float), bars.low.to_numpy(float), close, timeperiod=14,
    )
    bars['rsi'] = talib.RSI(close, timeperiod=14)
    for interval, label in ((60, 'h1'), (240, 'h4')):
        higher = resample_closed(minutes, interval)
        higher['adx'] = talib.ADX(
            higher.high.to_numpy(float), higher.low.to_numpy(float),
            higher.close.to_numpy(float), timeperiod=14,
        )
        bars[f'{label}_adx'] = higher.adx.reindex(bars.index, method='ffill')
    return bars


def _confirmed_pivots(values: np.ndarray, width: int, *, lows: bool) -> list[tuple[int, int]]:
    """Return (pivot index, confirmation index); never backdate knowledge."""
    pivots = []
    for known in range(2 * width, len(values)):
        pivot = known - width
        neighbours = np.r_[values[pivot - width:pivot], values[pivot + 1:known + 1]]
        is_pivot = values[pivot] < neighbours.min() if lows else values[pivot] > neighbours.max()
        if is_pivot:
            pivots.append((pivot, known))
    return pivots


def generate_h3_signals(
    bars: pd.DataFrame,
    config: H3DoubleSweepConfig,
    symbol: str,
) -> list[dict]:
    low = bars.low.to_numpy(float)
    high = bars.high.to_numpy(float)
    close = bars.close.to_numpy(float)
    open_ = bars.open.to_numpy(float)
    atr = bars.atr.to_numpy(float)
    rsi = bars.rsi.to_numpy(float)
    records = []

    def scan(side: int, pivots: list[tuple[int, int]]) -> None:
        for pair_index in range(1, len(pivots)):
            first, _ = pivots[pair_index - 1]
            second, known = pivots[pair_index]
            separation = second - first
            if not config.minimum_separation_bars <= separation <= config.maximum_separation_bars:
                continue
            if not (np.isfinite(atr[second]) and np.isfinite(rsi[first]) and np.isfinite(rsi[second])):
                continue

            if side == 1:
                sweep = (low[first] - low[second]) / atr[second]
                divergence = rsi[second] - rsi[first]
                trapped = close[second] > low[first]
                oscillator_extreme = rsi[first] <= config.bullish_first_rsi_maximum
                neckline = float(high[first + 1:second].max())
            else:
                sweep = (high[second] - high[first]) / atr[second]
                divergence = rsi[first] - rsi[second]
                trapped = close[second] < high[first]
                oscillator_extreme = rsi[first] >= config.bearish_first_rsi_minimum
                neckline = float(low[first + 1:second].min())
            if not (
                config.minimum_sweep_atr <= sweep <= config.maximum_sweep_atr
                and divergence >= config.minimum_rsi_divergence
                and trapped and oscillator_extreme
            ):
                continue

            last = min(len(bars) - 1, known + config.mss_window_bars)
            mss = None
            for i in range(known, last + 1):
                if not np.isfinite(atr[i]):
                    continue
                break_ok = (
                    close[i] >= neckline + config.mss_break_atr * atr[i] and close[i] > open_[i]
                    if side == 1
                    else close[i] <= neckline - config.mss_break_atr * atr[i] and close[i] < open_[i]
                )
                range_regime = (
                    bars.h1_adx.iloc[i] <= config.h1_adx_maximum
                    and bars.h4_adx.iloc[i] <= config.h4_adx_maximum
                )
                if break_ok and range_regime:
                    mss = i
                    break
            if mss is None:
                continue
            timestamp = bars.index[mss]
            if not config.first_entry_hour_utc <= timestamp.hour < config.last_entry_hour_utc:
                continue

            stop = (
                low[second] - config.stop_buffer_atr * atr[mss]
                if side == 1
                else high[second] + config.stop_buffer_atr * atr[mss]
            )
            risk = side * (neckline - stop)
            risk_pct = risk / neckline * 100.0
            if not config.minimum_stop_pct <= risk_pct <= config.maximum_stop_pct:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': timestamp,
                'side': side,
                'limit_price': neckline,
                'limit_ttl_minutes': config.limit_ttl_minutes,
                'reference': float(close[mss]),
                'stop': float(stop),
                'atr': float(atr[mss]),
                'min_stop_atr': 0.5,
                'max_stop_atr': 4.0,
                'min_target_r': config.target_r,
                'score': 10,
                'setup': 'h3_double_sweep_divergence_v1',
                'setup_id': f'H3DSD:v1:{symbol}:{direction}:{timestamp.isoformat()}',
                'evidence': {
                    'first_pivot': bars.index[first].isoformat(),
                    'second_pivot': bars.index[second].isoformat(),
                    'pivot_known_at': bars.index[known].isoformat(),
                    'sweep_atr': round(float(sweep), 4),
                    'rsi_divergence': round(float(divergence), 2),
                    'neckline': neckline,
                    'risk_pct_at_limit': round(float(risk_pct), 4),
                    'h1_adx': round(float(bars.h1_adx.iloc[mss]), 2),
                    'h4_adx': round(float(bars.h4_adx.iloc[mss]), 2),
                },
            })

    scan(1, _confirmed_pivots(low, config.swing_width, lows=True))
    scan(-1, _confirmed_pivots(high, config.swing_width, lows=False))
    records.sort(key=lambda row: row['timestamp'])
    counts = Counter(row['timestamp'] for row in records)
    return [row for row in records if counts[row['timestamp']] == 1]
