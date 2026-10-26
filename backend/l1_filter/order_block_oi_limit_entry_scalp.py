"""S21: S20's entry confirmation (order block + OBV + OI, patient exit)
unchanged, except the fill mechanism — a resting LIMIT order at the order
block's 50% ("OTE"-style) instead of a market order at next open. Classic
SMC execution: don't chase the zone once it's already been touched, rest an
order inside it and let price come to you. This directly targets S20's
diagnosed weakness (PF collapses under cost stress) two ways at once: maker
fee (2bps) instead of taker (5bps), and a better average entry price, which
widens the realized R on every trade that fills without touching the entry
signal, win rate, or exit management at all.

Route 'limit_entry' (H1) keeps S20's all-day trading. Route
'limit_entry_killzone' (H2) additionally restricts entries to the London/NY
liquidity windows already used and tested by S13
(bollinger_regime_scalp._in_trading_window) — an ICT selectivity filter:
fewer, higher-quality fills, which also improves the fee/edge ratio.

Routes 'limit_entry_concession' and 'limit_entry_concession_killzone' are a
corrected second attempt: the first attempt (H1/H2 above) priced the resting
limit at the OB zone's fixed 50% midpoint, which — since it is only placed
AFTER the zone has already been touched and started reclaiming — usually
demanded price retrace even further than it already had, deep into the zone,
before filling. That produced very few fills (17/6mo, versus S20's 137) and
those few were disproportionately bad (price that keeps diving that deep
past a reaction is more likely still falling than bouncing). The corrected
routes instead ask for a small, ATR-scaled concession relative to the price
already observed at the touch bar (limit_concession_atr, default 0.25x ATR)
— still a genuine, non-marketable resting order that captures the maker fee
and a better average price than chasing at market, but a realistic ask
instead of a deep, unlikely retracement.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .bollinger_regime_scalp import _in_trading_window
from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class OrderBlockLimitEntryConfig:
    name: str
    route: str  # 'limit_entry' or 'limit_entry_killzone'
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20
    zone_ttl_bars: int = 32
    stop_buffer_atr_mult: float = 0.15
    obv_ema_period: int = 9
    oi_lookback_bars: int = 8
    ote_ratio: float = 0.5
    limit_concession_atr: float = 0.25
    limit_ttl_minutes: int = 45
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0

    def __post_init__(self):
        if self.route not in ('limit_entry', 'limit_entry_killzone',
                              'limit_entry_concession', 'limit_entry_concession_killzone'):
            raise ValueError('Unknown order block limit-entry route')
        if (self.ema_period < 2 or self.ema_slope_lookback < 1 or self.adx_threshold <= 0
                or self.displacement_atr_mult <= 0 or self.volume_mult <= 0
                or self.volume_avg_lookback < 2 or self.zone_ttl_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.obv_ema_period < 1
                or self.oi_lookback_bars < 1 or not 0 < self.ote_ratio < 1
                or self.limit_concession_atr <= 0
                or self.limit_ttl_minutes < 1 or self.partial_r <= 0
                or self.trail_atr <= 0 or self.target_r <= self.partial_r):
            raise ValueError('Invalid order block limit-entry parameters')

    def execution(self) -> ScalpConfig:
        # Identical to S20's exit management on purpose — isolates the entry
        # fill-mechanism change as the only variable.
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=self.partial_r,
            partial_fraction=0.0,
            trailing=True,
            trail_atr=self.trail_atr,
            max_hold_minutes=240,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=5.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
        )


def central_variants() -> list[OrderBlockLimitEntryConfig]:
    """S21's original (broken-timing) hypotheses; kept for the historical
    record of that protocol run. Exactly two; no parameter grid."""
    return [
        OrderBlockLimitEntryConfig('S21_ob_oi_limit_entry', 'limit_entry'),
        OrderBlockLimitEntryConfig('S21_ob_oi_limit_entry_killzone', 'limit_entry_killzone'),
    ]


def corrected_variants() -> list[OrderBlockLimitEntryConfig]:
    """S21c: the corrected fill-mechanism hypotheses (ATR concession instead
    of the OB zone's fixed 50% midpoint). Exactly two; no parameter grid."""
    return [
        OrderBlockLimitEntryConfig('S21c_ob_oi_limit_concession', 'limit_entry_concession'),
        OrderBlockLimitEntryConfig('S21c_ob_oi_limit_concession_killzone',
                                   'limit_entry_concession_killzone'),
    ]


def limit_entry_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                         config: OrderBlockLimitEntryConfig) -> pd.DataFrame:
    """S17's order-block/regime/OBV features plus causal OI-change — same
    construction as S18's oi_features, kept local so this module does not
    depend on order_block_oi_confirmation_scalp's execution defaults."""
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)
    return bars


def generate_limit_entry_signals(bars: pd.DataFrame, config: OrderBlockLimitEntryConfig,
                                  symbol: str) -> list[dict]:
    """Same zone bookkeeping and confirmation (regime + structure + OBV + OI)
    as S18/S20's first-touch trigger, but the resulting order is a resting
    limit at the zone's OTE level instead of a market fill — the simulator's
    existing pending-order logic (backtest.cluster_scalp_simulator) decides
    whether/when it actually fills."""
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
    ob_bull_confirmed = bars.ob_bull_confirmed.to_numpy()
    ob_bull_top, ob_bull_bottom = bars.ob_bull_top.to_numpy(), bars.ob_bull_bottom.to_numpy()
    ob_bear_confirmed = bars.ob_bear_confirmed.to_numpy()
    ob_bear_top, ob_bear_bottom = bars.ob_bear_top.to_numpy(), bars.ob_bear_bottom.to_numpy()

    active = {1: [], -1: []}
    records = []
    for i in range(n):
        active[1] = [z for z in active[1] if z['expires'] > i]
        active[-1] = [z for z in active[-1] if z['expires'] > i]

        if ob_bull_confirmed[i] and np.isfinite(ob_bull_top[i]) and np.isfinite(ob_bull_bottom[i]):
            active[1].append({'top': float(ob_bull_top[i]), 'bottom': float(ob_bull_bottom[i]),
                              'expires': i + config.zone_ttl_bars})
        if ob_bear_confirmed[i] and np.isfinite(ob_bear_top[i]) and np.isfinite(ob_bear_bottom[i]):
            active[-1].append({'top': float(ob_bear_top[i]), 'bottom': float(ob_bear_bottom[i]),
                               'expires': i + config.zone_ttl_bars})

        if not np.isfinite(atr[i]):
            continue
        if (config.route in ('limit_entry_killzone', 'limit_entry_concession_killzone')
                and not _in_trading_window(bars.index[i])):
            continue

        for side in (1, -1):
            if side == 1:
                touched = [z for z in active[1] if low[i] <= z['top'] and close[i] >= z['bottom']]
            else:
                touched = [z for z in active[-1] if high[i] >= z['bottom'] and close[i] <= z['top']]
            if not touched:
                continue
            for z in touched:
                active[side].remove(z)

            regime_ok = htf_trend_up[i] if side == 1 else htf_trend_down[i]
            if not (regime_ok and htf_adx[i] >= config.adx_threshold):
                continue
            flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue
            if not np.isfinite(oi_change[i]):
                continue
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue

            zone = touched[0]
            if config.route in ('limit_entry_concession', 'limit_entry_concession_killzone'):
                # A small, realistic ask relative to the price already
                # observed at the touch bar, not the zone's fixed midpoint.
                limit_price = close[i] - side * config.limit_concession_atr * atr[i]
                # Never ask for a price outside the zone itself.
                limit_price = (max(limit_price, zone['bottom']) if side == 1
                              else min(limit_price, zone['top']))
            else:
                limit_price = zone['bottom'] + config.ote_ratio * (zone['top'] - zone['bottom'])
            stop = (zone['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                    else zone['top'] + config.stop_buffer_atr_mult * atr[i])
            risk = side * (limit_price - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': bars.index[i],
                'side': side,
                'reference': float(close[i]),
                'limit_price': float(limit_price),
                'limit_ttl_minutes': config.limit_ttl_minutes,
                'stop': float(stop),
                'min_stop_atr': 0.5,
                'max_stop_atr': 3.0,
                'atr': float(atr[i]),
                'score': 6,
                'setup': f'order_block_limit_entry_{config.route}',
                'setup_id': (
                    f'OBLE:v1:{config.route}:{symbol}:{direction}:{bars.index[i].isoformat()}'
                ),
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
