"""Research-only Bollinger regime routes for S13.

The indicator is one volatility/location evidence family, not several votes.
All bar indices are close-time availability timestamps.  Breakouts and
excursions are compared with bands frozen on the preceding closed bar.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class BollingerRouteConfig:
    name: str
    route: str
    period: int = 20
    deviations: float = 2.0
    bandwidth_lookback: int = 1920
    squeeze_quantile: float = 0.20
    hourly_bandwidth_lookback: int = 480
    hourly_extreme_quantile: float = 0.80
    target_r: float = 1.80

    def __post_init__(self):
        if self.route not in ('squeeze_expansion', 'liquidity_failure_smt'):
            raise ValueError('Unknown Bollinger route')
        if (self.period < 2 or self.deviations <= 0 or self.bandwidth_lookback < 20
                or not 0 < self.squeeze_quantile < 1
                or self.hourly_bandwidth_lookback < 20
                or not 0 < self.hourly_extreme_quantile < 1
                or self.target_r <= 1):
            raise ValueError('Invalid Bollinger parameters')

    def execution(self) -> ScalpConfig:
        is_limit = self.route == 'liquidity_failure_smt'
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r if not is_limit else 2.0,
            partial_r=0.90 if not is_limit else 1.0,
            partial_fraction=0.0,
            trailing=False,
            max_hold_minutes=180,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=5.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
        )


def central_variants() -> list[BollingerRouteConfig]:
    """Exactly two predeclared mechanical hypotheses; no parameter grid."""
    return [
        BollingerRouteConfig('S13_bb_squeeze_expansion', 'squeeze_expansion'),
        BollingerRouteConfig('S13_bb_liquidity_failure_smt', 'liquidity_failure_smt', target_r=2.0),
    ]


def _bands(close: pd.Series, period: int, deviations: float) -> pd.DataFrame:
    """Population-sigma bands, including only observations at or before index."""
    middle = close.rolling(period, min_periods=period).mean()
    sigma = close.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame({
        'bb_middle': middle,
        'bb_upper': middle + deviations * sigma,
        'bb_lower': middle - deviations * sigma,
        'bb_bandwidth': deviations * 2 * sigma / middle.where(middle > 0),
    }, index=close.index)


def _session_windows(index: pd.DatetimeIndex) -> list[tuple[str, str, pd.Timestamp, pd.Timestamp]]:
    local_dates = sorted(set(index.tz_convert('America/New_York').date))
    records = []
    for local_date in local_dates:
        midnight = pd.Timestamp(local_date, tz='America/New_York')
        for name, start_hour, end_hour in (
            ('london', 2, 5),
            ('new_york', 7, 11),
        ):
            start = midnight + pd.Timedelta(hours=start_hour)
            end = midnight + pd.Timedelta(hours=end_hour)
            records.append((str(local_date), name, start.tz_convert('UTC'), end.tz_convert('UTC')))
    return records


def _attach_frozen_session_boxes(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    result['session'] = None
    result['session_date'] = None
    result['box_high'] = np.nan
    result['box_low'] = np.nan
    for local_date, name, start, end in _session_windows(result.index):
        # The four-hour range ends at session open and never changes afterwards.
        box = result.loc[(result.index > start - pd.Timedelta(hours=4))
                         & (result.index <= start)]
        if len(box) < 16:
            continue
        mask = (result.index > start) & (result.index <= end)
        result.loc[mask, 'session'] = name
        result.loc[mask, 'session_date'] = local_date
        result.loc[mask, 'box_high'] = float(box.high.max())
        result.loc[mask, 'box_low'] = float(box.low.min())
    return result


def bollinger_features(
    minutes: pd.DataFrame,
    config: BollingerRouteConfig,
) -> pd.DataFrame:
    """Build causal 15m features and frozen ET-session ranges."""
    bars = resample_closed(minutes, 15)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bands = _bands(bars.close, config.period, config.deviations)
    bars = bars.join(bands)
    for column in ('bb_middle', 'bb_upper', 'bb_lower'):
        bars[f'{column}_prior'] = bars[column].shift(1)

    # Each cutoff excludes the value it classifies.  The breakout bar cannot
    # widen its own reference band or its own historical squeeze threshold.
    bars['bandwidth_cutoff'] = bars.bb_bandwidth.shift(1).rolling(
        config.bandwidth_lookback,
        min_periods=config.bandwidth_lookback,
    ).quantile(config.squeeze_quantile)
    bars['squeeze_state'] = (
        bars.bb_bandwidth.notna()
        & bars.bandwidth_cutoff.notna()
        & (bars.bb_bandwidth <= bars.bandwidth_cutoff)
    )
    bars['prior_squeeze_count'] = bars.squeeze_state.shift(1).rolling(
        4, min_periods=4).sum()
    bars['prior_volume_median'] = bars.volume.shift(1).rolling(20, min_periods=20).median()
    bars['relative_volume'] = bars.volume / bars.prior_volume_median.where(
        bars.prior_volume_median > 0)

    hourly = resample_closed(minutes, 60)
    hourly_bands = _bands(hourly.close, config.period, config.deviations)
    hourly = hourly.join(hourly_bands)
    hourly['bandwidth_extreme_cutoff'] = hourly.bb_bandwidth.shift(1).rolling(
        config.hourly_bandwidth_lookback,
        min_periods=config.hourly_bandwidth_lookback,
    ).quantile(config.hourly_extreme_quantile)
    hourly['hourly_bandwidth_extreme'] = (
        hourly.bb_bandwidth.notna()
        & hourly.bandwidth_extreme_cutoff.notna()
        & (hourly.bb_bandwidth > hourly.bandwidth_extreme_cutoff)
    )
    bars['hourly_bandwidth'] = hourly.bb_bandwidth.reindex(bars.index, method='ffill')
    bars['hourly_bandwidth_extreme_cutoff'] = hourly.bandwidth_extreme_cutoff.reindex(
        bars.index, method='ffill')
    bars['hourly_bandwidth_extreme'] = hourly.hourly_bandwidth_extreme.reindex(
        bars.index, method='ffill').eq(True)
    bars = _attach_frozen_session_boxes(bars)
    return bars


def _in_trading_window(timestamp: pd.Timestamp) -> bool:
    local = timestamp.tz_convert('America/New_York')
    minute = local.hour * 60 + local.minute
    return local.weekday() < 5 and (120 < minute <= 300 or 420 < minute <= 660)


def squeeze_expansion_signals(
    bars: pd.DataFrame,
    btc: pd.DataFrame,
    config: BollingerRouteConfig,
    symbol: str,
) -> list[dict]:
    """H1: trade the first qualified release from a contiguous squeeze episode."""
    if config.route != 'squeeze_expansion':
        raise ValueError('Wrong route config')
    btc = btc.reindex(bars.index)
    records = []
    consumed: set[pd.Timestamp] = set()
    last_squeeze_i = None
    episode_start = None

    for i, row in enumerate(bars.itertuples()):
        if bool(row.squeeze_state):
            if last_squeeze_i is None or i - last_squeeze_i > 1:
                episode_start = row.Index
            last_squeeze_i = i
        elif last_squeeze_i is not None and i - last_squeeze_i > 4:
            episode_start = None
        if episode_start is None or episode_start in consumed or not _in_trading_window(row.Index):
            continue
        btc_row = btc.loc[row.Index]
        required = (
            np.isfinite(row.atr)
            and np.isfinite(row.bb_upper_prior)
            and np.isfinite(row.bb_lower_prior)
            and np.isfinite(row.relative_volume)
            and row.prior_squeeze_count >= 3
            and np.isfinite(btc_row.bb_middle_prior)
        )
        if not required:
            continue
        candle_range = row.high - row.low
        body_ratio = abs(row.close - row.open) / max(candle_range, 1e-12)
        if not (body_ratio >= 0.65 and 0.8 * row.atr <= candle_range <= 2.0 * row.atr
                and row.relative_volume >= 1.25):
            continue
        for side in (1, -1):
            band = row.bb_upper_prior if side == 1 else row.bb_lower_prior
            directional = side * (row.close - band) > 0
            btc_aligned = side * (btc_row.close - btc_row.bb_middle_prior) > 0
            if not directional or not btc_aligned:
                continue
            stop = row.low - 0.10 * row.atr if side == 1 else row.high + 0.10 * row.atr
            risk = side * (row.close - stop)
            if not 0.50 * row.atr <= risk <= 1.50 * row.atr:
                continue
            records.append({
                'timestamp': row.Index,
                'side': side,
                'reference': float(row.close),
                'stop': float(stop),
                'min_stop_atr': 0.50,
                'max_stop_atr': 1.50,
                'atr': float(row.atr),
                'score': 6,
                'setup': 'bb_squeeze_expansion',
                'setup_id': f'BBSE:v1:{symbol}:{episode_start.isoformat()}',
                'episode_start': episode_start.isoformat(),
            })
            consumed.add(episode_start)
            break
    return records


def liquidity_failure_smt_signals(
    bars: pd.DataFrame,
    btc: pd.DataFrame,
    config: BollingerRouteConfig,
    symbol: str,
) -> list[dict]:
    """H2: fade an extreme session-range failure only when BTC does not confirm."""
    if config.route != 'liquidity_failure_smt':
        raise ValueError('Wrong route config')
    btc = btc.reindex(bars.index)
    records = []
    used = set()
    btc_confirmed: dict[tuple, bool] = {}
    for row in bars.itertuples():
        if row.session is None or not _in_trading_window(row.Index):
            continue
        btc_row = btc.loc[row.Index]
        required = all(np.isfinite(value) for value in (
            row.atr, row.bb_middle_prior, row.bb_upper_prior, row.bb_lower_prior,
            row.hourly_bandwidth, row.hourly_bandwidth_extreme_cutoff,
            row.box_high, row.box_low,
            btc_row.atr, btc_row.box_high, btc_row.box_low,
        ))
        if not required or row.hourly_bandwidth_extreme:
            continue
        candle_range = row.high - row.low
        if candle_range <= 0:
            continue
        for side in (1, -1):
            key = (row.session_date, row.session, side)
            if key in used:
                continue
            box = row.box_low if side == 1 else row.box_high
            band = row.bb_lower_prior if side == 1 else row.bb_upper_prior
            extreme = row.low if side == 1 else row.high
            btc_box = btc_row.box_low if side == 1 else btc_row.box_high
            btc_extreme = btc_row.low if side == 1 else btc_row.high
            # SMT is session-level: once BTC has swept its own frozen range,
            # a later alt sweep in the same session is confirmation, not SMT.
            if side * (btc_extreme - btc_box) < -0.05 * btc_row.atr:
                btc_confirmed[key] = True
            swept_box = side * (extreme - box) < -0.05 * row.atr
            swept_band = side * (extreme - band) < -0.05 * row.atr
            reclaimed = side * (row.close - box) > 0 and side * (row.close - band) > 0
            directional_body = side * (row.close - row.open) > 0
            close_location = ((row.close - row.low) / candle_range if side == 1
                              else (row.high - row.close) / candle_range)
            btc_nonconfirmation = not btc_confirmed.get(key, False)
            if not (swept_box and swept_band and reclaimed and directional_body
                    and close_location >= 0.65 and btc_nonconfirmation):
                continue
            entry = (row.open + row.close) / 2
            stop = row.low - 0.10 * row.atr if side == 1 else row.high + 0.10 * row.atr
            risk = side * (entry - stop)
            if not 0.50 * row.atr <= risk <= 1.50 * row.atr:
                used.add(key)
                continue
            two_r = entry + side * 2.0 * risk
            target = min(two_r, row.bb_middle_prior) if side == 1 else max(two_r, row.bb_middle_prior)
            reward = side * (target - entry)
            if reward < 1.25 * risk:
                used.add(key)
                continue
            records.append({
                'timestamp': row.Index,
                'side': side,
                'reference': float(row.close),
                'limit_price': float(entry),
                'limit_ttl_minutes': 30,
                'stop': float(stop),
                'min_stop_atr': 0.50,
                'max_stop_atr': 1.50,
                'target_price': float(target),
                'min_target_r': 1.25,
                'atr': float(row.atr),
                'score': 6,
                'setup': 'bb_liquidity_failure_smt',
                'setup_id': (
                    f'BBLR:v1:{symbol}:{"long" if side == 1 else "short"}:'
                    f'{row.session}:{row.session_date}'
                ),
            })
            used.add(key)
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]


def generate_bollinger_signals(
    bars: pd.DataFrame,
    btc: pd.DataFrame,
    config: BollingerRouteConfig,
    symbol: str,
) -> list[dict]:
    if config.route == 'squeeze_expansion':
        return squeeze_expansion_signals(bars, btc, config, symbol)
    return liquidity_failure_smt_signals(bars, btc, config, symbol)
