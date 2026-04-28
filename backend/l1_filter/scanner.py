"""L1Scanner: orchestrates all 15 gates and produces TradeContext."""
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from analysts.base import Bias
from analysts.momentum import compute_connors_rsi
from .gates_a import check_killzone, check_htf_trend, check_btc_correlation, check_funding_rate, check_adx
from .gates_b import check_liquidity_sweep, check_fvg_ob, check_premium_discount, check_atr_squeeze
from .gates_c import (
    check_choch, check_momentum_divergence, check_ema_crossover,
    check_volume_spike, check_vwap, check_obv_confirmation, check_price_action_trigger,
)
from .utils import compute_atr, compute_ema
from .mtf import build_top_down_context
from .models import L1Result

MIN_B_PASS = 2   # B1+B2 mandatory = core SMC setup (additional gates = optional confirmation)
MIN_C_PASS = 1   # base threshold; S1 uses stricter trigger confirmation below


def _check_htf_bos(candles_4h: list, direction: str) -> bool:
    """Check if HTF (4H) has a confirmed Break of Structure in the given direction.
    CHoCH on LTF without HTF BOS = false signal."""
    if len(candles_4h) < 15:
        return True  # insufficient data → don't block
    try:
        import numpy as np
        from analysts.structure import detect_swing_points, detect_structure_break
        highs  = np.array([c['high']  for c in candles_4h])
        lows   = np.array([c['low']   for c in candles_4h])
        swings = detect_swing_points(highs, lows, lookback=3)
        struct = detect_structure_break(swings)
        if struct is None:
            return False
        if direction == 'LONG'  and struct['direction'] == 'bullish':
            return True
        if direction == 'SHORT' and struct['direction'] == 'bearish':
            return True
        return False
    except Exception:
        return True  # on error, don't block


class L1Scanner:
    def scan(self, symbol: str, now: datetime = None, strategy: str | None = 'S1') -> Optional[dict]:
        if now is None:
            now = datetime.now(timezone.utc)

        candles_1d  = self._get_candles(symbol, '1d',  250)
        candles_4h  = self._get_candles(symbol, '4h',  100)
        candles_1h  = self._get_candles(symbol, '1h',  100)
        candles_15m = self._get_candles(symbol, '15m', 100)

        # A2 first — determines direction for all other gates
        a2_passed, a2_data = check_htf_trend(candles_1d)
        if not a2_passed:
            self._save(symbol, '', False, {}, {}, {})
            return None

        direction = a2_data['direction']
        mtf_context = build_top_down_context(candles_1d, candles_4h, candles_1h, candles_15m)

        btc_candles = self._get_candles('BTCUSDT', '1h', 50) if symbol != 'BTCUSDT' else candles_1h
        funding     = self._get_latest_funding_rate(symbol)

        a1_passed, a1_data = check_killzone(now)
        post_ny_continuation = 16 <= now.hour < 18
        session_window = 'ny_continuation' if post_ny_continuation else a1_data.get('session')

        a3_passed, a3_data = check_btc_correlation(btc_candles, direction, symbol, symbol_candles=candles_1h)
        a4_passed, a4_data = check_funding_rate(funding, direction)
        a5_passed, a5_data = check_adx(candles_1h)

        gates_a = {'A1': a1_passed or post_ny_continuation, 'A2': True, 'A3': a3_passed, 'A4': a4_passed, 'A5': a5_passed}
        strict_a_pass = all(gates_a.values())
        permissive_a_pass = self._passes_permissive_a(strategy, gates_a)

        if not strict_a_pass and not permissive_a_pass:
            self._save(symbol, direction, False, gates_a, {}, {})
            return None

        b1_passed, b1_data = check_liquidity_sweep(candles_1h, direction,
                                                    symbol=symbol, htf_candles=candles_4h)
        b2_passed, b2_data = check_fvg_ob(candles_15m, direction)
        b3_passed, b3_data = check_premium_discount(candles_1h, direction, htf_candles=candles_4h)
        # B4 (classical patterns) removed — redundant with B1+B2, adds noise
        b5_passed, b5_data = check_atr_squeeze(candles_1h)

        gates_b = {'B1': b1_passed, 'B2': b2_passed, 'B3': b3_passed, 'B5': b5_passed}

        s1_candidates = self._get_s1_candidates(
            b1_passed, b1_data, b2_passed, b3_passed, b5_passed,
            session_window=session_window, mtf_context=mtf_context
        )
        # C1: CHoCH — HTF BOS is ideal confirmation but not hard requirement.
        # With limited backtest data, relax to accept standalone LTF CHoCH.
        htf_bos = _check_htf_bos(candles_4h, direction)
        c1_passed, c1_data = check_choch(candles_15m, direction,
                                          require_htf_bos=htf_bos)   # soft requirement
        c2_passed, c2_data = check_momentum_divergence(candles_15m, direction, symbol=symbol)
        c3_passed, c3_data = check_ema_crossover(candles_15m, direction)
        c4_passed, c4_data = check_volume_spike(candles_15m)
        c5_passed, c5_data = check_vwap(candles_1h, direction)
        c6_passed, c6_data = check_obv_confirmation(candles_15m, direction)
        c7_passed, c7_data = check_price_action_trigger(candles_15m, direction)

        gates_c = {'C1': c1_passed, 'C2': c2_passed, 'C3': c3_passed, 'C4': c4_passed, 'C5': c5_passed, 'C6': c6_passed, 'C7': c7_passed}

        flow_signal = self._get_volume_flow_signal(symbol, now=now)
        strategy_candidates = self._filter_s1_candidates_by_trigger(s1_candidates, c1_data, gates_c)
        if self._is_s2_candidate(direction, gates_a, gates_b, gates_c, mtf_context, c1_data, flow_signal):
            strategy_candidates.append('S2')
        if self._is_s3_candidate(gates_a, gates_b, gates_c, mtf_context, c1_data, symbol=symbol):
            strategy_candidates.append('S3')
        s4_data = self._get_s4_candidate(symbol, direction, gates_a, gates_c, mtf_context, candles_15m, now)
        if s4_data:
            strategy_candidates.append('S4')
        s5_data = self._get_s5_candidate(symbol, direction, gates_a, gates_c, mtf_context, candles_4h, candles_15m, now)
        if s5_data:
            strategy_candidates.append('S5')
        if not strategy_candidates:
            self._save(symbol, direction, False, gates_a, gates_b, gates_c)
            return None

        selected_strategy = self._select_requested_strategy(strategy, strategy_candidates)
        if selected_strategy is None:
            self._save(symbol, direction, False, gates_a, gates_b, gates_c)
            return None

        selected_direction = direction
        if selected_strategy == 'S5' and s5_data and s5_data.get('direction_override'):
            selected_direction = s5_data['direction_override']

        setup_score = self._score_setup(
            selected_strategy, gates_b, gates_c, mtf_context, b1_data, b2_data, c1_data, flow_signal
        )
        entry_mode = self._infer_entry_mode(selected_strategy, setup_score, mtf_context, c1_data, gates_c)

        adx_val = a5_data.get('adx_value', 0)
        ctx = {
            'symbol':             symbol,
            'timestamp':          now.isoformat(),
            'direction':          selected_direction,
            'current_price':      candles_15m[-1]['close'] if candles_15m else candles_1h[-1]['close'],
            'strategy':           selected_strategy,
            'strategy_candidates': strategy_candidates,
            'setup_profile':      selected_strategy,
            'session_window':     session_window,
            'entry_mode':         entry_mode,
            'setup_score':        setup_score,
            'flow_signal':        flow_signal,
            'gates_a':            gates_a,
            'gates_b':            gates_b,
            'gates_c':            gates_c,
            'mtf_context':        mtf_context,
            'atr':                a5_data.get('atr'),
            'fvg_zone':           b2_data.get('fvg_zone'),
            'entry_ote':          b2_data.get('entry_ote'),
            'fvg_type':           b2_data.get('fvg_type'),
            'fvg_status':         b2_data.get('fvg_status'),
            'fvg_fill_ratio':     b2_data.get('fvg_fill_ratio'),
            'swept_level':        b1_data.get('swept_level'),
            'nearest_liquidity':  b1_data.get('nearest_liquidity'),
            'opening_range_high': s4_data.get('opening_range_high') if s4_data else None,
            'opening_range_low':  s4_data.get('opening_range_low') if s4_data else None,
            'opening_range_mid':  s4_data.get('opening_range_mid') if s4_data else None,
            'opening_range_breakout': s4_data.get('breakout_side') if s4_data else None,
            's5_trigger_high':    s5_data.get('trigger_high') if s5_data else None,
            's5_trigger_low':     s5_data.get('trigger_low') if s5_data else None,
            's5_atr_15m':         s5_data.get('atr_15m') if s5_data else None,
            's5_pullback_depth_atr': s5_data.get('pullback_depth_atr') if s5_data else None,
            's5_reclaim_price':   s5_data.get('reclaim_price') if s5_data else None,
            's5_pullback_len':    s5_data.get('pullback_len') if s5_data else None,
            's5_symbol_profile':  s5_data.get('symbol_profile') if s5_data else None,
            's5_crsi':            s5_data.get('crsi') if s5_data else None,
            's5_crsi_delta':      s5_data.get('crsi_delta') if s5_data else None,
            'btc_trend':          a3_data.get('btc_trend'),
            'funding_rate':       a4_data.get('funding_rate'),
            'daily_vwap':         c5_data.get('vwap'),
            'adx_value':          adx_val,
            'regime':             'trending' if adx_val > 25 else 'weak_trending',
        }
        self._save(symbol, selected_direction, True, gates_a, gates_b, gates_c, ctx)
        return ctx

    @staticmethod
    def _passes_permissive_a(strategy: str | None, gates_a: dict) -> bool:
        if strategy == 'S2':
            return bool(gates_a.get('A1') and gates_a.get('A4') and gates_a.get('A5'))
        if strategy == 'S3':
            return bool(gates_a.get('A1') and gates_a.get('A2') and gates_a.get('A5'))
        if strategy == 'S4':
            return bool(gates_a.get('A1') and gates_a.get('A2') and gates_a.get('A5'))
        if strategy == 'S5':
            return bool(gates_a.get('A2'))
        return False

    @staticmethod
    def _get_s1_candidates(b1_passed: bool, b1_data: dict, b2_passed: bool,
                           b3_passed: bool, b5_passed: bool,
                           session_window: str | None = None,
                           mtf_context: dict | None = None) -> list[str]:
        candidates = []
        mtf_context = mtf_context or {}
        allow_reversal = mtf_context.get('allow_reversal', True)
        allow_continuation = mtf_context.get('allow_continuation', True)
        if session_window == 'ny' and b1_passed and b2_passed and b3_passed and allow_reversal:
            if 'htf_poi_confluence' not in b1_data or b1_data.get('htf_poi_confluence', False):
                candidates.append('S1A')
        if session_window in {'ny', 'ny_continuation'} and b2_passed and (b3_passed or b5_passed) and allow_continuation:
            candidates.append('S1B')
        if session_window in {'ny', 'ny_continuation'} and b1_passed and b2_passed:
            candidates.append('S1C')
        return candidates

    @staticmethod
    def _filter_s1_candidates_by_trigger(strategy_candidates: list[str], c1_data: dict,
                                         gates_c: dict) -> list[str]:
        if not c1_data:
            return []

        filtered = []
        c1_type = c1_data.get('type')
        has_secondary = any(gates_c.get(gate, False) for gate in ('C2', 'C4', 'C5', 'C6', 'C7'))
        has_continuation_confirmation = any(gates_c.get(gate, False) for gate in ('C3', 'C4', 'C5', 'C6', 'C7'))

        for strategy_id in strategy_candidates:
            if strategy_id == 'S1A' and c1_type == 'CHoCH' and has_secondary:
                filtered.append(strategy_id)
            if strategy_id == 'S1B' and c1_type in {'CHoCH', 'BOS', 'BOS_fallback'} and has_continuation_confirmation:
                filtered.append(strategy_id)
            if strategy_id == 'S1C' and c1_type in {'CHoCH', 'BOS', 'BOS_fallback'} and any(
                gates_c.get(gate, False) for gate in ('C3', 'C5', 'C6', 'C7')
            ):
                filtered.append(strategy_id)

        return filtered

    @staticmethod
    def _is_s2_candidate(direction: str, gates_a: dict, gates_b: dict, gates_c: dict,
                         mtf_context: dict, c1_data: dict, flow_signal: dict) -> bool:
        if not (gates_a.get('A1') and gates_a.get('A4') and gates_a.get('A5')):
            return False

        score = float(flow_signal.get('score') or 0.0)
        confidence = float(flow_signal.get('confidence') or 0.0)
        bias = flow_signal.get('bias')
        bias_aligned = (direction == 'LONG' and bias == 'LONG') or (direction == 'SHORT' and bias == 'SHORT')
        if not bias_aligned or confidence < 0.25:
            return False

        if direction == 'LONG' and score < 20:
            return False
        if direction == 'SHORT' and score > -20:
            return False

        trigger_type = c1_data.get('type')
        if trigger_type not in {'CHoCH', 'BOS', 'BOS_fallback'}:
            return False

        mtf_ok = mtf_context.get('allow_continuation', False) and mtf_context.get('state_1h', {}).get('state') != 'counter_trend'
        if not mtf_ok:
            return False

        b_support = gates_b.get('B2') or gates_b.get('B5') or gates_b.get('B3')
        c_confirmations = sum(1 for gate in ('C3', 'C4', 'C5', 'C6', 'C7') if gates_c.get(gate, False))
        impulse_ready = gates_c.get('C7') or (gates_c.get('C4') and gates_c.get('C6'))
        return bool(b_support and impulse_ready and c_confirmations >= 3)

    @staticmethod
    def _is_s3_candidate(gates_a: dict, gates_b: dict, gates_c: dict,
                         mtf_context: dict, c1_data: dict, symbol: str | None = None) -> bool:
        if not (gates_a.get('A1') and gates_a.get('A2') and gates_a.get('A5')):
            return False
        if not mtf_context.get('allow_continuation', False):
            return False
        if mtf_context.get('state_1h', {}).get('state') not in {'aligned_continuation', 'aligned_pullback', 'neutral'}:
            return False
        if symbol in {'BTCUSDT', 'SOLUSDT'}:
            return False
        trigger_type = c1_data.get('type')
        if trigger_type not in {'BOS', 'BOS_fallback', 'CHoCH'}:
            return False
        structure_ready = gates_b.get('B3') or gates_b.get('B2') or gates_b.get('B5')
        trigger_ready = gates_c.get('C7') and (gates_c.get('C3') or gates_c.get('C4') or gates_c.get('C6'))
        return bool(structure_ready and trigger_ready)

    @staticmethod
    def _get_s4_candidate(symbol: str, direction: str, gates_a: dict, gates_c: dict,
                          mtf_context: dict, candles_15m: list, now: datetime) -> dict | None:
        if symbol not in {'BTCUSDT', 'ETHUSDT'}:
            return None
        if not (gates_a.get('A1') and gates_a.get('A2') and gates_a.get('A5')):
            return None
        if mtf_context.get('state_1h', {}).get('state') == 'counter_trend':
            return None
        if not candles_15m or len(candles_15m) < 8:
            return None
        if now.hour < 14:
            return None

        day_candles = [
            c for c in candles_15m
            if c.get('timestamp') and c['timestamp'].date() == now.date() and c['timestamp'] <= now
        ]
        opening_range = [
            c for c in day_candles
            if c['timestamp'].hour == 13 and c['timestamp'].minute in {0, 15}
        ]
        if len(opening_range) < 2:
            return None
        if len(day_candles) < 2:
            return None

        range_high = max(c['high'] for c in opening_range)
        range_low = min(c['low'] for c in opening_range)
        range_mid = (range_high + range_low) / 2
        opening_range_size = range_high - range_low
        last = day_candles[-1]
        prev = day_candles[-2]
        breakout_up = last['close'] > range_high and prev['close'] <= range_high
        breakout_down = last['close'] < range_low and prev['close'] >= range_low
        recent_atr = compute_atr(candles_15m[-20:], period=14)
        atr_ref = float(recent_atr[-1]) if recent_atr else 0.0
        if atr_ref <= 0:
            return None
        avg_volume = sum(float(c.get('volume', 0.0)) for c in day_candles[:-1][-8:]) / max(len(day_candles[:-1][-8:]), 1)
        breakout_volume_ratio = float(last.get('volume', 0.0)) / max(avg_volume, 1e-9)
        narrow_range = opening_range_size / atr_ref < 0.85
        c_confirmations = sum(1 for gate in ('C4', 'C5', 'C6', 'C7') if gates_c.get(gate, False))
        if direction == 'LONG' and breakout_up and gates_c.get('C7') and c_confirmations >= 2 and breakout_volume_ratio > 1.4 and narrow_range:
            return {
                'opening_range_high': range_high,
                'opening_range_low': range_low,
                'opening_range_mid': range_mid,
                'breakout_side': 'LONG',
                'breakout_volume_ratio': breakout_volume_ratio,
                'opening_range_atr_ratio': opening_range_size / atr_ref,
            }
        if direction == 'SHORT' and breakout_down and gates_c.get('C7') and c_confirmations >= 2 and breakout_volume_ratio > 1.4 and narrow_range:
            return {
                'opening_range_high': range_high,
                'opening_range_low': range_low,
                'opening_range_mid': range_mid,
                'breakout_side': 'SHORT',
                'breakout_volume_ratio': breakout_volume_ratio,
                'opening_range_atr_ratio': opening_range_size / atr_ref,
            }
        return None

    @staticmethod
    def _get_s5_candidate(symbol: str, direction: str, gates_a: dict, gates_c: dict,
                          mtf_context: dict, candles_4h: list, candles_15m: list, now: datetime) -> dict | None:
        if symbol not in {'BTCUSDT', 'ETHUSDT'}:
            return None
        if not gates_a.get('A2'):
            return None
        if not (13 <= now.hour < 19):
            return None
        if len(candles_4h) < 55 or len(candles_15m) < 25:
            return None

        closes_4h = [float(c['close']) for c in candles_4h]
        ema9 = compute_ema(closes_4h, 9)
        ema21 = compute_ema(closes_4h, 21)
        ema50 = compute_ema(closes_4h, 50)
        if not (ema9 and ema21 and ema50):
            return None
        if ema9[-1] > ema21[-1] > ema50[-1]:
            local_direction = 'LONG'
        elif ema9[-1] < ema21[-1] < ema50[-1]:
            local_direction = 'SHORT'
        else:
            return None

        atr_series = compute_atr(candles_15m[-30:], period=14)
        atr_15m = float(atr_series[-1]) if atr_series else 0.0
        if atr_15m <= 0:
            return None
        current_price = float(candles_15m[-1]['close'])
        if atr_15m / max(current_price, 1e-9) < 0.0025:
            return None

        closes_15m = [float(c['close']) for c in candles_15m]
        ema9_15m = compute_ema(closes_15m, 9)
        ema21_15m = compute_ema(closes_15m, 21)
        ema50_15m = compute_ema(closes_15m, 50)
        crsi_15m = compute_connors_rsi(closes_15m, rsi_period=3, streak_rsi_period=2, rank_period=20)
        if not (ema9_15m and ema21_15m and ema50_15m):
            return None
        if len(crsi_15m) < 2:
            return None

        profile = {
            'BTCUSDT': {
                'touch_atr': 0.35, 'max_depth_atr': 1.00, 'min_pullback': 2, 'vol_ratio': 1.00,
                'crsi_long_min': 18.0, 'crsi_long_max': 58.0, 'crsi_short_min': 42.0, 'crsi_short_max': 82.0, 'crsi_delta': 2.0,
            },
            'ETHUSDT': {
                'touch_atr': 0.45, 'max_depth_atr': 1.35, 'min_pullback': 3, 'vol_ratio': 1.10,
                'crsi_long_min': 20.0, 'crsi_long_max': 62.0, 'crsi_short_min': 38.0, 'crsi_short_max': 84.0, 'crsi_delta': 1.5,
            },
        }[symbol]

        rebound = candles_15m[-1]
        avg_volume = sum(float(c['volume']) for c in candles_15m[-21:-1]) / max(len(candles_15m[-21:-1]), 1)
        volume_ok = float(rebound['volume']) >= avg_volume * profile['vol_ratio']
        if not volume_ok:
            return None
        current_crsi = float(crsi_15m[-1])
        previous_crsi = float(crsi_15m[-2])
        crsi_delta = current_crsi - previous_crsi

        if local_direction == 'LONG':
            crsi_ok = (
                profile['crsi_long_min'] <= current_crsi <= profile['crsi_long_max']
                and crsi_delta >= profile['crsi_delta']
            )
        else:
            crsi_ok = (
                profile['crsi_short_min'] <= current_crsi <= profile['crsi_short_max']
                and crsi_delta <= -profile['crsi_delta']
            )
        if not crsi_ok:
            return None

        correction = None
        depth = None
        pullback_len = 0
        ema21_value = float(ema21_15m[-1])
        recent_low = float(min(c['low'] for c in candles_15m[-3:]))
        recent_high = float(max(c['high'] for c in candles_15m[-3:]))

        for window in range(profile['min_pullback'], 7):
            candidate = candles_15m[-(window + 1):-1]
            if len(candidate) < window:
                continue
            pullback_high = max(float(c['high']) for c in candidate)
            pullback_low = min(float(c['low']) for c in candidate)
            candidate_depth = pullback_high - pullback_low
            if candidate_depth > profile['max_depth_atr'] * atr_15m:
                continue

            last_candidate_close = float(candidate[-1]['close'])
            first_candidate_close = float(candidate[0]['close'])

            if local_direction == 'LONG':
                bearish_bodies = sum(1 for c in candidate if float(c['close']) < float(c['open']))
                ema_touch = (
                    pullback_low <= ema21_value + profile['touch_atr'] * atr_15m
                    or abs(last_candidate_close - ema21_value) <= 0.6 * atr_15m
                )
                trend_ok = ema9_15m[-1] > ema21_15m[-1] > ema50_15m[-1] and current_price > ema21_value
                reclaim_ok = float(rebound['close']) > ema21_value and float(rebound['close']) > float(rebound['open'])
                if bearish_bodies >= max(2, window - 1) and ema_touch and trend_ok and reclaim_ok:
                    correction = candidate
                    depth = candidate_depth
                    pullback_len = window
                    break
            else:
                bullish_bodies = sum(1 for c in candidate if float(c['close']) > float(c['open']))
                ema_touch = (
                    pullback_high >= ema21_value - profile['touch_atr'] * atr_15m
                    or abs(last_candidate_close - ema21_value) <= 0.6 * atr_15m
                )
                trend_ok = ema9_15m[-1] < ema21_15m[-1] < ema50_15m[-1] and current_price < ema21_value
                reclaim_ok = float(rebound['close']) < ema21_value and float(rebound['close']) < float(rebound['open'])
                if bullish_bodies >= max(2, window - 1) and ema_touch and trend_ok and reclaim_ok:
                    correction = candidate
                    depth = candidate_depth
                    pullback_len = window
                    break

        if not correction or depth is None:
            state_1h = mtf_context.get('state_1h', {}).get('state')
            prev = candles_15m[-2]
            if local_direction == 'LONG':
                continuation_ok = state_1h in {'aligned_continuation', 'aligned_pullback'}
                reclaim_ok = float(rebound['close']) > ema21_value and float(rebound['close']) > float(rebound['open'])
                timing_ok = float(prev['low']) <= ema21_value + 0.45 * atr_15m and float(prev['close']) <= ema9_15m[-1]
                if continuation_ok and reclaim_ok and timing_ok:
                    correction = [prev]
                    depth = max(float(prev['high']) - float(prev['low']), 0.35 * atr_15m)
                    pullback_len = 1
                else:
                    return None
            else:
                continuation_ok = state_1h in {'aligned_continuation', 'aligned_pullback'}
                reclaim_ok = float(rebound['close']) < ema21_value and float(rebound['close']) < float(rebound['open'])
                timing_ok = float(prev['high']) >= ema21_value - 0.45 * atr_15m and float(prev['close']) >= ema9_15m[-1]
                if continuation_ok and reclaim_ok and timing_ok:
                    correction = [prev]
                    depth = max(float(prev['high']) - float(prev['low']), 0.35 * atr_15m)
                    pullback_len = 1
                else:
                    return None

        if local_direction == 'LONG':
            trigger_low = recent_low
            trigger_high = float(rebound['high'])
        else:
            trigger_low = float(rebound['low'])
            trigger_high = recent_high

        return {
            'trigger_high': trigger_high,
            'trigger_low': trigger_low,
            'atr_15m': atr_15m,
            'pullback_depth_atr': depth / atr_15m,
            'pullback_len': pullback_len,
            'direction_override': local_direction,
            'reclaim_price': float(rebound['close']),
            'symbol_profile': symbol,
            'crsi': current_crsi,
            'crsi_delta': crsi_delta,
        }

    @staticmethod
    def _select_requested_strategy(strategy: str | None, strategy_candidates: list[str]) -> str | None:
        if not strategy_candidates:
            return None
        if strategy in (None, 'S1'):
            if 'S1A' in strategy_candidates:
                return 'S1A'
            if 'S1C' in strategy_candidates:
                return 'S1C'
            if 'S1B' in strategy_candidates:
                return 'S1B'
            return strategy_candidates[0]
        return strategy if strategy in strategy_candidates else None

    @staticmethod
    def _score_setup(strategy_id: str, gates_b: dict, gates_c: dict, mtf_context: dict,
                     b1_data: dict, b2_data: dict, c1_data: dict, flow_signal: dict | None = None) -> int:
        score = 0
        flow_signal = flow_signal or {}
        if strategy_id == 'S2':
            score += 2 if abs(float(flow_signal.get('score') or 0.0)) >= 35 else 1 if abs(float(flow_signal.get('score') or 0.0)) >= 20 else 0
            score += 1 if float(flow_signal.get('confidence') or 0.0) >= 0.4 else 0
            score += 1 if gates_b.get('B2') else 0
            score += 1 if gates_b.get('B5') else 0
            score += 1 if gates_b.get('B3') else 0
            score += 1 if gates_c.get('C3') else 0
            score += 1 if gates_c.get('C4') else 0
            score += 1 if gates_c.get('C5') else 0
            score += 1 if gates_c.get('C6') else 0
            score += 2 if gates_c.get('C7') else 0
            score += 1 if mtf_context.get('timing_15m', {}).get('divergence_aligned') else 0
            return score
        if strategy_id == 'S3':
            score += 1 if gates_b.get('B2') else 0
            score += 2 if gates_b.get('B3') else 0
            score += 1 if gates_b.get('B5') else 0
            score += 1 if c1_data.get('type') in {'BOS', 'BOS_fallback'} else 2 if c1_data.get('type') == 'CHoCH' else 0
            score += 1 if gates_c.get('C3') else 0
            score += 1 if gates_c.get('C4') else 0
            score += 1 if gates_c.get('C5') else 0
            score += 1 if gates_c.get('C6') else 0
            score += 2 if gates_c.get('C7') else 0
            score += 1 if mtf_context.get('state_1h', {}).get('state') == 'aligned_continuation' else 0
            return score
        if strategy_id == 'S4':
            score += 2 if gates_c.get('C7') else 0
            score += 1 if gates_c.get('C4') else 0
            score += 1 if gates_c.get('C5') else 0
            score += 1 if gates_c.get('C6') else 0
            score += 1 if mtf_context.get('state_1h', {}).get('state') == 'aligned_continuation' else 0
            return score
        if strategy_id == 'S5':
            score += 2 if gates_c.get('C7') else 0
            score += 1 if gates_c.get('C4') else 0
            score += 1 if gates_c.get('C5') else 0
            score += 1 if gates_c.get('C6') else 0
            score += 2 if mtf_context.get('state_1h', {}).get('state') == 'aligned_pullback' else 1 if mtf_context.get('state_1h', {}).get('state') == 'aligned_continuation' else 0
            return score

        if strategy_id == 'S1A':
            score += 2 if gates_b.get('B1') else 0
        else:
            sweep_type = b1_data.get('sweep_type')
            score += 1 if sweep_type else 0

        score += 1 if gates_b.get('B2') else 0
        fvg_status = b2_data.get('fvg_status')
        if fvg_status == 'fresh':
            score += 1
        score += 1 if gates_b.get('B3') else 0
        score += 1 if gates_b.get('B5') else 0
        score += 2 if c1_data.get('type') == 'CHoCH' else 1 if c1_data.get('type') in {'BOS', 'BOS_fallback'} else 0
        score += 1 if gates_c.get('C2') else 0
        score += 1 if gates_c.get('C3') else 0
        score += 1 if gates_c.get('C4') else 0
        score += 1 if gates_c.get('C5') else 0
        score += 1 if gates_c.get('C6') else 0
        score += 1 if gates_c.get('C7') else 0
        score += 1 if mtf_context.get('state_4h', {}).get('divergence_aligned') else 0
        score += 1 if mtf_context.get('timing_15m', {}).get('divergence_aligned') else 0
        return score

    @staticmethod
    def _infer_entry_mode(strategy_id: str, setup_score: int, mtf_context: dict,
                          c1_data: dict, gates_c: dict) -> str:
        if strategy_id == 'S1A':
            return 'LIMIT'
        if strategy_id == 'S1C':
            return 'HYBRID' if setup_score >= 6 else 'LIMIT'
        if strategy_id == 'S2':
            if gates_c.get('C7') and (gates_c.get('C4') or gates_c.get('C6')):
                return 'MARKET'
            return 'HYBRID'
        if strategy_id == 'S3':
            if gates_c.get('C7') and gates_c.get('C4'):
                return 'MARKET'
            return 'HYBRID'
        if strategy_id == 'S4':
            if setup_score >= 5 and gates_c.get('C4') and gates_c.get('C6'):
                return 'HYBRID'
            return 'MARKET'
        if strategy_id == 'S5':
            return 'MARKET'

        trigger_type = c1_data.get('type')
        strong_impulse = trigger_type in {'CHoCH', 'BOS'} and gates_c.get('C7') and (gates_c.get('C5') or gates_c.get('C6'))
        timing_ready = mtf_context.get('timing_15m', {}).get('divergence_aligned', False)
        if strong_impulse and (timing_ready or setup_score >= 7):
            return 'HYBRID'
        if trigger_type in {'BOS', 'BOS_fallback'} and setup_score >= 5:
            return 'LIMIT'
        return 'MARKET'

    def _get_candles(self, symbol: str, interval: str, limit: int) -> list:
        from ingester.models import Candle
        qs = (Candle.objects
              .filter(symbol=symbol, interval=interval, is_closed=True)
              .order_by('-timestamp')[:limit])
        return [
            {'open': float(c.open), 'high': float(c.high),
             'low':  float(c.low),  'close': float(c.close), 'volume': float(c.volume),
             'timestamp': c.timestamp}   # needed for Judas Swing filter
            for c in reversed(list(qs))
        ]

    def _get_latest_funding_rate(self, symbol: str) -> float:
        from ingester.models import FundingRate
        try:
            fr = FundingRate.objects.filter(symbol=symbol).latest('timestamp')
            return float(fr.funding_rate)
        except FundingRate.DoesNotExist:
            return 0.0

    def _get_volume_flow_signal(self, symbol: str, now: datetime | None = None) -> dict:
        try:
            from datetime import timedelta
            from ingester.models import Candle, FundingRate, OpenInterest

            now = now or datetime.now(timezone.utc)

            candles_5m = list(
                Candle.objects.filter(
                    symbol=symbol, interval='5m', is_closed=True,
                    timestamp__lte=now, timestamp__gte=now - timedelta(hours=4),
                ).order_by('timestamp').values('volume', 'taker_buy_volume')
            )
            candles_15m = list(
                Candle.objects.filter(
                    symbol=symbol, interval='15m', is_closed=True,
                    timestamp__lte=now, timestamp__gte=now - timedelta(hours=8),
                ).order_by('timestamp').values('close', 'volume')
            )
            funding_rates = list(
                FundingRate.objects.filter(
                    symbol=symbol,
                    timestamp__lte=now, timestamp__gte=now - timedelta(days=3),
                ).order_by('timestamp').values_list('funding_rate', flat=True)
            )
            oi_values = list(
                OpenInterest.objects.filter(
                    symbol=symbol,
                    timestamp__lte=now, timestamp__gte=now - timedelta(hours=6),
                ).order_by('timestamp').values_list('open_interest', flat=True)
            )

            score = 0.0
            reasoning = []

            if len(candles_5m) >= 10:
                cvd = []
                cumulative = 0.0
                for candle in candles_5m:
                    buy_vol = float(candle['taker_buy_volume'])
                    total_vol = float(candle['volume'])
                    delta = buy_vol - (total_vol - buy_vol)
                    cumulative += delta
                    cvd.append(cumulative)
                recent = cvd[-10:]
                slope = np.polyfit(range(len(recent)), recent, 1)[0]
                total_volume = sum(float(c['volume']) for c in candles_5m) or 1.0
                cvd_score = float(np.clip((slope * len(candles_5m)) / (total_volume / len(candles_5m)) * 160, -60, 60))
                score += cvd_score * 0.35
                reasoning.append(f"cvd={cvd_score:.1f}")

            if len(candles_15m) >= 12:
                closes = [float(c['close']) for c in candles_15m]
                volumes = [float(c['volume']) for c in candles_15m]
                obv = [0.0]
                for idx in range(1, len(closes)):
                    if closes[idx] > closes[idx - 1]:
                        obv.append(obv[-1] + volumes[idx])
                    elif closes[idx] < closes[idx - 1]:
                        obv.append(obv[-1] - volumes[idx])
                    else:
                        obv.append(obv[-1])
                if len(obv) >= 6 and abs(obv[-6]) > 1e-9:
                    obv_roc = (obv[-1] - obv[-6]) / abs(obv[-6]) * 100
                    obv_score = float(np.clip(obv_roc, -50, 50))
                    score += obv_score * 0.25
                    reasoning.append(f"obv={obv_score:.1f}")

            rates = [float(r) for r in funding_rates]
            if rates:
                current_rate = rates[-1]
                funding_score = float(np.clip(-current_rate * 20000, -25, 25))
                score += funding_score * 0.15
                reasoning.append(f"funding={funding_score:.1f}")

            oi = [float(v) for v in oi_values]
            if len(oi) >= 3 and len(candles_15m) >= 3:
                oi_change = (oi[-1] - oi[0]) / oi[0] if oi[0] else 0.0
                price_change = (float(candles_15m[-1]['close']) - float(candles_15m[0]['close'])) / float(candles_15m[0]['close'])
                if oi_change > 0.02 and price_change > 0.004:
                    oi_score = 35.0
                elif oi_change > 0.02 and price_change < -0.004:
                    oi_score = -35.0
                else:
                    oi_score = 0.0
                score += oi_score * 0.25
                reasoning.append(f"oi={oi_score:.1f}")

            score = float(np.clip(score, -100, 100))
            confidence = min(abs(score) / 50.0, 1.0)
            bias = 'LONG' if score > 0 else 'SHORT' if score < 0 else 'NEUTRAL'
            return {
                'score': score,
                'confidence': confidence,
                'bias': bias,
                'reasoning': ' | '.join(reasoning) if reasoning else 'volume_flow_neutral',
                'metadata': {},
            }
        except Exception:
            return {'score': 0.0, 'confidence': 0.0, 'bias': 'NEUTRAL', 'reasoning': 'volume_flow_unavailable', 'metadata': {}}

    def _save(self, symbol, direction, passed, gates_a, gates_b, gates_c, ctx=None):
        L1Result.objects.create(
            symbol=symbol,
            direction=direction,
            passed=passed,
            gates_a=gates_a,
            gates_b=gates_b,
            gates_c=gates_c,
            gates_b_count=sum(gates_b.values()) if gates_b else 0,
            gates_c_count=sum(gates_c.values()) if gates_c else 0,
            trade_context=ctx,
        )
