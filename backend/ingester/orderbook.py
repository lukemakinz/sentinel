"""Pure order-book feature calculations used by ingestion and research."""
from __future__ import annotations

from decimal import Decimal


def _levels(raw_levels) -> list[tuple[Decimal, Decimal]]:
    parsed = []
    for level in raw_levels or []:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = Decimal(str(level[0]))
        quantity = Decimal(str(level[1]))
        if price > 0 and quantity > 0:
            parsed.append((price, quantity))
    return parsed


def _depth_usd(levels: list[tuple[Decimal, Decimal]], count: int) -> Decimal:
    return sum((price * quantity for price, quantity in levels[:count]), Decimal('0'))


def _imbalance(bid_depth: Decimal, ask_depth: Decimal) -> Decimal:
    total = bid_depth + ask_depth
    return (bid_depth - ask_depth) / total if total > 0 else Decimal('0')


def summarize_depth(raw_bids, raw_asks) -> dict | None:
    """Normalize a partial book and compute stable, replayable L2 features."""
    bids = sorted(_levels(raw_bids), key=lambda level: level[0], reverse=True)
    asks = sorted(_levels(raw_asks), key=lambda level: level[0])
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        return None

    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / Decimal('2')
    bid_depth_5 = _depth_usd(bids, 5)
    ask_depth_5 = _depth_usd(asks, 5)
    bid_depth_20 = _depth_usd(bids, 20)
    ask_depth_20 = _depth_usd(asks, 20)

    return {
        'bids': [[float(price), float(quantity)] for price, quantity in bids[:20]],
        'asks': [[float(price), float(quantity)] for price, quantity in asks[:20]],
        'best_bid': best_bid,
        'best_ask': best_ask,
        'mid_price': mid,
        'spread_bps': (best_ask - best_bid) / mid * Decimal('10000'),
        'bid_depth_5_usd': bid_depth_5,
        'ask_depth_5_usd': ask_depth_5,
        'bid_depth_20_usd': bid_depth_20,
        'ask_depth_20_usd': ask_depth_20,
        'imbalance_5': _imbalance(bid_depth_5, ask_depth_5),
        'imbalance_20': _imbalance(bid_depth_20, ask_depth_20),
    }
