"""S10 research strategy: BTC SMT raid -> alt displacement -> OB mitigation.

The implementation deliberately models an ICT/order-block narrative as a
causal state machine instead of a collection of same-bar indicators:

* Asia and London ranges are published only after those ranges have closed.
* A range boundary must first be swept and reclaimed.
* A later alt candle must displace in the opposite direction and break the
  micro structure that was frozen at the raid.
* The last opposing alt candle inside that exact event is the only eligible
  order block.  Entry is its first maker mitigation; unrelated historical OBs
  and FVGs are never mixed into the setup.
* A session/side setup can be emitted only once, preventing repeated trades on
  one persistent sweep/FVG.

This module is research-only.  It has no database or exchange dependency and
does not register a live strategy.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class LiquidityDeliveryConfig:
    name: str
    minutes: int = 15
    target_r: float = 2.50
    max_hold_minutes: int = 120
    min_sweep_atr: float = 0.10
    max_sweep_atr: float = 1.00
    displacement_atr: float = 0.80
    max_displacement_bars: int = 3
    ob_entry_fraction: float = 0.50
    leverage: float = 20.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=self.minutes,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=True,
            trail_atr=1.10,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=0.003,
            max_notional_equity=0.75,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=self.leverage,
            max_margin_fraction=0.05,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            margin_safety_reserve=0.01,
        )


def liquidity_delivery_variants() -> list[LiquidityDeliveryConfig]:
    """Small neighbourhood around the central ICT-SMT specification."""
    return [
        LiquidityDeliveryConfig(
            name=f'S10_smt_delivery_5m_disp{int(displacement * 100)}_ce{int(ce * 100)}',
            minutes=5,
            displacement_atr=displacement,
            ob_entry_fraction=ce,
        )
        for displacement in (0.7, 0.8, 0.9)
        for ce in (0.4, 0.5, 0.6)
    ]


def _publish_session_ranges(bars: pd.DataFrame) -> pd.DataFrame:
    """Attach frozen ICT session ranges using New-York local time and DST.

    For a local trading date, the London window receives the completed
    20:00-02:00 ET Asian range.  The New-York window receives the completed
    02:00-07:00 ET London range.  Values are written only inside the consuming
    kill zone, so a later row can never leak back into an earlier decision.
    """
    result = bars.copy()
    for column in ('source_high', 'source_low'):
        result[column] = np.nan
    result['session'] = None
    result['session_date'] = None

    local = result.index.tz_convert('America/New_York')
    dates = sorted(set(local.date))
    for local_date in dates:
        midnight = pd.Timestamp(local_date, tz='America/New_York')
        asia_start = midnight - pd.Timedelta(hours=4)  # prior day 20:00 ET
        london_open = midnight + pd.Timedelta(hours=2)
        london_close = midnight + pd.Timedelta(hours=5)
        ny_open = midnight + pd.Timedelta(hours=7)
        ny_close = midnight + pd.Timedelta(hours=10)

        asia = result.loc[(result.index > asia_start.tz_convert('UTC'))
                          & (result.index <= london_open.tz_convert('UTC'))]
        london_source = result.loc[(result.index > london_open.tz_convert('UTC'))
                                   & (result.index <= ny_open.tz_convert('UTC'))]

        if not asia.empty:
            mask = ((result.index >= london_open.tz_convert('UTC'))
                    & (result.index < london_close.tz_convert('UTC')))
            result.loc[mask, 'source_high'] = float(asia.high.max())
            result.loc[mask, 'source_low'] = float(asia.low.min())
            result.loc[mask, 'session'] = 'london'
            result.loc[mask, 'session_date'] = str(local_date)

        if not london_source.empty:
            mask = ((result.index >= ny_open.tz_convert('UTC'))
                    & (result.index < ny_close.tz_convert('UTC')))
            result.loc[mask, 'source_high'] = float(london_source.high.max())
            result.loc[mask, 'source_low'] = float(london_source.low.min())
            result.loc[mask, 'session'] = 'new_york'
            result.loc[mask, 'session_date'] = str(local_date)

    return result


def liquidity_delivery_features(minutes: pd.DataFrame, interval: int) -> pd.DataFrame:
    bars = resample_closed(minutes, interval)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['delta_ratio'] = ((2 * bars.taker_buy_volume - bars.volume)
                           / bars.volume.replace(0, np.nan))
    volume_window = max(24, int(8 * 60 / interval))
    bars['relative_volume'] = (
        bars.volume / bars.volume.shift().rolling(volume_window).median())
    bars['prior_high3'] = bars.high.shift().rolling(3).max()
    bars['prior_low3'] = bars.low.shift().rolling(3).min()

    higher = resample_closed(minutes, 60)
    higher['ema20'] = talib.EMA(higher.close.to_numpy(), 20)
    higher['ema50'] = talib.EMA(higher.close.to_numpy(), 50)
    higher['bias'] = np.where(
        (higher.close > higher.ema20) & (higher.ema20 > higher.ema50)
        & (higher.ema20 > higher.ema20.shift(2)), 1,
        np.where(
            (higher.close < higher.ema20) & (higher.ema20 < higher.ema50)
            & (higher.ema20 < higher.ema20.shift(2)), -1, 0))
    higher['adx'] = talib.ADX(
        higher.high.to_numpy(), higher.low.to_numpy(), higher.close.to_numpy(), 14)
    bars['htf_bias'] = higher.bias.reindex(bars.index, method='ffill')
    bars['htf_adx'] = higher.adx.reindex(bars.index, method='ffill')
    return _publish_session_ranges(bars)


def _session_context(row) -> tuple[str, str, float, float] | None:
    if (row.session is None or not np.isfinite(row.source_high)
            or not np.isfinite(row.source_low)):
        return None
    return row.session, row.session_date, float(row.source_low), float(row.source_high)


def liquidity_delivery_signals(
    bars: pd.DataFrame,
    btc_bars: pd.DataFrame,
    config: LiquidityDeliveryConfig,
) -> list[dict]:
    """Emit causal SMT setups where BTC raids and the traded alt diverges."""
    aligned_btc = btc_bars.reindex(bars.index)
    rows = list(bars.itertuples())
    btc_rows = list(aligned_btc.itertuples())
    records: list[dict] = []

    for side in (1, -1):
        state = None
        used: set[tuple] = set()
        for i, (row, btc) in enumerate(zip(rows, btc_rows)):
            context = _session_context(row)
            btc_context = _session_context(btc)
            if (context is None or btc_context is None
                    or context[:2] != btc_context[:2]
                    or not np.isfinite(row.atr) or row.atr <= 0
                    or not np.isfinite(btc.atr) or btc.atr <= 0):
                state = None
                continue

            session, session_date, range_low, range_high = context
            _, _, btc_range_low, btc_range_high = btc_context
            setup_id = (session_date, session, side)
            if setup_id in used:
                state = None
                continue

            btc_level = btc_range_low if side == 1 else btc_range_high
            alt_level = range_low if side == 1 else range_high
            opposite = range_high if side == 1 else range_low
            btc_extreme = float(btc.low if side == 1 else btc.high)
            alt_extreme = float(row.low if side == 1 else row.high)
            close_location = ((row.close - row.low) / max(row.high - row.low, 1e-12)
                              if side == 1 else
                              (row.high - row.close) / max(row.high - row.low, 1e-12))

            if state is not None and state['setup_id'] != setup_id:
                state = None

            if state is not None:
                expired = i - state['sweep_i'] > config.max_displacement_bars
                state['alt_anchor'] = min(state['alt_anchor'], row.low) if side == 1 else max(
                    state['alt_anchor'], row.high)
                invalidated = side * (row.close - state['alt_anchor']) < -0.10 * row.atr
                if expired or invalidated:
                    state = None
                else:
                    body = side * (row.close - row.open)
                    displaced = (
                        body >= config.displacement_atr * row.atr
                        and (row.high - row.low) >= 1.20 * row.atr
                        and close_location >= 0.75
                        and side * (row.close - state['break_level']) > 0
                    )
                    if displaced and i >= 2:
                        gap_bottom, gap_top = (
                            (float(rows[i - 2].high), float(row.low)) if side == 1
                            else (float(row.high), float(rows[i - 2].low)))
                        gap_width = gap_top - gap_bottom
                        has_fvg = 0.10 * row.atr <= gap_width <= 0.60 * row.atr

                        opposing = None
                        for j in range(i - 1, state['sweep_i'] - 1, -1):
                            candidate = rows[j]
                            if side * (candidate.close - candidate.open) < 0:
                                opposing = candidate
                                break

                        if opposing is not None:
                            if side == 1:
                                ob_bottom, ob_top = float(opposing.low), float(opposing.open)
                            else:
                                ob_bottom, ob_top = float(opposing.open), float(opposing.high)
                            if ob_top <= ob_bottom:
                                continue
                            entry = ob_bottom + config.ob_entry_fraction * (ob_top - ob_bottom)
                            stop = state['alt_anchor'] - side * 0.10 * row.atr
                            risk = side * (entry - stop)
                            boundary_target = opposite - side * 0.05 * row.atr
                            room_r = side * (boundary_target - entry) / max(risk, 1e-12)
                            target_r = min(config.target_r, room_r)
                            target = entry + side * target_r * risk
                            stop_pct = risk / max(entry, 1e-12)
                            estimated_cost_pct = 0.0002 + 0.0005 + 0.0002
                            cost_fraction_of_r = estimated_cost_pct / max(stop_pct, 1e-12)
                            if (0.5 * row.atr <= risk <= 1.8 * row.atr
                                    and target_r >= 1.5
                                    and cost_fraction_of_r <= 0.45):
                                raid_id = f'{session_date}:{session}:{"long" if side == 1 else "short"}'
                                records.append({
                                    'timestamp': row.Index,
                                    'side': side,
                                    'reference': float(row.close),
                                    'stop': float(stop),
                                    'atr': float(row.atr),
                                    'limit_price': float(entry),
                                    'limit_ttl_minutes': min(60, 3 * config.minutes),
                                    'target_price': float(target),
                                    'target_boundary': float(opposite),
                                    'min_target_r': 1.5,
                                    'score': 5,
                                    'setup': 'btc_smt_raid_first_ob_mitigation',
                                    'setup_id': f'{raid_id}:{bars.attrs.get("symbol", "alt")}',
                                    'raid_id': raid_id,
                                    'selection_score': float(target_r / cost_fraction_of_r),
                                    'swept_level': float(state['btc_level']),
                                    'sweep_extreme': float(state['btc_anchor']),
                                    'fvg': ([float(gap_bottom), float(gap_top)]
                                            if has_fvg else None),
                                    'order_block': [ob_bottom, ob_top],
                                })
                                used.add(setup_id)
                                state = None
                                continue

            if state is None:
                sweep_depth = -side * (btc_extreme - btc_level)
                reclaimed = side * (btc.close - btc_level) > 0
                alt_non_confirmation = side * (alt_extreme - alt_level) >= 0.05 * row.atr
                break_level = row.prior_high3 if side == 1 else row.prior_low3
                if (config.min_sweep_atr * btc.atr <= sweep_depth
                        <= config.max_sweep_atr * btc.atr
                        and reclaimed and alt_non_confirmation
                        and np.isfinite(break_level)):
                    state = {
                        'setup_id': setup_id,
                        'sweep_i': i,
                        'btc_anchor': btc_extreme,
                        'btc_level': btc_level,
                        'alt_anchor': alt_extreme,
                        'break_level': float(break_level),
                    }

    records.sort(key=lambda x: x['timestamp'])
    counts = Counter(x['timestamp'] for x in records)
    return [x for x in records if counts[x['timestamp']] == 1]
