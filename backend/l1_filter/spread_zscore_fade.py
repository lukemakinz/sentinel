"""S69 H1: fade an extreme SOL/XRP log-spread z-score.

Opposite of S68 (long the winner) and of XSM-28 (weekly momentum).
Rolling 60-day beta, 20-day z-score. |z| >= 2: short the rich leg, long the cheap leg.
2 ATR stops, 3-day hold, two slots, $15 per leg.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class SpreadZscoreConfig:
    name: str = 'S69_spread_zscore'
    beta_window: int = 60
    z_window: int = 20
    entry_z: float = 2.0
    stop_atr_mult: float = 2.0
    target_r: float = 8.0
    max_hold_days: int = 3

    def __post_init__(self):
        if (self.beta_window != 60 or self.z_window != 20 or self.entry_z != 2.0
                or self.stop_atr_mult != 2.0 or self.target_r < 8
                or self.max_hold_days != 3):
            raise ValueError('Invalid S69 spread configuration')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_days * 1440,
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


def spread_zscore_features(
    sol_minutes: pd.DataFrame,
    xrp_minutes: pd.DataFrame,
    config: SpreadZscoreConfig,
) -> dict:
    sol = resample_closed(sol_minutes, 1440)
    xrp = resample_closed(xrp_minutes, 1440)
    joined = sol[['close']].join(xrp[['close']], lsuffix='_sol', rsuffix='_xrp', how='inner')
    log_sol = np.log(joined.close_sol)
    log_xrp = np.log(joined.close_xrp)
    ret_sol, ret_xrp = log_sol.diff(), log_xrp.diff()
    cov = ret_sol.rolling(config.beta_window).cov(ret_xrp)
    var = ret_xrp.rolling(config.beta_window).var()
    beta = cov / var.replace(0, np.nan)
    spread = log_sol - beta * log_xrp
    mu = spread.rolling(config.z_window).mean()
    sigma = spread.rolling(config.z_window).std()
    z = (spread - mu) / sigma.replace(0, np.nan)
    frames = {}
    for symbol, source, close_col in (
        ('SOLUSDT', sol, 'close_sol'),
        ('XRPUSDT', xrp, 'close_xrp'),
    ):
        close = source.close.to_numpy()
        frame = source.copy()
        frame['atr'] = talib.ATR(source.high.to_numpy(), source.low.to_numpy(), close, 14)
        frame['z'] = z.reindex(frame.index)
        frame['close'] = joined[close_col].reindex(frame.index)
        frames[symbol] = frame
    return frames


def generate_spread_zscore_signals(
    bars_by_symbol: dict,
    config: SpreadZscoreConfig,
) -> dict:
    sol = bars_by_symbol['SOLUSDT']
    xrp = bars_by_symbol['XRPUSDT']
    out = {'SOLUSDT': [], 'XRPUSDT': []}
    for timestamp in sol.index.intersection(xrp.index):
        z = float(sol.loc[timestamp, 'z'])
        if not np.isfinite(z) or abs(z) < config.entry_z:
            continue
        # Positive z: SOL rich versus XRP -> short SOL, long XRP.
        sides = {'SOLUSDT': -1 if z > 0 else 1, 'XRPUSDT': 1 if z > 0 else -1}
        legs = {}
        ok = True
        for symbol, side in sides.items():
            row = bars_by_symbol[symbol].loc[timestamp]
            local_atr = float(row.atr)
            if not np.isfinite(local_atr) or local_atr <= 0:
                ok = False
                break
            stop = float(row.close) - side * config.stop_atr_mult * local_atr
            if side * (float(row.close) - stop) <= 0:
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
                'score': min(10, max(1, int(abs(z) * 2))),
                'setup': 'spread_zscore',
                'setup_id': f'S69:z:{symbol}:{direction}:{timestamp.isoformat()}',
            }
        if ok:
            for symbol, signal in legs.items():
                out[symbol].append(signal)
    return out
