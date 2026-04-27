"""L3Calculator — deterministic entry/SL/TP calculation. No LLM."""
from datetime import datetime, timezone
from django.conf import settings

# Strategy-specific ATR buffer multipliers for SL
_SL_ATR_BUFFER = {'S1': 0.20, 'S1A': 0.20, 'S1B': 0.10, 'S1C': 0.16, 'S2': 0.20, 'S3': 0.15}

# Per-strategy SL caps (% of entry price)
# S1 scalp: tight (0.3-1.0%) | S2 order flow: medium (0.3-1.5%) | S3 classic: wider (0.3-2.5%)
_SL_MIN_PCT = {'S1': 0.003, 'S1A': 0.003, 'S1B': 0.003, 'S1C': 0.003, 'S2': 0.003, 'S3': 0.003}
_SL_MAX_PCT = {'S1': 0.015, 'S1A': 0.015, 'S1B': 0.012, 'S1C': 0.016, 'S2': 0.020, 'S3': 0.025}

_MAX_SL_PCT = 0.03   # global hard cap (legacy — per-strategy caps take precedence)
_MIN_RR         = 1.2    # TP1 must be >= 1.2R (always met since TP1 = 1.5R)
_CHANDELIER_PERIOD = 22
_CHANDELIER_ATR_MULT = 3.0
_TIME_KILL_HOURS    = 8

_TP_CONFIG = {
    'S1':  {'tp1_r': 1.5, 'tp2_r': 3.0, 'ratios': [0.40, 0.40, 0.20]},
    'S1A': {'tp1_r': 1.5, 'tp2_r': 3.0, 'ratios': [0.25, 0.25, 0.50]},
    'S1B': {'tp1_r': 0.8, 'tp2_r': 2.4, 'ratios': [0.30, 0.30, 0.40]},
    'S1C': {'tp1_r': 1.2, 'tp2_r': 3.2, 'ratios': [0.15, 0.25, 0.60]},
    'S2':  {'tp1_r': 1.5, 'tp2_r': 3.0, 'ratios': [0.40, 0.40, 0.20]},
    'S3':  {'tp1_r': 1.5, 'tp2_r': 3.0, 'ratios': [0.40, 0.40, 0.20]},
}

_TIME_KILL_CONFIG = {
    'S1':  {'hours': 8, 'min_r_progress': 1.0},
    'S1A': {'hours': 8, 'min_r_progress': 1.0},
    'S1B': {'hours': 4, 'min_r_progress': 0.5},
    'S1C': {'hours': 7, 'min_r_progress': 0.5},
    'S2':  {'hours': 8, 'min_r_progress': 1.0},
    'S3':  {'hours': 8, 'min_r_progress': 1.0},
}

_STOP_PROFILE_MULTIPLIERS = {
    'tight':  {'atr': 0.80, 'min_pct': 0.90, 'max_pct': 0.85},
    'medium': {'atr': 1.00, 'min_pct': 1.00, 'max_pct': 1.00},
    'loose':  {'atr': 1.35, 'min_pct': 1.15, 'max_pct': 1.35},
}


class L3Calculator:
    """All methods are pure functions — no DB, no LLM."""

    def calculate(self, trade_context: dict, l2_decision: dict, strategy: str = 'S1') -> dict | None:
        if l2_decision.get('action') != 'APPROVE':
            return None

        direction = trade_context['direction']
        atr       = float(trade_context.get('atr') or 100.0)
        base_size_mult = float(l2_decision.get('size_multiplier', 1.0))
        size_mult = base_size_mult * self._setup_size_multiplier(trade_context, strategy)

        entry = self._entry(trade_context, direction, strategy, atr)
        sl    = self._stop_loss(trade_context, entry, direction, atr, strategy)

        r = abs(entry - sl)
        if r <= 0:
            return None

        symbol = trade_context.get('symbol')
        runner_profile = self._runner_profile(trade_context, strategy)
        tps = self._take_profits(entry, direction, r, symbol=symbol, strategy=strategy)

        leverage, liq_price, liq_dist, conviction = self._select_leverage(
            trade_context, l2_decision, entry, direction, r
        )
        if leverage is None:
            return None

        entry_mode = trade_context.get('entry_mode', 'MARKET' if strategy == 'S1B' else 'LIMIT')
        order_type = 'MARKET' if entry_mode in {'MARKET', 'HYBRID'} else 'LIMIT'

        return {
            'symbol':       trade_context.get('symbol', ''),
            'side':         direction,
            'entry_price':  round(entry, 4),
            'stop_loss':    round(sl, 4),
            'take_profits': tps,
            'r_value':      round(r, 4),
            'size_multiplier': size_mult,
            'margin_cap_multiplier': self._margin_cap_multiplier(trade_context, strategy),
            'runner_profile': runner_profile,
            'strategy':     strategy,
            'stop_profile': trade_context.get('stop_profile', 'medium'),
            'leverage':     leverage,
            'margin_mode':  getattr(settings, 'DEFAULT_MARGIN_MODE', 'isolated'),
            'liquidation_price': round(liq_price, 4),
            'liquidation_buffer_r': round(liq_dist / r, 4),
            'conviction':   conviction,
            'entry_mode':   entry_mode,
            'order_type':   order_type,
        }

    @staticmethod
    def _setup_size_multiplier(ctx: dict, strategy: str) -> float:
        if strategy != 'S1C':
            return 1.0

        score = int(ctx.get('setup_score') or 0)
        entry_mode = ctx.get('entry_mode')
        fvg_status = ctx.get('fvg_status')
        mtf = ctx.get('mtf_context') or {}
        h4_div = mtf.get('state_4h', {}).get('divergence_aligned', False)
        timing_div = mtf.get('timing_15m', {}).get('divergence_aligned', False)

        if score >= 10 and entry_mode == 'HYBRID' and fvg_status == 'fresh':
            return 1.5 if (h4_div or timing_div) else 1.35
        if score >= 8 and entry_mode == 'HYBRID':
            return 1.25
        return 1.0

    @staticmethod
    def _margin_cap_multiplier(ctx: dict, strategy: str) -> float:
        if strategy != 'S1C':
            return 1.0

        score = int(ctx.get('setup_score') or 0)
        entry_mode = ctx.get('entry_mode')
        fvg_status = ctx.get('fvg_status')
        mtf = ctx.get('mtf_context') or {}
        h4_div = mtf.get('state_4h', {}).get('divergence_aligned', False)
        timing_div = mtf.get('timing_15m', {}).get('divergence_aligned', False)

        if score >= 10 and entry_mode == 'HYBRID' and fvg_status == 'fresh' and (h4_div or timing_div):
            return 1.35
        if score >= 8 and entry_mode == 'HYBRID':
            return 1.20
        return 1.0

    @staticmethod
    def _runner_profile(ctx: dict, strategy: str) -> str:
        if strategy != 'S1C':
            return 'standard'

        score = int(ctx.get('setup_score') or 0)
        entry_mode = ctx.get('entry_mode')
        fvg_status = ctx.get('fvg_status')
        symbol = ctx.get('symbol', '')
        mtf = ctx.get('mtf_context') or {}
        h4_div = mtf.get('state_4h', {}).get('divergence_aligned', False)
        timing_div = mtf.get('timing_15m', {}).get('divergence_aligned', False)

        is_alt = symbol in {'SOLUSDT', 'ETHUSDT', 'BNBUSDT'}
        if score >= 10 and entry_mode == 'HYBRID' and fvg_status == 'fresh' and (h4_div or timing_div):
            return 'extended'
        if is_alt and score >= 8 and entry_mode == 'HYBRID':
            return 'extended'
        return 'standard'

    # ── Entry ──────────────────────────────────────────────────────────────

    def _entry(self, ctx: dict, direction: str, strategy: str, atr: float) -> float:
        fvg      = ctx.get('fvg_zone')
        entry_ote = ctx.get('entry_ote')   # OTE from proper FVG (50% mid)
        swept    = float(ctx.get('swept_level') or 0)
        liq      = float(ctx.get('nearest_liquidity') or 0)

        if strategy in {'S1', 'S1A'}:
            if entry_ote:
                # Use OTE entry from proper displacement FVG
                return float(entry_ote)
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                # 50% (mid) instead of previous 25% — standard OTE
                return bot + 0.50 * (top - bot) if direction == 'LONG' else top - 0.50 * (top - bot)
            # Fallback: just inside the sweep level
            return swept + atr * 0.1 if direction == 'LONG' else swept - atr * 0.1

        if strategy == 'S1B':
            current = float(ctx.get('current_price') or 0.0)
            entry_mode = ctx.get('entry_mode', 'MARKET')
            shallow_limit = None
            if current > 0:
                if fvg:
                    bot, top = float(fvg[0]), float(fvg[1])
                    shallow_limit = bot + 0.38 * (top - bot) if direction == 'LONG' else top - 0.38 * (top - bot)
                if entry_mode == 'HYBRID' and shallow_limit is not None:
                    return 0.33 * current + 0.67 * shallow_limit
                if entry_mode == 'MARKET':
                    return current
                if entry_mode == 'LIMIT' and shallow_limit is not None:
                    return shallow_limit
                return current
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                return bot + 0.38 * (top - bot) if direction == 'LONG' else top - 0.38 * (top - bot)
            if liq > 0:
                return liq * 1.002 if direction == 'LONG' else liq * 0.998
            return swept + atr * 0.2 if direction == 'LONG' else swept - atr * 0.2

        if strategy == 'S1C':
            current = float(ctx.get('current_price') or 0.0)
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                reclaim_limit = bot + 0.50 * (top - bot) if direction == 'LONG' else top - 0.50 * (top - bot)
                if current > 0:
                    return 0.25 * current + 0.75 * reclaim_limit
                return reclaim_limit
            if current > 0 and swept > 0:
                reclaim_level = swept * (1.001 if direction == 'LONG' else 0.999)
                return 0.25 * current + 0.75 * reclaim_level
            return swept + atr * 0.15 if direction == 'LONG' else swept - atr * 0.15

        if strategy == 'S2':
            # Market order at ChoCH — use swept level + small buffer
            return swept + 0.1 * atr if direction == 'LONG' else swept - 0.1 * atr

        # S3: Classic TA — limit near S/R (use nearest liquidity as S/R proxy)
        if liq > 0:
            return liq * 1.005 if direction == 'LONG' else liq * 0.995
        return swept + 0.1 * atr if direction == 'LONG' else swept - 0.1 * atr

    # ── Stop Loss ──────────────────────────────────────────────────────────

    def _stop_loss(self, ctx: dict, entry: float, direction: str, atr: float, strategy: str) -> float:
        stop_profile = str(ctx.get('stop_profile', 'medium')).lower()
        profile = _STOP_PROFILE_MULTIPLIERS.get(stop_profile, _STOP_PROFILE_MULTIPLIERS['medium'])
        buf   = _SL_ATR_BUFFER.get(strategy, 0.20) * profile['atr']
        swept = float(ctx.get('swept_level') or entry)
        fvg   = ctx.get('fvg_zone')
        sl_min_pct = _SL_MIN_PCT.get(strategy, 0.003) * profile['min_pct']
        sl_max_pct = _SL_MAX_PCT.get(strategy, 0.010) * profile['max_pct']

        if strategy == 'S1B' and fvg:
            bot, top = float(fvg[0]), float(fvg[1])
            if direction == 'LONG':
                swept = min(swept, bot)
                sl_raw = bot - buf * atr
                sl_floor = entry * (1 - sl_max_pct)
                sl_ceil  = entry * (1 - sl_min_pct)
                return max(sl_raw, sl_floor) if sl_raw < sl_ceil else sl_ceil
            else:
                swept = max(swept, top)
                sl_raw = top + buf * atr
                sl_floor = entry * (1 + sl_min_pct)
                sl_ceil  = entry * (1 + sl_max_pct)
                return min(sl_raw, sl_ceil) if sl_raw > sl_floor else sl_floor

        if strategy == 'S1C':
            anchor = swept
            if fvg:
                bot, top = float(fvg[0]), float(fvg[1])
                anchor = min(anchor, bot) if direction == 'LONG' else max(anchor, top)
            if direction == 'LONG':
                sl_raw = anchor - buf * atr
                sl_floor = entry * (1 - sl_max_pct)
                sl_ceil  = entry * (1 - sl_min_pct)
                return max(sl_raw, sl_floor) if sl_raw < sl_ceil else sl_ceil
            sl_raw = anchor + buf * atr
            sl_floor = entry * (1 + sl_min_pct)
            sl_ceil  = entry * (1 + sl_max_pct)
            return min(sl_raw, sl_ceil) if sl_raw > sl_floor else sl_floor

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
                       symbol: str = None, strategy: str = 'S1') -> list[dict]:
        """
        TP targets: nearest real liquidity level preferred over mechanical R multiples.
        Falls back to 1.5R/3R when no liquidity data available.
        """
        tp1_level = tp2_level = None
        tp_cfg = _TP_CONFIG.get(strategy, _TP_CONFIG['S1'])
        tp1_r = tp_cfg['tp1_r']
        tp2_r = tp_cfg['tp2_r']
        tp_ratios = tp_cfg['ratios']

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
            tp1_level = entry + tp1_r * r if direction == 'LONG' else entry - tp1_r * r
        if tp2_level is None:
            tp2_level = entry + tp2_r * r if direction == 'LONG' else entry - tp2_r * r

        return [
            {'level': round(tp1_level, 4), 'ratio': tp_ratios[0], 'label': 'TP1', 'runner': False},
            {'level': round(tp2_level, 4), 'ratio': tp_ratios[1], 'label': 'TP2', 'runner': False},
            {'level': None, 'ratio': tp_ratios[2], 'label': 'TP3', 'runner': True},
        ]

    def _select_leverage(self, ctx: dict, l2_decision: dict, entry: float,
                          direction: str, r: float) -> tuple[int | None, float | None, float | None, str]:
        default_lev = max(1, int(getattr(settings, 'MAX_LEVERAGE', 10)))
        high_conv_lev = max(default_lev, int(getattr(settings, 'MAX_HIGH_CONVICTION_LEVERAGE', 20)))
        min_buffer_r = float(getattr(settings, 'MIN_LIQUIDATION_BUFFER_R', 3.0))

        is_high_conviction = self._is_high_conviction(ctx, l2_decision)
        leverage = high_conv_lev if is_high_conviction else default_lev
        conviction = 'HIGH_CONVICTION' if is_high_conviction else 'STANDARD'

        liq_price = self._compute_liquidation_price(direction, entry, leverage)
        liq_dist = abs(entry - liq_price)
        if liq_dist >= min_buffer_r * r:
            return leverage, liq_price, liq_dist, conviction

        if leverage != default_lev:
            liq_price = self._compute_liquidation_price(direction, entry, default_lev)
            liq_dist = abs(entry - liq_price)
            if liq_dist >= min_buffer_r * r:
                return default_lev, liq_price, liq_dist, 'STANDARD'

        return None, None, None, conviction

    @staticmethod
    def _is_high_conviction(ctx: dict, l2_decision: dict) -> bool:
        if float(l2_decision.get('size_multiplier', 0.0)) < 1.0:
            return False
        gates_b = ctx.get('gates_b') or {}
        gates_c = ctx.get('gates_c') or {}
        passed_b = sum(1 for passed in gates_b.values() if passed)
        passed_c = sum(1 for passed in gates_c.values() if passed)
        return passed_b >= 3 and passed_c >= 3

    @staticmethod
    def _compute_liquidation_price(side: str, entry_price: float, leverage: int) -> float:
        maintenance_margin = float(getattr(settings, 'MAINTENANCE_MARGIN_RATE', 0.005))
        if leverage <= 0:
            return 0.0
        if side == 'LONG':
            return entry_price * (1 - 1 / leverage + maintenance_margin)
        return entry_price * (1 + 1 / leverage - maintenance_margin)

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
                        entry: float, sl: float, current: float,
                        strategy: str = 'S1',
                        tp1_hit: bool = False,
                        tp2_hit: bool = False) -> bool:
        cfg = _TIME_KILL_CONFIG.get(strategy, _TIME_KILL_CONFIG['S1'])
        age_hours = (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600

        if strategy == 'S1B':
            if age_hours >= 2:
                if (direction == 'LONG' and current < entry) or (direction == 'SHORT' and current > entry):
                    return True
            if age_hours < cfg['hours']:
                return False

        if strategy == 'S1C':
            if tp2_hit and age_hours < 12:
                return False
            if tp1_hit and age_hours < 10:
                return False

        if age_hours < cfg['hours']:
            return False

        r = abs(entry - sl)
        min_progress_level = entry + cfg['min_r_progress'] * r if direction == 'LONG' else entry - cfg['min_r_progress'] * r
        hit_required_progress = (
            (direction == 'LONG'  and current >= min_progress_level) or
            (direction == 'SHORT' and current <= min_progress_level)
        )
        return not hit_required_progress
