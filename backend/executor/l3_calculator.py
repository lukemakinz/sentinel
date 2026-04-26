"""L3Calculator — deterministic entry/SL/TP calculation. No LLM."""
from datetime import datetime, timezone
from django.conf import settings

# Strategy-specific ATR buffer multipliers for SL
_SL_ATR_BUFFER = {'S1': 0.20, 'S2': 0.20, 'S3': 0.15}

# Per-strategy SL caps (% of entry price)
# S1 scalp: tight (0.3-1.0%) | S2 order flow: medium (0.3-1.5%) | S3 classic: wider (0.3-2.5%)
_SL_MIN_PCT = {'S1': 0.003, 'S2': 0.003, 'S3': 0.003}  # min 0.3% — noise stop protection
_SL_MAX_PCT = {'S1': 0.015, 'S2': 0.020, 'S3': 0.025}  # max per strategy (1.5/2.0/2.5%)

_MAX_SL_PCT = 0.03   # global hard cap (legacy — per-strategy caps take precedence)
_TP1_R          = 1.5
_TP2_R          = 3.0
_MIN_RR         = 1.2    # TP1 must be >= 1.2R (always met since TP1 = 1.5R)
_TP_RATIOS      = [0.40, 0.40, 0.20]   # TP1, TP2, runner
_CHANDELIER_PERIOD = 22
_CHANDELIER_ATR_MULT = 3.0
_TIME_KILL_HOURS    = 8


class L3Calculator:
    """All methods are pure functions — no DB, no LLM."""

    def calculate(self, trade_context: dict, l2_decision: dict, strategy: str = 'S1') -> dict | None:
        if l2_decision.get('action') != 'APPROVE':
            return None

        direction = trade_context['direction']
        atr       = float(trade_context.get('atr') or 100.0)
        size_mult = float(l2_decision.get('size_multiplier', 1.0))

        entry = self._entry(trade_context, direction, strategy, atr)
        sl    = self._stop_loss(trade_context, entry, direction, atr, strategy)

        r = abs(entry - sl)
        if r <= 0:
            return None

        symbol = trade_context.get('symbol')
        tps = self._take_profits(entry, direction, r, symbol=symbol)

        # Leverage safety: liquidation must be >= 2×R away
        max_lev = getattr(settings, 'MAX_LEVERAGE', 5)
        liq_dist = entry / max_lev
        if liq_dist < 2 * r:
            return None

        return {
            'symbol':       trade_context.get('symbol', ''),
            'side':         direction,
            'entry_price':  round(entry, 4),
            'stop_loss':    round(sl, 4),
            'take_profits': tps,
            'r_value':      round(r, 4),
            'size_multiplier': size_mult,
            'strategy':     strategy,
        }

    # ── Entry ──────────────────────────────────────────────────────────────

    def _entry(self, ctx: dict, direction: str, strategy: str, atr: float) -> float:
        fvg      = ctx.get('fvg_zone')
        entry_ote = ctx.get('entry_ote')   # OTE from proper FVG (50% mid)
        swept    = float(ctx.get('swept_level') or 0)
        liq      = float(ctx.get('nearest_liquidity') or 0)

        if strategy == 'S1':
            if entry_ote:
                # Use OTE entry from proper displacement FVG
                return float(entry_ote)
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                # 50% (mid) instead of previous 25% — standard OTE
                return bot + 0.50 * (top - bot) if direction == 'LONG' else top - 0.50 * (top - bot)
            # Fallback: just inside the sweep level
            return swept + atr * 0.1 if direction == 'LONG' else swept - atr * 0.1

        if strategy == 'S2':
            # Market order at ChoCH — use swept level + small buffer
            return swept + 0.1 * atr if direction == 'LONG' else swept - 0.1 * atr

        # S3: Classic TA — limit near S/R (use nearest liquidity as S/R proxy)
        if liq > 0:
            return liq * 1.005 if direction == 'LONG' else liq * 0.995
        return swept + 0.1 * atr if direction == 'LONG' else swept - 0.1 * atr

    # ── Stop Loss ──────────────────────────────────────────────────────────

    def _stop_loss(self, ctx: dict, entry: float, direction: str, atr: float, strategy: str) -> float:
        buf   = _SL_ATR_BUFFER.get(strategy, 0.20)
        swept = float(ctx.get('swept_level') or entry)
        sl_min_pct = _SL_MIN_PCT.get(strategy, 0.003)
        sl_max_pct = _SL_MAX_PCT.get(strategy, 0.010)

        if direction == 'LONG':
            sl_raw = swept - buf * atr
            # Apply per-strategy bounds
            sl_floor = entry * (1 - sl_max_pct)  # can't be further than max%
            sl_ceil  = entry * (1 - sl_min_pct)  # can't be closer than min%
            return max(sl_raw, sl_floor) if sl_raw < sl_ceil else sl_ceil
        else:
            sl_raw   = swept + buf * atr
            sl_floor = entry * (1 + sl_min_pct)
            sl_ceil  = entry * (1 + sl_max_pct)
            return min(sl_raw, sl_ceil) if sl_raw > sl_floor else sl_floor

    # ── Take Profits ───────────────────────────────────────────────────────

    def _take_profits(self, entry: float, direction: str, r: float,
                       symbol: str = None) -> list[dict]:
        """
        TP targets: nearest real liquidity level preferred over mechanical R multiples.
        Falls back to 1.5R/3R when no liquidity data available.
        """
        tp1_level = tp2_level = None

        # Try to use real liquidity levels as TP targets
        if symbol and r > 0:
            try:
                from l1_filter.liquidity import LiquiditySnapshot
                snap   = LiquiditySnapshot.build(symbol)
                levels = snap.all_levels()

                if direction == 'LONG':
                    above = sorted([l for l in levels if l > entry + 0.5 * r])
                    if len(above) >= 1: tp1_level = above[0]
                    if len(above) >= 2: tp2_level = above[1]
                else:
                    below = sorted([l for l in levels if l < entry - 0.5 * r], reverse=True)
                    if len(below) >= 1: tp1_level = below[0]
                    if len(below) >= 2: tp2_level = below[1]
            except Exception:
                pass

        # Fallback: mechanical R multiples
        if tp1_level is None:
            tp1_level = entry + _TP1_R * r if direction == 'LONG' else entry - _TP1_R * r
        if tp2_level is None:
            tp2_level = entry + _TP2_R * r if direction == 'LONG' else entry - _TP2_R * r

        return [
            {'level': round(tp1_level, 4), 'ratio': _TP_RATIOS[0], 'label': 'TP1', 'runner': False},
            {'level': round(tp2_level, 4), 'ratio': _TP_RATIOS[1], 'label': 'TP2', 'runner': False},
            {'level': None, 'ratio': _TP_RATIOS[2], 'label': 'TP3', 'runner': True},
        ]

    # ── Chandelier Stop ────────────────────────────────────────────────────

    @staticmethod
    def compute_chandelier_stop(direction: str, price_series: list[float], atr: float) -> float | None:
        if len(price_series) < _CHANDELIER_PERIOD:
            return None
        window = price_series[-_CHANDELIER_PERIOD:]
        if direction == 'LONG':
            return max(window) - _CHANDELIER_ATR_MULT * atr
        return min(window) + _CHANDELIER_ATR_MULT * atr

    # ── Time Kill ─────────────────────────────────────────────────────────

    @staticmethod
    def check_time_kill(direction: str, opened_at: datetime,
                        entry: float, sl: float, current: float) -> bool:
        age_hours = (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600
        if age_hours < _TIME_KILL_HOURS:
            return False

        r = abs(entry - sl)
        one_r_level = entry + r if direction == 'LONG' else entry - r
        hit_one_r = (
            (direction == 'LONG'  and current >= one_r_level) or
            (direction == 'SHORT' and current <= one_r_level)
        )
        return not hit_one_r
