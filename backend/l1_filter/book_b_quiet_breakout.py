"""S83 — 1h Donchian only in 'quiet' bull regimes (low BTC vol, solid breadth)."""
from dataclasses import dataclass, replace

import pandas as pd

from .book_b_shared_risk import BookBSharedRiskConfig, daily_indicator_table
from .book_a_small_tsmom import BookASmallTsmomConfig
from .hourly_donchian_adx import (
    HourlyDonchianAdxConfig,
    generate_hourly_donchian_adx_signals,
    hourly_donchian_adx_features,
)
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class BookBQuietBreakoutConfig:
    name: str = 'S83_quiet_donchian'
    donchian: HourlyDonchianAdxConfig = HourlyDonchianAdxConfig()
    max_btc_vol_percentile: float = 0.55
    min_breadth_sma50: float = 0.40
    require_btc_above_sma200: bool = True
    max_trades_per_week: int = 0  # 0 = unlimited

    def execution(self) -> ScalpConfig:
        return replace(
            self.donchian.execution(),
            name=self.name,
            fixed_risk_usd=6.0,
            max_positions=1,
            fee_bps=7.0,
            maker_fee_bps=7.0,
            daily_loss_fraction=0.05,
            drawdown_halt_fraction=0.25,
            consecutive_loss_halt=3,
        )


def filter_quiet_breakout_signals(
    signals: list[dict],
    indicators: pd.DataFrame,
    config: BookBQuietBreakoutConfig,
) -> list[dict]:
    out = []
    week_counts: dict[tuple[int, int], int] = {}
    for signal in signals:
        day = pd.Timestamp(signal['timestamp']).normalize()
        if day not in indicators.index:
            continue
        row = indicators.loc[day]
        if config.require_btc_above_sma200 and row.get('btc_above_sma200', 0) < 1:
            continue
        if float(row.get('btc_vol_percentile', 1)) > config.max_btc_vol_percentile:
            continue
        if float(row.get('breadth_sma50', 0)) < config.min_breadth_sma50:
            continue
        ts = pd.Timestamp(signal['timestamp'])
        if config.max_trades_per_week > 0:
            key = (int(ts.isocalendar().year), int(ts.isocalendar().week))
            if week_counts.get(key, 0) >= config.max_trades_per_week:
                continue
            week_counts[key] = week_counts.get(key, 0) + 1
        tagged = dict(signal)
        tagged['risk_scale'] = 0.5 + 0.5 * float(row.get('breadth_sma50', 0))
        tagged['setup'] = 'quiet_donchian_rm'
        out.append(tagged)
    return out


BOOK_B_QUIET_V2 = BookBQuietBreakoutConfig(
    name='S83_quiet_donchian_v2',
    max_btc_vol_percentile=0.45,
    min_breadth_sma50=0.50,
    max_trades_per_week=2,
)


def build_quiet_breakout_signals(
    minutes: pd.DataFrame,
    minutes_panel: dict[str, pd.DataFrame],
    symbol: str,
    config: BookBQuietBreakoutConfig,
) -> list[dict]:
    gate = BookASmallTsmomConfig()
    indicators = daily_indicator_table(minutes_panel, gate)
    raw = generate_hourly_donchian_adx_signals(
        hourly_donchian_adx_features(minutes, config.donchian),
        config.donchian,
        symbol,
    )
    return filter_quiet_breakout_signals(raw, indicators, config)
