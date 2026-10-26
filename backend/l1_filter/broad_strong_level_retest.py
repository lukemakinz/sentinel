"""S89: one strong-level strategy across a liquid multi-asset universe."""
from dataclasses import dataclass

from .hourly_strong_level_retest import HourlyStrongLevelRetestConfig


@dataclass(frozen=True)
class BroadStrongLevelRetestConfig(HourlyStrongLevelRetestConfig):
    name: str = 'S89_broad_strong_level_retest'
    # Strong hourly support/resistance is allowed a full trading week to be
    # revisited.  The first touch still consumes the setup.
    validity_hours: int = 168
