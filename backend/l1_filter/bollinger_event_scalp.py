"""S14 research candidates: BB regime plus causal PA/ICT/OB event sequencing."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .bollinger_regime_scalp import (
    BollingerRouteConfig,
    _in_trading_window,
    bollinger_features,
)
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class BollingerEventConfig:
    name: str
    route: str
    min_confirmations: int

    def __post_init__(self):
        allowed = {
            'squeeze_event_ob': 4,
            'liquidity_mss': 3,
        }
        if self.route not in allowed or self.min_confirmations != allowed[self.route]:
            raise ValueError('Only the frozen central event configurations are allowed')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=2.0,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            max_hold_minutes=120 if self.route == 'squeeze_event_ob' else 90,
            risk_fraction=0.002,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=5.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
        )


def event_variants() -> list[BollingerEventConfig]:
    return [
        BollingerEventConfig('S14_bb_squeeze_event_ob', 'squeeze_event_ob', 4),
        BollingerEventConfig('S14_bb_liquidity_mss', 'liquidity_mss', 3),
    ]


def _confirmed_pivots(bars: pd.DataFrame, width=2) -> tuple[pd.Series, pd.Series]:
    """Last 2-left/2-right pivot, published on its confirmation bar."""
    known_high = np.full(len(bars), np.nan)
    known_low = np.full(len(bars), np.nan)
    last_high = last_low = np.nan
    highs, lows = bars.high.to_numpy(), bars.low.to_numpy()
    for known in range(width * 2, len(bars)):
        pivot = known - width
        if highs[pivot] == np.max(highs[pivot - width:pivot + width + 1]):
            last_high = highs[pivot]
        if lows[pivot] == np.min(lows[pivot - width:pivot + width + 1]):
            last_low = lows[pivot]
        known_high[known] = last_high
        known_low[known] = last_low
    return pd.Series(known_high, index=bars.index), pd.Series(known_low, index=bars.index)


def _structure_bias(hourly: pd.DataFrame) -> pd.Series:
    result = np.zeros(len(hourly), dtype=int)
    swing_highs, swing_lows = [], []
    highs, lows = hourly.high.to_numpy(), hourly.low.to_numpy()
    for known in range(4, len(hourly)):
        pivot = known - 2
        if highs[pivot] == np.max(highs[pivot - 2:pivot + 3]):
            swing_highs.append(highs[pivot])
        if lows[pivot] == np.min(lows[pivot - 2:pivot + 3]):
            swing_lows.append(lows[pivot])
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            if swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]:
                result[known] = 1
            elif swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]:
                result[known] = -1
        if result[known] == 0:
            result[known] = result[known - 1]
    return pd.Series(result, index=hourly.index)


def bollinger_event_features(minutes: pd.DataFrame) -> pd.DataFrame:
    base = BollingerRouteConfig('S14_features', 'squeeze_expansion')
    bars = bollinger_features(minutes, base)
    pivot_high, pivot_low = _confirmed_pivots(bars)
    # A pivot confirmed using the sweep candle was not known before the sweep.
    bars['pivot_high_prior'] = pivot_high.shift(1)
    bars['pivot_low_prior'] = pivot_low.shift(1)
    bars['prior_four_high'] = bars.high.shift(1).rolling(4, min_periods=4).max()
    bars['prior_four_low'] = bars.low.shift(1).rolling(4, min_periods=4).min()
    prior_bandwidth = bars.bb_bandwidth.shift(1).rolling(4, min_periods=4).median()
    bars['bandwidth_expansion_25'] = bars.bb_bandwidth >= 1.25 * prior_bandwidth
    hourly = resample_closed(minutes, 60)
    hourly['structure_bias'] = _structure_bias(hourly)
    bars['structure_bias_1h'] = hourly.structure_bias.reindex(
        bars.index, method='ffill').fillna(0).astype(int)
    return bars


def _candidate_payload(route, setup_id, confirmations, hard, **signal):
    confirmations = {key: bool(value) for key, value in confirmations.items()}
    hard = {key: bool(value) for key, value in hard.items()}
    passed = sum(confirmations.values())
    return {
        **signal,
        'score': passed,
        'setup': route,
        'setup_id': setup_id,
        'shadow_only': True,
        'evidence': {
            'hard_conditions': hard,
            'confirmations': confirmations,
            'passed_confirmations': passed,
            'total_confirmations': len(confirmations),
            'ai_authority': 'APPROVE_OR_REJECT_ONLY',
        },
    }


def squeeze_event_ob_signals(
    bars: pd.DataFrame,
    btc: pd.DataFrame,
    config: BollingerEventConfig,
    symbol: str,
) -> list[dict]:
    """Squeeze -> box/band release -> first mitigation of the exact event OB."""
    if config.route != 'squeeze_event_ob':
        raise ValueError('Wrong route config')
    btc = btc.reindex(bars.index)
    rows = list(bars.itertuples())
    records, consumed = [], set()
    last_squeeze_i = None
    episode_start = None
    for i, row in enumerate(rows):
        if bool(row.squeeze_state):
            if last_squeeze_i is None or i - last_squeeze_i > 1:
                episode_start = row.Index
            last_squeeze_i = i
        elif last_squeeze_i is not None and i - last_squeeze_i > 4:
            episode_start = None
        if (episode_start is None or episode_start in consumed or i < 5
                or not _in_trading_window(row.Index)):
            continue
        btc_row = btc.loc[row.Index]
        if not all(np.isfinite(value) for value in (
            row.atr, row.bb_upper_prior, row.bb_lower_prior,
            row.prior_four_high, row.prior_four_low, row.relative_volume,
            btc_row.bb_middle_prior,
        )) or row.prior_squeeze_count < 3:
            continue
        for side in (1, -1):
            band = row.bb_upper_prior if side == 1 else row.bb_lower_prior
            box = row.prior_four_high if side == 1 else row.prior_four_low
            hard_breakout = (
                side * (row.close - band) > 0
                and side * (row.close - box) >= 0.10 * row.atr
            )
            if not hard_breakout:
                continue
            opposing = [j for j in range(max(0, i - 5), i)
                        if side * (rows[j].close - rows[j].open) < 0]
            if not opposing:
                continue
            ob = rows[opposing[-1]]
            distal = ob.low if side == 1 else ob.high
            proximal = ob.open
            ob_width = abs(proximal - distal)
            if ob_width <= 0 or ob_width > row.atr:
                continue
            entry = (proximal + distal) / 2
            stop = distal - 0.10 * row.atr if side == 1 else distal + 0.10 * row.atr
            risk = side * (entry - stop)
            if not 0.35 * row.atr <= risk <= 1.50 * row.atr:
                consumed.add(episode_start)
                continue
            candle_range = row.high - row.low
            body_ratio = abs(row.close - row.open) / max(candle_range, 1e-12)
            confirmations = {
                'range_at_least_1_3_atr': candle_range >= 1.30 * row.atr,
                'body_at_least_70pct': body_ratio >= 0.70,
                'relative_volume_at_least_1_25': row.relative_volume >= 1.25,
                'bandwidth_expands_25pct': bool(row.bandwidth_expansion_25),
                'btc_directional_regime': side * (btc_row.close - btc_row.bb_middle_prior) > 0,
                'confirmed_1h_structure': row.structure_bias_1h == side,
            }
            if sum(confirmations.values()) < config.min_confirmations:
                continue
            hard = {
                'prior_squeeze_3_of_4': True,
                'breaks_frozen_box_and_prior_bb': True,
                'exact_event_order_block': True,
                'fixed_risk_geometry': True,
            }
            records.append(_candidate_payload(
                'bb_squeeze_event_ob',
                f'BBSEO:v1:{symbol}:{episode_start.isoformat()}',
                confirmations, hard,
                timestamp=row.Index, side=side, reference=float(row.close),
                limit_price=float(entry), limit_ttl_minutes=45,
                stop=float(stop), min_stop_atr=0.35, max_stop_atr=1.50,
                atr=float(row.atr), min_target_r=1.50,
            ))
            consumed.add(episode_start)
            break
    return records


def liquidity_mss_signals(
    bars: pd.DataFrame,
    btc: pd.DataFrame,
    config: BollingerEventConfig,
    symbol: str,
) -> list[dict]:
    """Session/BB failure -> cumulative SMT -> later MSS/displacement candidate."""
    if config.route != 'liquidity_mss':
        raise ValueError('Wrong route config')
    btc = btc.reindex(bars.index)
    rows = list(bars.itertuples())
    records = []
    for side in (1, -1):
        state = None
        consumed, btc_confirmed = set(), set()
        for i, row in enumerate(rows):
            if row.session is None or not _in_trading_window(row.Index):
                state = None
                continue
            btc_row = btc.loc[row.Index]
            key = (row.session_date, row.session, side)
            if all(np.isfinite(value) for value in (btc_row.atr, btc_row.box_low, btc_row.box_high)):
                btc_box = btc_row.box_low if side == 1 else btc_row.box_high
                btc_extreme = btc_row.low if side == 1 else btc_row.high
                if side * (btc_extreme - btc_box) < -0.05 * btc_row.atr:
                    btc_confirmed.add(key)
            if state is not None and state['key'] != key:
                state = None
            if state is not None:
                state['extreme'] = (min(state['extreme'], row.low) if side == 1
                                    else max(state['extreme'], row.high))
                if key in btc_confirmed or i > state['expires_i']:
                    state = None
                else:
                    box = row.box_low if side == 1 else row.box_high
                    if side * (row.close - box) <= 0:
                        state = None
                    else:
                        pivot = state['pivot']
                        mss = np.isfinite(pivot) and side * (row.close - pivot) > 0
                        if mss:
                            candle_range = row.high - row.low
                            body_ratio = abs(row.close - row.open) / max(candle_range, 1e-12)
                            close_location = ((row.close - row.low) / max(candle_range, 1e-12)
                                              if side == 1 else
                                              (row.high - row.close) / max(candle_range, 1e-12))
                            fvg = False
                            if i >= 2:
                                fvg = (row.low - rows[i - 2].high >= 0.03 * row.atr if side == 1
                                       else rows[i - 2].low - row.high >= 0.03 * row.atr)
                            confirmations = {
                                'range_at_least_1_2_atr': candle_range >= 1.20 * row.atr,
                                'body_at_least_70pct': body_ratio >= 0.70,
                                'close_in_outer_20pct': close_location >= 0.80,
                                'exact_displacement_fvg': fvg,
                                'bandwidth_expands_25pct': bool(row.bandwidth_expansion_25),
                                'confirmed_1h_structure': row.structure_bias_1h == side,
                            }
                            if sum(confirmations.values()) >= config.min_confirmations:
                                if fvg:
                                    entry = ((rows[i - 2].high + row.low) / 2 if side == 1
                                             else (rows[i - 2].low + row.high) / 2)
                                else:
                                    entry = (row.open + row.close) / 2
                                stop = (state['extreme'] - 0.10 * state['atr'] if side == 1
                                        else state['extreme'] + 0.10 * state['atr'])
                                risk = side * (entry - stop)
                                opposite = row.box_high if side == 1 else row.box_low
                                boundary_target = opposite - side * 0.05 * row.atr
                                two_r = entry + side * 2.0 * risk
                                target = min(two_r, boundary_target) if side == 1 else max(two_r, boundary_target)
                                reward = side * (target - entry)
                                if (0.50 * row.atr <= risk <= 1.80 * row.atr
                                        and reward >= 1.50 * risk):
                                    hard = {
                                        'session_and_prior_bb_sweep_reclaim': True,
                                        'cumulative_btc_smt': True,
                                        'later_preknown_pivot_mss': True,
                                        'fixed_risk_geometry': True,
                                    }
                                    records.append(_candidate_payload(
                                        'bb_liquidity_mss', state['setup_id'],
                                        confirmations, hard,
                                        timestamp=row.Index, side=side, reference=float(row.close),
                                        limit_price=float(entry), limit_ttl_minutes=30,
                                        stop=float(stop), target_price=float(target),
                                        min_target_r=1.50, min_stop_atr=0.50,
                                        max_stop_atr=1.80, atr=float(row.atr),
                                    ))
                            state = None
                            continue
            if state is not None or key in consumed or key in btc_confirmed:
                continue
            pivot = row.pivot_high_prior if side == 1 else row.pivot_low_prior
            box = row.box_low if side == 1 else row.box_high
            band = row.bb_lower_prior if side == 1 else row.bb_upper_prior
            extreme = row.low if side == 1 else row.high
            required = all(np.isfinite(value) for value in (
                row.atr, pivot, box, band, row.hourly_bandwidth,
                row.hourly_bandwidth_extreme_cutoff,
            )) and not row.hourly_bandwidth_extreme
            sweep = required and side * (extreme - box) < -0.05 * row.atr
            outside_band = required and side * (extreme - band) < -0.05 * row.atr
            reclaim = required and side * (row.close - box) > 0 and side * (row.close - band) > 0
            directional = side * (row.close - row.open) > 0
            if sweep and outside_band and reclaim and directional:
                consumed.add(key)
                state = {
                    'key': key, 'sweep_i': i, 'expires_i': i + 4,
                    'extreme': extreme, 'atr': row.atr, 'pivot': pivot,
                    'setup_id': (
                        f'BBLMSS:v1:{symbol}:{"long" if side == 1 else "short"}:'
                        f'{row.session}:{row.session_date}:{row.Index.isoformat()}'
                    ),
                }
    records.sort(key=lambda item: item['timestamp'])
    return records


def generate_bollinger_event_signals(bars, btc, config, symbol):
    if config.route == 'squeeze_event_ob':
        return squeeze_event_ob_signals(bars, btc, config, symbol)
    return liquidity_mss_signals(bars, btc, config, symbol)
