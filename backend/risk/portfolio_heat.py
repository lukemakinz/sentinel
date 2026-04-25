"""Portfolio Heat — BTC-beta correlation exposure limit."""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_BTC_BETA_MULTIPLIER = 2.0  # Max 2× BTC-beta effective exposure

# Approximate BTC-beta for common pairs (rolling 30d correlation proxy)
BTC_BETAS = {
    'BTCUSDT': 1.00,
    'ETHUSDT': 0.90,
    'SOLUSDT': 0.85,
    'BNBUSDT': 0.75,
    'AVAXUSDT': 0.80,
    'ADAUSDT': 0.70,
    'DOTUSDT': 0.75,
}
DEFAULT_BETA = 0.80  # fallback for unknown pairs


def get_btc_beta_exposure() -> float:
    """
    Return total absolute BTC-beta exposure as a multiple of account equity.
    Long and short positions are counted separately (abs value).
    """
    from executor.models import Position, AccountState

    open_positions = list(Position.objects.filter(status='OPEN'))
    if not open_positions:
        return 0.0

    account = AccountState.objects.order_by('-updated_at').first()
    equity = float(account.equity) if account else float(getattr(settings, 'INITIAL_BALANCE', 10000))
    if equity <= 0:
        return 0.0

    total_exposure = 0.0
    for pos in open_positions:
        beta = BTC_BETAS.get(pos.symbol, DEFAULT_BETA)
        total_exposure += abs(pos.position_size_usd) * beta

    return total_exposure / equity


def check_portfolio_heat() -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Blocks new trades when BTC-beta exposure > 2×.
    """
    from executor.models import Position
    if not Position.objects.filter(status='OPEN').exists():
        return True, "No open positions"

    ratio = get_btc_beta_exposure()

    if ratio > MAX_BTC_BETA_MULTIPLIER:
        msg = f"BTC-beta exposure too high: {ratio:.2f}× (max {MAX_BTC_BETA_MULTIPLIER}×)"
        logger.warning(f"🔥 PORTFOLIO HEAT: {msg}")
        return False, msg

    return True, f"Portfolio heat OK: {ratio:.2f}× BTC-beta"
