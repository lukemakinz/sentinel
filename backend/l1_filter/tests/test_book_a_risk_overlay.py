import pandas as pd

from l1_filter.book_a_risk_overlay import (
    BookARiskOverlayConfig,
    exposure_multiplier,
)
from l1_filter.book_a_small_tsmom import BookASmallTsmomConfig


def test_exposure_zero_when_below_sma200():
    risk = BookARiskOverlayConfig()
    mult = exposure_multiplier({'valid': 1.0, 'btc_above_sma200': 0.0, 'breadth_sma50': 1.0}, risk)
    assert mult == 0.0


def test_drawdown_flat_cuts_exposure():
    risk = BookARiskOverlayConfig(use_breadth=False, use_vol_penalty=False)
    mult = exposure_multiplier({
        'valid': 1.0,
        'btc_above_sma200': 1.0,
        'equity_drawdown': 0.20,
    }, risk)
    assert mult == 0.0
