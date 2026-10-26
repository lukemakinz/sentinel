"""Small, deterministic helpers for slow multi-sleeve portfolio research."""
from copy import deepcopy

import pandas as pd

from .book_ab_portfolio_combo import merge_book_daily


def short_only_targets(targets: list[dict]) -> list[dict]:
    """Return independent target records with every non-short weight removed.

    Empty target records are intentionally retained.  They close an existing
    short when the frozen parent strategy leaves its DOWN regime; dropping
    them would accidentally turn the hedge into an indefinite hold.
    """
    filtered = []
    for original in targets:
        target = deepcopy(original)
        weights = {
            symbol: float(weight)
            for symbol, weight in target.get('weights', {}).items()
            if float(weight) < 0.0
        }
        target['weights'] = weights
        target['gross_weight'] = float(sum(abs(weight) for weight in weights.values()))
        if 'selected' in target:
            target['selected'] = {
                symbol: details
                for symbol, details in target['selected'].items()
                if symbol in weights
            }
        if not weights and original.get('weights'):
            target['flat_reason'] = 'SHORT_ONLY_FILTER'
        filtered.append(target)
    return filtered


def merge_sleeve_daily(*daily_pnls: pd.Series) -> pd.Series:
    """Merge one or more independently capitalised sleeve PnL series."""
    if not daily_pnls:
        return pd.Series(dtype=float)
    total = daily_pnls[0]
    for sleeve in daily_pnls[1:]:
        total = merge_book_daily(total, sleeve)
    return total
