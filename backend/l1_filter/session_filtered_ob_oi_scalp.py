"""S43: S20 H1's exact entry/exit (order block + OI confirmation, patient
breakeven+chandelier exit) -- the only route in this project's 46 prior
tests with genuine, if stress-fragile, edge -- PLUS a UTC-hour session
filter. S20's own validation-window failure was specifically on stress
costs (base PF 1.12 passed, stress PF 0.857 did not); if that fragility is
partly a thin-liquidity/wide-effective-spread problem during low-volume
hours rather than a property of the setup itself, restricting entries to
the highest-liquidity hours of the day should show up as improved stress
PF relative to S20's own unfiltered stress numbers, without needing any
new evidence family. Two window widths are tested as the frozen
hypotheses; no other parameter changes.
"""
from dataclasses import dataclass

import pandas as pd

from .order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
    oi_features,
)
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class SessionFilteredOBOIConfig:
    name: str
    route: str  # 'wide_session' (07:00-20:00 UTC) or 'core_overlap' (12:00-17:00 UTC)
    start_hour: int
    end_hour: int

    def __post_init__(self):
        if self.route not in ('wide_session', 'core_overlap'):
            raise ValueError('Unknown session filter route')
        if not 0 <= self.start_hour < 24 or not 0 < self.end_hour <= 24:
            raise ValueError('Invalid session hours')
        if self.start_hour >= self.end_hour:
            raise ValueError('Session filter must not wrap midnight')

    def base(self) -> OrderBlockOIConfig:
        # S20 H1 exactly: route='oi', partial_r=1.5, trail_atr=2.5, target_r=8.0.
        return OrderBlockOIConfig(
            name=self.name, route='oi', partial_r=1.5, trail_atr=2.5, target_r=8.0,
        )

    def execution(self) -> ScalpConfig:
        return self.base().execution()


def central_variants() -> list[SessionFilteredOBOIConfig]:
    """Exactly two predeclared session widths; no parameter grid."""
    return [
        SessionFilteredOBOIConfig('S43_session_wide', 'wide_session', 7, 20),
        SessionFilteredOBOIConfig('S43_session_core_overlap', 'core_overlap', 12, 17),
    ]


def session_features(minutes: pd.DataFrame, metrics: pd.DataFrame,
                      config: SessionFilteredOBOIConfig) -> pd.DataFrame:
    return oi_features(minutes, metrics, config.base())


def generate_session_signals(bars: pd.DataFrame, config: SessionFilteredOBOIConfig,
                              symbol: str) -> list[dict]:
    signals = generate_order_block_oi_signals(bars, config.base(), symbol)
    return [
        signal for signal in signals
        if config.start_hour <= signal['timestamp'].hour < config.end_hour
    ]
