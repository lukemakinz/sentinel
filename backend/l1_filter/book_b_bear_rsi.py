"""Book B — RSI2 only when Book A macro gate is OFF (BTC < SMA200)."""
from dataclasses import dataclass, replace

import pandas as pd

from .book_a_small_tsmom import BookASmallTsmomConfig, build_daily_panel
from .rsi2_mean_reversion import Rsi2Config, generate_rsi2_signals, rsi2_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class BookBBearRsiConfig:
    name: str = 'S81_book_b_bear_rsi'
    gate: BookASmallTsmomConfig = BookASmallTsmomConfig()
    rsi: Rsi2Config = Rsi2Config(name='S81_rsi2_bear')

    def execution(self) -> ScalpConfig:
        return replace(
            self.rsi.execution(),
            name=self.name,
            fee_bps=7.0,
            maker_fee_bps=7.0,
            fixed_risk_usd=10.0,
            max_positions=1,
        )


def _btc_bear_days(panel: pd.DataFrame, config: BookASmallTsmomConfig) -> set[pd.Timestamp]:
    gate = config.gate_symbol()
    btc = panel[gate]
    sma = btc.rolling(config.sma_gate_days).mean()
    bear = btc < sma
    return set(panel.index[bear.fillna(False)])


def generate_bear_rsi_signals(
    minutes: pd.DataFrame,
    btc_minutes: pd.DataFrame,
    config: BookBBearRsiConfig,
    symbol: str,
) -> list[dict]:
    panel = build_daily_panel(
        {config.gate.gate_symbol(): btc_minutes, symbol: minutes},
        config.gate,
    )
    bear_days = _btc_bear_days(panel, config.gate)
    raw = generate_rsi2_signals(rsi2_features(minutes, config.rsi), config.rsi, symbol)
    out = []
    for signal in raw:
        day = signal['timestamp'].normalize()
        if day in bear_days:
            out.append(signal)
    return out
