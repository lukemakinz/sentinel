"""S68: daily cross-sectional momentum SOL vs XRP.

Always long the stronger 20-day return and short the weaker.
Not directional turtle (S64) and not a single-symbol breakout (S67).
One pair per UTC day, 1.5 ATR stops, 24h hold, two slots, $15/leg.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


PAIR = ('SOLUSDT', 'XRPUSDT')


@dataclass(frozen=True)
class CrossSectionMomConfig:
    name: str = 'S68_xs_mom_20'
    lookback: int = 20
    min_spread: float = 0.03
    stop_atr_mult: float = 1.50
    target_r: float = 8.0
    max_hold_minutes: int = 1440

    def __post_init__(self):
        if (self.lookback != 20 or self.min_spread != 0.03
                or self.stop_atr_mult <= 0 or self.target_r < 8
                or self.max_hold_minutes != 1440):
            raise ValueError('Invalid S68 cross-section configuration')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=0.06,
            max_notional_equity=4.0,
            daily_loss_fraction=0.14,
            weekly_loss_fraction=0.22,
            drawdown_halt_fraction=0.28,
            drawdown_risk_scale_fraction=0.16,
            max_positions=2,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=0.5,
            leverage=5.0,
            max_margin_fraction=0.25,
            margin_safety_reserve=0.01,
            maker_fee_bps=5.0,
            limit_penetration_bps=0.0,
            fixed_margin_usd=None,
            fixed_risk_usd=15.0,
        )


def cross_section_features(minutes: pd.DataFrame, config: CrossSectionMomConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 1440)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['mom'] = bars.close.pct_change(config.lookback)
    return bars


def generate_cross_section_signals(
    bars_by_symbol: dict,
    config: CrossSectionMomConfig,
) -> dict:
    sol = bars_by_symbol['SOLUSDT']
    xrp = bars_by_symbol['XRPUSDT']
    out = {'SOLUSDT': [], 'XRPUSDT': []}
    for timestamp in sol.index.intersection(xrp.index):
        sol_row, xrp_row = sol.loc[timestamp], xrp.loc[timestamp]
        sol_mom, xrp_mom = float(sol_row.mom), float(xrp_row.mom)
        if not np.isfinite(sol_mom) or not np.isfinite(xrp_mom):
            continue
        spread = sol_mom - xrp_mom
        if abs(spread) < config.min_spread:
            continue
        assignment = {
            'SOLUSDT': (1 if spread > 0 else -1, sol_row),
            'XRPUSDT': (-1 if spread > 0 else 1, xrp_row),
        }
        legs = {}
        ok = True
        for symbol, (side, row) in assignment.items():
            local_atr = float(row.atr)
            if not np.isfinite(local_atr) or local_atr <= 0:
                ok = False
                break
            stop = float(row.close) - side * config.stop_atr_mult * local_atr
            if side * (row.close - stop) <= 0:
                ok = False
                break
            direction = 'long' if side == 1 else 'short'
            legs[symbol] = {
                'timestamp': timestamp,
                'side': side,
                'reference': float(row.close),
                'stop': float(stop),
                'atr': local_atr,
                'min_stop_atr': 0.5,
                'max_stop_atr': 8.0,
                'score': min(10, max(1, int(abs(spread) * 80))),
                'setup': 'xs_mom_20',
                'setup_id': f'S68:xs:{symbol}:{direction}:{timestamp.isoformat()}',
            }
        if ok:
            for symbol, signal in legs.items():
                out[symbol].append(signal)
    return out
