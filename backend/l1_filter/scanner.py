"""L1Scanner: orchestrates all 15 gates and produces TradeContext."""
from datetime import datetime, timezone
from typing import Optional

from .gates_a import check_killzone, check_htf_trend, check_btc_correlation, check_funding_rate, check_adx
from .gates_b import check_liquidity_sweep, check_fvg_ob, check_premium_discount, check_atr_squeeze
from .gates_c import (
    check_choch, check_momentum_divergence, check_ema_crossover,
    check_volume_spike, check_vwap, check_obv_confirmation, check_price_action_trigger,
)
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

        if not all(gates_a.values()):
            self._save(symbol, direction, False, gates_a, {}, {})
            return None

        b1_passed, b1_data = check_liquidity_sweep(candles_1h, direction,
                                                    symbol=symbol, htf_candles=candles_4h)
        b2_passed, b2_data = check_fvg_ob(candles_15m, direction)
        b3_passed, b3_data = check_premium_discount(candles_1h, direction, htf_candles=candles_4h)
        # B4 (classical patterns) removed — redundant with B1+B2, adds noise
        b5_passed, b5_data = check_atr_squeeze(candles_1h)

        gates_b = {'B1': b1_passed, 'B2': b2_passed, 'B3': b3_passed, 'B5': b5_passed}

        strategy_candidates = self._get_s1_candidates(
            b1_passed, b1_data, b2_passed, b3_passed, b5_passed,
            session_window=session_window, mtf_context=mtf_context
        )
        if not strategy_candidates:
            self._save(symbol, direction, False, gates_a, gates_b, {})
            return None

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

        strategy_candidates = self._filter_s1_candidates_by_trigger(strategy_candidates, c1_data, gates_c)
        if not strategy_candidates:
            self._save(symbol, direction, False, gates_a, gates_b, gates_c)
            return None

        selected_strategy = self._select_requested_strategy(strategy, strategy_candidates)
        if selected_strategy is None:
            self._save(symbol, direction, False, gates_a, gates_b, gates_c)
            return None

        setup_score = self._score_setup(
            selected_strategy, gates_b, gates_c, mtf_context, b1_data, b2_data, c1_data
        )
        entry_mode = self._infer_entry_mode(selected_strategy, setup_score, mtf_context, c1_data, gates_c)

        adx_val = a5_data.get('adx_value', 0)
        ctx = {
            'symbol':             symbol,
            'timestamp':          now.isoformat(),
            'direction':          direction,
            'current_price':      candles_15m[-1]['close'] if candles_15m else candles_1h[-1]['close'],
            'strategy':           selected_strategy,
            'strategy_candidates': strategy_candidates,
            'setup_profile':      selected_strategy,
            'session_window':     session_window,
            'entry_mode':         entry_mode,
            'setup_score':        setup_score,
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
            'btc_trend':          a3_data.get('btc_trend'),
            'funding_rate':       a4_data.get('funding_rate'),
            'daily_vwap':         c5_data.get('vwap'),
            'adx_value':          adx_val,
            'regime':             'trending' if adx_val > 25 else 'weak_trending',
        }
        self._save(symbol, direction, True, gates_a, gates_b, gates_c, ctx)
        return ctx

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
    def _select_requested_strategy(strategy: str | None, strategy_candidates: list[str]) -> str | None:
        if not strategy_candidates:
            return None
        if strategy in (None, 'S1'):
            if 'S1A' in strategy_candidates:
                return 'S1A'
            if 'S1C' in strategy_candidates:
                return 'S1C'
            return strategy_candidates[0]
        return strategy if strategy in strategy_candidates else None

    @staticmethod
    def _score_setup(strategy_id: str, gates_b: dict, gates_c: dict, mtf_context: dict,
                     b1_data: dict, b2_data: dict, c1_data: dict) -> int:
        score = 0
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
