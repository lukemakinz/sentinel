"""
Kill Switches — automatic safety mechanisms.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import RiskState, RiskEvent

logger = logging.getLogger(__name__)


def get_risk_state():
    """Get or create the singleton risk state."""
    state, _ = RiskState.objects.get_or_create(pk=1)
    return state


def check_kill_switches(symbol, side) -> tuple[bool, str]:
    """
    Check all kill switches before opening a position.
    Returns (allowed, reason).
    """
    state = get_risk_state()

    # 1. Daily drawdown > 3%
    if state.is_daily_stopped:
        return False, f"Daily stop active (PnL: {state.daily_pnl:+.2f}%)"

    if state.daily_pnl < -settings.MAX_DAILY_DRAWDOWN * 100:
        state.is_daily_stopped = True
        state.save()
        _log_event('DAILY_STOP', symbol, f"Daily drawdown {state.daily_pnl:.2f}% exceeded {settings.MAX_DAILY_DRAWDOWN*100}%")
        return False, "Daily drawdown limit hit"

    # 2. Weekly drawdown > 7%
    if state.is_weekly_stopped:
        return False, f"Weekly stop active (PnL: {state.weekly_pnl:+.2f}%)"

    if state.weekly_pnl < -settings.MAX_WEEKLY_DRAWDOWN * 100:
        state.is_weekly_stopped = True
        state.save()
        _log_event('WEEKLY_STOP', symbol, f"Weekly drawdown {state.weekly_pnl:.2f}%")
        return False, "Weekly drawdown limit hit"

    # 3. Max open positions
    from executor.models import Position
    open_positions = Position.objects.filter(status='OPEN').count()
    if open_positions >= settings.MAX_OPEN_POSITIONS:
        return False, f"Max positions reached ({open_positions}/{settings.MAX_OPEN_POSITIONS})"

    # 4. Only one position per symbol
    symbol_positions = Position.objects.filter(symbol=symbol, status='OPEN').count()
    if symbol_positions > 0:
        return False, f"Already have open position on {symbol}"

    # 5. Correlation check (BTC + ETH = no more crypto)
    if open_positions >= 2:
        open_symbols = list(Position.objects.filter(status='OPEN').values_list('symbol', flat=True))
        crypto_count = len(open_symbols)
        if crypto_count >= 2:
            return False, "Correlation limit: already 2 crypto positions open"

    # 6. Volatility spike check
    from .position_sizing import get_atr_for_symbol
    atr = get_atr_for_symbol(symbol)
    if atr:
        from ingester.models import Candle
        avg_candles = list(Candle.objects.filter(
            symbol=symbol, interval='1h', is_closed=True,
        ).order_by('-timestamp').values_list('close', flat=True)[:50])

        if avg_candles:
            avg_price = sum(float(c) for c in avg_candles) / len(avg_candles)
            atr_pct = atr / avg_price
            normal_atr_pct = 0.015  # ~1.5% ATR is normal for BTC

            if atr_pct > normal_atr_pct * 2:
                _log_event('VOLATILITY_SPIKE', symbol, f"ATR {atr_pct:.4f} > 2x normal")
                # Only allow high conviction trades during volatility
                return False, "Volatility spike — only HIGH_CONVICTION trades allowed"

    # 7. Funding rate check
    from ingester.models import FundingRate
    latest_funding = FundingRate.objects.filter(symbol=symbol).order_by('-timestamp').first()
    if latest_funding and abs(float(latest_funding.funding_rate)) > 0.001:
        funding_direction = 'LONG' if float(latest_funding.funding_rate) > 0 else 'SHORT'
        if side == funding_direction:
            _log_event('FUNDING_BLOCK', symbol, f"Funding {float(latest_funding.funding_rate):.6f} blocks {side}")
            return False, f"Funding rate too high to go {side}"

    # 8. News calendar blackout
    from .news_calendar import is_news_blackout
    if is_news_blackout():
        return False, "News blackout window — high-impact event nearby"

    # 9. Portfolio heat (BTC-beta exposure)
    from .portfolio_heat import check_portfolio_heat
    heat_ok, heat_reason = check_portfolio_heat()
    if not heat_ok:
        return False, heat_reason

    # 10. Strategy health (rolling Sharpe)
    from .strategy_monitor import check_strategy_health
    health_ok, health_reason = check_strategy_health()
    if not health_ok:
        return False, health_reason

    # 11. DD-based size multiplier (halt if 0)
    if get_dd_size_multiplier() == 0.0:
        return False, "Portfolio drawdown -20% — trading halted"

    # 12. Anti-revenge rules (cooldown, consecutive SL, session loss limit)
    from .anti_revenge import check_anti_revenge
    ar_ok, ar_reason = check_anti_revenge(symbol)
    if not ar_ok:
        return False, ar_reason

    return True, "All checks passed"


def get_current_drawdown() -> float:
    """Current DD as negative % from peak. 0 if no account data."""
    from executor.models import AccountState
    state = AccountState.objects.order_by('-updated_at').first()
    if not state or state.peak_equity <= 0:
        return 0.0
    return -(state.peak_equity - state.equity) / state.peak_equity * 100


def get_dd_size_multiplier() -> float:
    """DD-based position size: 0%→1.0 | -5%→0.75 | -10%→0.5 | -15%→0.25 | -20%→HALT."""
    dd = get_current_drawdown()
    if dd <= -20:
        return 0.0
    if dd <= -15:
        return 0.25
    if dd <= -10:
        return 0.5
    if dd <= -5:
        return 0.75
    return 1.0


def get_position_size_multiplier() -> float:
    """DD-based position size multiplier (replaces consecutive-loss logic)."""
    mult = get_dd_size_multiplier()
    state = get_risk_state()
    state.position_size_multiplier = mult
    state.save()
    return mult


def update_after_trade(pnl_percent):
    """Update risk state after a trade closes."""
    state = get_risk_state()

    state.daily_pnl += pnl_percent
    state.weekly_pnl += pnl_percent

    if pnl_percent < 0:
        state.consecutive_losses += 1
        if state.consecutive_losses >= 3:
            state.position_size_multiplier = 0.5
            _log_event('LOSS_STREAK', '', f"{state.consecutive_losses} consecutive losses")
    else:
        state.consecutive_losses = 0
        state.position_size_multiplier = 1.0

    state.save()


def reset_daily():
    """Reset daily PnL — run at midnight UTC."""
    state = get_risk_state()
    state.daily_pnl = 0
    state.is_daily_stopped = False
    state.save()


def reset_weekly():
    """Reset weekly PnL — run on Monday midnight UTC."""
    state = get_risk_state()
    state.weekly_pnl = 0
    state.is_weekly_stopped = False
    state.save()


def _log_event(event_type, symbol, message, metadata=None):
    RiskEvent.objects.create(
        event_type=event_type, symbol=symbol,
        message=message, metadata=metadata or {}
    )
    logger.warning(f"🛡️ RISK: {event_type} | {symbol} | {message}")
