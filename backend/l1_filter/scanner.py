"""L1Scanner: orchestrates all 15 gates and produces TradeContext."""
from datetime import datetime, timezone
from typing import Optional

from .gates_a import check_killzone, check_htf_trend, check_btc_correlation, check_funding_rate, check_adx
from .gates_b import check_liquidity_sweep, check_fvg_ob, check_premium_discount, check_classical_pattern, check_atr_squeeze
from .gates_c import check_choch, check_momentum_divergence, check_ema_crossover, check_volume_spike, check_vwap
from .models import L1Result

MIN_B_PASS = 3
MIN_C_PASS = 2


class L1Scanner:
    def scan(self, symbol: str, now: datetime = None) -> Optional[dict]:
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

        btc_candles = self._get_candles('BTCUSDT', '1h', 50) if symbol != 'BTCUSDT' else candles_1h
        funding     = self._get_latest_funding_rate(symbol)

        a1_passed, a1_data = check_killzone(now)
        a3_passed, a3_data = check_btc_correlation(btc_candles, direction, symbol)
        a4_passed, a4_data = check_funding_rate(funding, direction)
        a5_passed, a5_data = check_adx(candles_1h)

        gates_a = {'A1': a1_passed, 'A2': True, 'A3': a3_passed, 'A4': a4_passed, 'A5': a5_passed}

        if not all(gates_a.values()):
            self._save(symbol, direction, False, gates_a, {}, {})
            return None

        b1_passed, b1_data = check_liquidity_sweep(candles_1h, direction)
        b2_passed, b2_data = check_fvg_ob(candles_15m, direction)
        b3_passed, b3_data = check_premium_discount(candles_4h, direction)
        b4_passed, b4_data = check_classical_pattern(candles_1h, direction)
        b5_passed, b5_data = check_atr_squeeze(candles_1h)

        gates_b = {'B1': b1_passed, 'B2': b2_passed, 'B3': b3_passed, 'B4': b4_passed, 'B5': b5_passed}

        if sum(gates_b.values()) < MIN_B_PASS:
            self._save(symbol, direction, False, gates_a, gates_b, {})
            return None

        c1_passed, c1_data = check_choch(candles_15m, direction)
        c2_passed, c2_data = check_momentum_divergence(candles_1h, direction)
        c3_passed, c3_data = check_ema_crossover(candles_15m, direction)
        c4_passed, c4_data = check_volume_spike(candles_15m)
        c5_passed, c5_data = check_vwap(candles_1h, direction)

        gates_c = {'C1': c1_passed, 'C2': c2_passed, 'C3': c3_passed, 'C4': c4_passed, 'C5': c5_passed}

        if sum(gates_c.values()) < MIN_C_PASS:
            self._save(symbol, direction, False, gates_a, gates_b, gates_c)
            return None

        adx_val = a5_data.get('adx_value', 0)
        ctx = {
            'symbol':             symbol,
            'timestamp':          now.isoformat(),
            'direction':          direction,
            'gates_a':            gates_a,
            'gates_b':            gates_b,
            'gates_c':            gates_c,
            'atr':                a5_data.get('atr'),
            'fvg_zone':           b2_data.get('fvg_zone'),
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

    def _get_candles(self, symbol: str, interval: str, limit: int) -> list:
        from ingester.models import Candle
        qs = (Candle.objects
              .filter(symbol=symbol, interval=interval, is_closed=True)
              .order_by('-timestamp')[:limit])
        return [
            {'open': float(c.open), 'high': float(c.high),
             'low': float(c.low),  'close': float(c.close), 'volume': float(c.volume)}
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
