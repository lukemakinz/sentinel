"""Book B — S80 macro event burst (FOMC/CPI/NFP), post-release range breakout."""
from collections import Counter
from dataclasses import dataclass
import numpy as np
import pandas as pd
import talib

from risk.news_calendar import macro_events_between
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class BookBMacroBurstConfig:
    name: str = 'S80_book_b_macro_burst'
    pre_event_minutes: int = 120
    post_event_minutes: int = 240
    entry_bar_minutes: int = 5
    stop_buffer_atr: float = 0.10
    target_r: float = 3.0
    max_hold_minutes: int = 4 * 60
    allowed_events: tuple[str, ...] = ('FOMC', 'CPI', 'NFP')
    fixed_risk_usd: float = 10.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=0.04,
            max_notional_equity=1.2,
            daily_loss_fraction=0.12,
            weekly_loss_fraction=0.22,
            drawdown_halt_fraction=0.30,
            fee_bps=7.0,
            slippage_bps=3.0,
            min_reward_cost_ratio=1.5,
            leverage=6.0,
            max_margin_fraction=0.35,
            margin_safety_reserve=0.02,
            maker_fee_bps=7.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=60.0,
            fixed_risk_usd=self.fixed_risk_usd,
            max_positions=1,
            flip_on_opposite_signal=False,
        )


def macro_burst_features(minutes: pd.DataFrame, config: BookBMacroBurstConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, config.entry_bar_minutes)
    atr = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['atr'] = atr
    return bars


def generate_macro_burst_signals(
    bars: pd.DataFrame,
    config: BookBMacroBurstConfig,
    symbol: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> list[dict]:
    if bars.empty:
        return []
    start = window_start.to_pydatetime()
    end = window_end.to_pydatetime()
    events = [
        e for e in macro_events_between(start, end)
        if e['name'] in config.allowed_events
    ]
    records = []
    for event in events:
        event_ts = pd.Timestamp(event['datetime'])
        if event_ts.tzinfo is None:
            event_ts = event_ts.tz_localize('UTC')
        pre_start = event_ts - pd.Timedelta(minutes=config.pre_event_minutes)
        pre_end = event_ts
        post_end = event_ts + pd.Timedelta(minutes=config.post_event_minutes)
        pre = bars.loc[(bars.index >= pre_start) & (bars.index < pre_end)]
        if len(pre) < 3:
            continue
        pre_high = float(pre.high.max())
        pre_low = float(pre.low.min())
        if pre_high <= pre_low:
            continue
        post = bars.loc[(bars.index >= event_ts) & (bars.index < post_end)]
        for row in post.itertuples():
            atr = float(row.atr) if np.isfinite(row.atr) else 0.0
            if atr <= 0:
                continue
            side = 0
            if float(row.close) > pre_high:
                side = 1
            elif float(row.close) < pre_low:
                side = -1
            if side == 0:
                continue
            stop = (
                pre_low - config.stop_buffer_atr * atr
                if side == 1
                else pre_high + config.stop_buffer_atr * atr
            )
            reference = float(row.close)
            risk = side * (reference - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': row.Index,
                'side': side,
                'reference': reference,
                'stop': float(stop),
                'min_stop_atr': 0.3,
                'max_stop_atr': 6.0,
                'atr': atr,
                'score': 8,
                'setup': f'macro_burst_{event["name"]}',
                'setup_id': (
                    f'MB:v1:{symbol}:{event["name"]}:{event_ts.isoformat()}:{direction}'
                ),
            })
            break

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
