"""
Risk Manager — combines position sizing and kill switches.
"""
import logging
from django.conf import settings

from .position_sizing import (
    get_atr_for_symbol, calculate_stop_loss,
    calculate_take_profits, calculate_position_size
)
from .kill_switches import check_kill_switches, get_position_size_multiplier

logger = logging.getLogger(__name__)


class RiskManager:
    """Central risk management facade."""

    def evaluate_trade(self, symbol, side, tier, current_price):
        """
        Evaluate whether a trade should be taken.
        Returns (approved, trade_params) or (False, reason).
        """
        # Kill switch check
        allowed, reason = check_kill_switches(symbol, side)
        if not allowed:
            return False, {'reason': reason}

        # Volatility spike — only HIGH_CONVICTION
        if 'Volatility spike' in reason and tier != 'HIGH_CONVICTION':
            return False, {'reason': 'Volatility spike — need HIGH_CONVICTION'}

        # ATR calculation
        atr = get_atr_for_symbol(symbol)
        if atr is None:
            return False, {'reason': 'Cannot calculate ATR — insufficient data'}

        # Position sizing
        balance = self._get_balance()
        risk_pct = settings.MAX_RISK_PER_TRADE
        multiplier = get_position_size_multiplier()
        effective_risk = risk_pct * multiplier

        # Tier-based sizing
        if tier == 'HIGH_CONVICTION':
            size_factor = 1.0
        elif tier == 'SIGNAL':
            size_factor = 0.6
        else:
            return False, {'reason': f'Tier {tier} does not trigger trades'}

        # Calculate levels
        sl = calculate_stop_loss(current_price, atr, side)
        tps = calculate_take_profits(current_price, sl, side)
        size = calculate_position_size(
            balance, effective_risk * size_factor,
            current_price, sl, settings.MAX_LEVERAGE
        )

        if size <= 0:
            return False, {'reason': 'Calculated position size is zero'}

        trade_params = {
            'symbol': symbol,
            'side': side,
            'entry_price': current_price,
            'stop_loss': sl,
            'take_profits': tps,
            'position_size_usd': size,
            'quantity': size / current_price,
            'leverage': settings.MAX_LEVERAGE,
            'risk_percent': effective_risk * size_factor,
            'atr': atr,
            'tier': tier,
        }

        logger.info(f"✅ Trade approved: {symbol} {side} size=${size:.2f} SL={sl:.2f}")
        return True, trade_params

    def _get_balance(self):
        """Get current account balance."""
        from executor.models import AccountState
        state = AccountState.objects.order_by('-updated_at').first()
        if state:
            return state.balance
        return settings.INITIAL_BALANCE
