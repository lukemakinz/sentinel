"""S40: 4H extreme oversold/overbought mean reversion -- fewer, larger
trades, deliberately different in shape from every 15m order-block route
(S16-S37) and the liquidation-cascade routes (S38/S39): entry is not
conditioned on any structure, flow, or forced-deleveraging signature at
all, only on price/momentum being at a genuine statistical extreme on the
4H timeframe. Wide stop beyond the recent 4H swing extreme, patient
breakeven+chandelier exit reused unmodified from S20 H1 (the one execution
style anywhere in this project with any track record).

Two independent, standard definitions of "extreme" are tested as the two
frozen hypotheses: H1 uses 4H RSI(14) beyond 20/80 (a stricter, rarer tier
than the conventional 30/70; 10/90 was tried first in a pre-freeze
correctness check and never fired even once on BTC/ETH/XRP over the whole
development window, so it was loosened one standard tier before any
performance data was examined -- disclosed, not a result-driven choice),
H2 uses a 20-period Bollinger z-score beyond +-2.5 sigma (a genuinely rare
price-distance extreme). Universe is widened to 8 liquid pairs (BTC/ETH/BNB/SOL/XRP/
ADA/SUI/DOGE) instead of the 3-6 used by prior scalp routes, since this
signal fires rarely per symbol and more independent symbols are needed to
reach a meaningful fill count -- not a change to the entry logic itself.
No open-interest or funding features are used (pure price/momentum), so
no metrics archive is required.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class HTFExtremeReversionConfig:
    name: str
    route: str  # 'rsi_extreme' or 'bb_extreme'
    rsi_period: int = 14
    rsi_oversold: float = 20.0
    rsi_overbought: float = 80.0
    bb_period: int = 20
    bb_extreme_z: float = 2.5
    swing_lookback_bars: int = 6
    stop_buffer_atr_mult: float = 0.25
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0

    def __post_init__(self):
        if self.route not in ('rsi_extreme', 'bb_extreme'):
            raise ValueError('Unknown HTF extreme reversion route')
        if (self.rsi_period < 2 or not 0 < self.rsi_oversold < 50
                or not 50 < self.rsi_overbought < 100 or self.bb_period < 5
                or self.bb_extreme_z <= 0 or self.swing_lookback_bars < 2
                or self.stop_buffer_atr_mult < 0
                or self.partial_r <= 0 or self.partial_r >= self.target_r
                or self.trail_atr <= 0):
            raise ValueError('Invalid HTF extreme reversion parameters')

    def execution(self) -> ScalpConfig:
        # Identical exit model to S20 H1 on purpose. max_hold_minutes is
        # widened to 3 days: a 4H-timeframe reversion needs far more room
        # than the 4h cap used by every 15m-entry route in this project.
        return ScalpConfig(
            name=self.name, minutes=15, target_r=self.target_r, partial_r=self.partial_r,
            partial_fraction=0.0, trailing=True, trail_atr=self.trail_atr,
            max_hold_minutes=4320, risk_fraction=0.0020, max_notional_equity=0.50,
            daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
            min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
            margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
            fixed_margin_usd=25.0, fixed_risk_usd=0.50,
        )


def central_variants() -> list[HTFExtremeReversionConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        HTFExtremeReversionConfig('S40_htf_reversion_rsi', 'rsi_extreme'),
        HTFExtremeReversionConfig('S40_htf_reversion_bb', 'bb_extreme'),
    ]


def htf_extreme_features(minutes: pd.DataFrame, config: HTFExtremeReversionConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 240)
    high, low, close = bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy()
    bars['atr'] = talib.ATR(high, low, close, timeperiod=14)
    bars['rsi'] = talib.RSI(close, timeperiod=config.rsi_period)

    mean = bars.close.rolling(config.bb_period, min_periods=config.bb_period).mean()
    std = bars.close.rolling(config.bb_period, min_periods=config.bb_period).std()
    bars['bb_zscore'] = (bars.close - mean) / std.where(std > 0)

    n = config.swing_lookback_bars
    bars['swing_low'] = bars.low.shift(1).rolling(n, min_periods=n).min()
    bars['swing_high'] = bars.high.shift(1).rolling(n, min_periods=n).max()
    return bars


def generate_htf_extreme_signals(bars: pd.DataFrame, config: HTFExtremeReversionConfig,
                                  symbol: str) -> list[dict]:
    n = len(bars)
    atr = bars.atr.to_numpy()
    close = bars.close.to_numpy()
    rsi = bars.rsi.to_numpy()
    bb_zscore = bars.bb_zscore.to_numpy()
    swing_low, swing_high = bars.swing_low.to_numpy(), bars.swing_high.to_numpy()

    records = []
    for i in range(n):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        if not np.isfinite(swing_low[i]) or not np.isfinite(swing_high[i]):
            continue

        if config.route == 'rsi_extreme':
            if not np.isfinite(rsi[i]):
                continue
            oversold, overbought = rsi[i] <= config.rsi_oversold, rsi[i] >= config.rsi_overbought
        else:
            if not np.isfinite(bb_zscore[i]):
                continue
            oversold = bb_zscore[i] <= -config.bb_extreme_z
            overbought = bb_zscore[i] >= config.bb_extreme_z

        if not (oversold or overbought):
            continue
        side = 1 if oversold else -1

        reference = float(close[i])
        stop = (swing_low[i] - config.stop_buffer_atr_mult * atr[i] if side == 1
                else swing_high[i] + config.stop_buffer_atr_mult * atr[i])
        risk = side * (reference - stop)
        if risk <= 0:
            continue

        direction = 'long' if side == 1 else 'short'
        timestamp = bars.index[i]
        records.append({
            'timestamp': timestamp, 'side': side, 'reference': reference,
            'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 6.0,
            'atr': float(atr[i]), 'score': 6,
            'setup': f'htf_extreme_reversion_{config.route}',
            'setup_id': f'HER:v1:{config.route}:{symbol}:{direction}:{timestamp.isoformat()}',
        })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
