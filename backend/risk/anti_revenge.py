"""
Anti-revenge trading rules.
Prevents emotional/revenge trading after losses.
All rules are HARD — no bypasses.
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def check_anti_revenge(symbol: str) -> tuple[bool, str]:
    """
    Check all anti-revenge rules before allowing a new entry.
    Returns (allowed, reason).
    """
    from executor.models import Trade

    now = timezone.now()
    last24 = now - timedelta(hours=24)
    last4h  = now - timedelta(hours=4)
    last_session = now - timedelta(hours=8)

    # ── Rule 1: 2 consecutive SL on same symbol in 24h → block 24h ───────────
    recent_symbol = list(
        Trade.objects.filter(symbol=symbol, entry_time__gte=last24)
        .order_by('-exit_time')
        .values_list('close_reason', flat=True)[:3]
    )
    sl_count = sum(1 for r in recent_symbol if r == 'STOP_LOSS')
    if sl_count >= 2:
        logger.warning(f"Anti-revenge: {symbol} has {sl_count} SL hits in 24h — blocked")
        return False, f"Anti-revenge: {sl_count} SL hits on {symbol} in 24h (cooldown 24h)"

    # ── Rule 2: 1 SL on same symbol → 30 min cooldown ────────────────────────
    last_sl = Trade.objects.filter(
        symbol=symbol, close_reason='STOP_LOSS',
        exit_time__gte=now - timedelta(minutes=30),
    ).exists()
    if last_sl:
        return False, f"Anti-revenge: 30min cooldown after SL on {symbol}"

    # ── Rule 3: 3 consecutive SL in portfolio → daily soft halt ──────────────
    recent_portfolio = list(
        Trade.objects.filter(entry_time__gte=last_session)
        .order_by('-exit_time')
        .values_list('close_reason', flat=True)[:5]
    )
    # Count consecutive SL from most recent
    consecutive_sl = 0
    for r in recent_portfolio:
        if r == 'STOP_LOSS':
            consecutive_sl += 1
        else:
            break
    if consecutive_sl >= 3:
        logger.warning(f"Anti-revenge: {consecutive_sl} consecutive SL in portfolio — soft halt")
        return False, f"Anti-revenge: {consecutive_sl} consecutive portfolio SL — no new entries this session"

    # ── Rule 4: Loss > 2R in current session ─────────────────────────────────
    session_pnl_r = _session_pnl_r(last_session)
    if session_pnl_r is not None and session_pnl_r < -2.0:
        return False, f"Anti-revenge: session loss {session_pnl_r:.1f}R exceeds -2R limit"

    # ── Rule 5: Max 5 trades per portfolio per 24h ────────────────────────────
    trades_today = Trade.objects.filter(entry_time__gte=last24).count()
    if trades_today >= 5:
        return False, f"Anti-revenge: max 5 trades/day reached ({trades_today})"

    # ── Rule 6: Max 1 trade per symbol per 4h ────────────────────────────────
    recent_on_symbol = Trade.objects.filter(symbol=symbol, entry_time__gte=last4h).exists()
    if recent_on_symbol:
        return False, f"Anti-revenge: max 1 trade per symbol per 4h — {symbol} already traded"

    return True, "Anti-revenge checks passed"


def _session_pnl_r(since) -> float | None:
    """Sum of pnl_r for all trades since `since` timestamp."""
    from executor.models import Trade
    trades = list(Trade.objects.filter(entry_time__gte=since).values_list('risk_reward', flat=True))
    if not trades:
        return None
    # risk_reward in trade = actual RR achieved (positive = win, negative = loss)
    return sum(float(r or 0) for r in trades)
