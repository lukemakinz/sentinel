"""L3Calculator — deterministic entry/SL/TP calculation. No LLM."""
from datetime import datetime, timezone
from django.conf import settings

# Strategy-specific ATR buffer multipliers for SL
_SL_ATR_BUFFER = {'S1': 0.20, 'S2': 0.20, 'S3': 0.15}
_MAX_SL_PCT     = 0.03   # 3% hard cap on SL distance from entry
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

        tps = self._take_profits(entry, direction, r)

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
        fvg    = ctx.get('fvg_zone')
        swept  = float(ctx.get('swept_level') or 0)
        liq    = float(ctx.get('nearest_liquidity') or 0)

        if strategy == 'S1':
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                return bot + 0.25 * (top - bot) if direction == 'LONG' else top - 0.25 * (top - bot)
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
        buf    = _SL_ATR_BUFFER.get(strategy, 0.20)
        swept  = float(ctx.get('swept_level') or entry)
        buffer = buf * atr

        if direction == 'LONG':
            sl = swept - buffer
            # 3% cap: SL must be at most 3% below entry
            sl_cap = entry * (1 - _MAX_SL_PCT)
            return max(sl, sl_cap)
        else:
            sl = swept + buffer
            sl_cap = entry * (1 + _MAX_SL_PCT)
            return min(sl, sl_cap)

    # ── Take Profits ───────────────────────────────────────────────────────

    def _take_profits(self, entry: float, direction: str, r: float) -> list[dict]:
        multipliers = [_TP1_R, _TP2_R, None]   # None = runner (no fixed target)
        result = []
        for i, mult in enumerate(multipliers):
            if mult is not None:
                level = entry + mult * r if direction == 'LONG' else entry - mult * r
            else:
                level = None  # chandelier trailing, set at runtime
            result.append({
                'level':  round(level, 4) if level is not None else None,
                'ratio':  _TP_RATIOS[i],
                'label':  f'TP{i + 1}',
                'runner': mult is None,
            })
        return result

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
