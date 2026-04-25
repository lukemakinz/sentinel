"""Slippage and fee model."""
from enum import Enum

MARKET_SLIPPAGE = 0.001   # 0.1%
TAKER_FEE       = 0.0005  # 0.05%
MAKER_FEE       = 0.0002  # 0.02%


class OrderType(str, Enum):
    MARKET = 'market'
    LIMIT  = 'limit'


def apply_slippage(price: float, order_type: OrderType, direction: str) -> float:
    if order_type == OrderType.MARKET:
        factor = 1 + MARKET_SLIPPAGE if direction == 'LONG' else 1 - MARKET_SLIPPAGE
        return price * factor
    return price  # limit orders fill at exact price


def compute_fee(position_size_usd: float, order_type: OrderType) -> float:
    rate = TAKER_FEE if order_type == OrderType.MARKET else MAKER_FEE
    return position_size_usd * rate
