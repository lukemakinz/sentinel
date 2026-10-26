"""Book B — S79 liquidation cascade snapback (BTC/ETH + liquid alts with OI)."""
from dataclasses import dataclass, replace

from .liquidation_cascade_fade_scalp import CascadeFadeConfig
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class BookBLiqSnapbackConfig:
    """S79-LIQ: fade forced deleveraging; higher risk book ($15) vs S38."""

    name: str = 'S79_book_b_liq'
    route: str = 'immediate'

    def cascade(self) -> CascadeFadeConfig:
        return CascadeFadeConfig(
            name=f'{self.name}_{self.route}',
            route=self.route,
            displacement_atr_mult=2.25,
            volume_mult=2.0,
            target_r=2.5,
            trail_atr=1.25,
            partial_r=1.0,
        )

    def execution(self) -> ScalpConfig:
        base = self.cascade().execution()
        return ScalpConfig(
            name=self.name,
            minutes=base.minutes,
            target_r=base.target_r,
            partial_r=base.partial_r,
            partial_fraction=base.partial_fraction,
            trailing=base.trailing,
            trail_atr=base.trail_atr,
            max_hold_minutes=240,
            risk_fraction=0.06,
            max_notional_equity=0.85,
            daily_loss_fraction=0.08,
            weekly_loss_fraction=0.18,
            drawdown_halt_fraction=0.35,
            fee_bps=7.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=2.0,
            leverage=8.0,
            max_margin_fraction=0.45,
            margin_safety_reserve=0.02,
            maker_fee_bps=7.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=75.0,
            fixed_risk_usd=15.0,
            max_positions=2,
            flip_on_opposite_signal=False,
        )


def central_variants() -> list[BookBLiqSnapbackConfig]:
    return [
        BookBLiqSnapbackConfig(route='immediate'),
        BookBLiqSnapbackConfig(name='S79_book_b_liq_confirmed', route='confirmed'),
        BookBLiqSnapbackConfig(
            name='S79_book_b_liq_lite',
            route='confirmed',
        ),
    ]


def execution_for(config: BookBLiqSnapbackConfig) -> ScalpConfig:
    execution = config.execution()
    if config.name == 'S79_book_b_liq_lite':
        return replace(
            execution,
            name=config.name,
            fixed_risk_usd=5.0,
            fixed_margin_usd=40.0,
            max_positions=1,
            daily_loss_fraction=0.06,
        )
    return execution
