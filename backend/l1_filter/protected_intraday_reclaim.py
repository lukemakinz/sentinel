"""S92: S91 signals with early cost-aware profit protection."""
from dataclasses import dataclass, replace

from .intraday_level_reclaim import IntradayLevelReclaimConfig


@dataclass(frozen=True)
class ProtectedIntradayReclaimConfig(IntradayLevelReclaimConfig):
    name: str = 'S92_protected_intraday_reclaim'
    protection_activation_r: float = 0.25
    profit_lock_fraction: float = 0.50

    def execution(self):
        return replace(
            super().execution(),
            partial_r=self.protection_activation_r,
            trailing=True,
            dollar_ratchet=True,
            dollar_ratchet_lock_fraction=self.profit_lock_fraction,
        )
