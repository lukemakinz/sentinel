"""S45 diagnostic (not a gated protocol, no new entry logic): tags S20
H1's already-realized trades -- development, validation AND retrospective
windows, computed here since S20 never reached retrospective (it failed
the validation gate, so the project's runners never computed it) -- with
a causal BTC-derived market regime (TREND/CHOP/SHOCK) and funding state
at entry, then reports PF/expectancy/long-PF/short-PF per regime per
window. A regime only earns the right to become an actual filter if its
effect direction is the same sign in all three windows -- reversing sign
between windows means reject, regardless of how good the average looks.

Regime formula (BTC daily bars, causal: today's regime uses only data
through YESTERDAY's close, via an explicit shift(1) before reindexing to
trade timestamps):
    trend_strength = abs(EMA20 - EMA100) / ATR14
    realized_vol    = std(daily log returns, 7d)
    vol_percentile  = rolling percentile rank of realized_vol over 90d
    regime = SHOCK if vol_percentile > 0.90
             else TREND if trend_strength > 1.0
             else CHOP
trend_strength's threshold (1.0, i.e. the EMA20/EMA100 gap exceeds one
ATR) is chosen a priori, consistent with this project's existing
convention of ATR-relative displacement thresholds (e.g. order block
displacement_atr_mult=1.5) -- not fit to any outcome.
"""
import numpy as np
import pandas as pd
import talib

from l1_filter.order_block_oi_confirmation_scalp import OrderBlockOIConfig, generate_order_block_oi_signals, oi_features
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .scalp_data import load_archives

TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def compute_btc_regime(cache: str) -> pd.Series:
    minutes, _, _ = load_archives('BTCUSDT', WARMUP, END, cache)
    daily = minutes.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    close = daily.close.to_numpy()
    ema20 = talib.EMA(close, timeperiod=20)
    ema100 = talib.EMA(close, timeperiod=100)
    atr14 = talib.ATR(daily.high.to_numpy(), daily.low.to_numpy(), close, timeperiod=14)
    trend_strength = np.abs(ema20 - ema100) / atr14

    log_ret = np.diff(np.log(close), prepend=np.nan)
    realized_vol = pd.Series(log_ret, index=daily.index).rolling(7, min_periods=7).std()
    vol_percentile = realized_vol.rolling(90, min_periods=30).apply(
        lambda arr: (arr <= arr[-1]).mean(), raw=True)

    regime = pd.Series('CHOP', index=daily.index, dtype=object)
    regime[trend_strength > 1.0] = 'TREND'
    regime[vol_percentile > 0.90] = 'SHOCK'  # SHOCK overrides TREND, checked last
    regime[~np.isfinite(trend_strength) | vol_percentile.isna()] = None

    # Causal: a trade on day D may only see regime known as of day D-1's close.
    regime = regime.shift(1)
    return regime


def main():
    cache = '/tmp/sentinel-scalp-cache'
    btc_regime_daily = compute_btc_regime(cache)

    config = OrderBlockOIConfig('S20_H1_diagnostic', 'oi', partial_r=1.5, trail_atr=2.5, target_r=8.0)
    data = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        data[symbol] = minutes, funding, metrics

    raw = {}
    funding_at = {}
    for symbol in TRADED:
        bars = oi_features(data[symbol][0], data[symbol][2], config)
        signals = generate_order_block_oi_signals(bars, config, symbol)
        raw[symbol] = signals
        funding_at[symbol] = data[symbol][1]  # funding rate series, sparse, at settlement times

    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}

    def regime_at(ts):
        day = pd.Timestamp(ts).normalize()
        idx = btc_regime_daily.index.searchsorted(day, side='right') - 1
        if idx < 0:
            return None
        return btc_regime_daily.iloc[idx]

    def funding_sign_at(symbol, ts):
        series = funding_at[symbol]
        prior = series[series.index <= ts]
        if prior.empty:
            return None
        return 'positive' if prior.iloc[-1] > 0 else ('negative' if prior.iloc[-1] < 0 else 'zero')

    def summarize(group):
        if not group:
            return {'n': 0, 'PF': None, 'expectancy_R': None, 'win_rate': None}
        gains = sum(t['pnl'] for t in group if t['pnl'] > 0)
        losses = -sum(t['pnl'] for t in group if t['pnl'] < 0)
        wins = sum(1 for t in group if t['pnl'] > 0)
        return {
            'n': len(group),
            'PF': round(gains / losses, 3) if losses > 0 else (float('inf') if gains > 0 else None),
            'expectancy_R': round(sum(t['r_multiple'] for t in group) / len(group), 3),
            'win_rate': round(wins / len(group), 3),
        }

    for window, (start, end) in WINDOWS.items():
        result = execute_cluster(markets, raw, config.execution(), start, end,
                                  initial_capital=250, symbol_priority=TRADED)
        trades = result['trades']
        for t in trades:
            t['regime'] = regime_at(t['opened_at'])
            t['funding_state'] = funding_sign_at(t['symbol'], t['opened_at'])

        print(f'\n=== {window} ({start} to {end}) -- total realized: {len(trades)} ===')
        print(f'{"regime":8s} {"n":>4s} {"PF":>8s} {"E[R]":>8s} {"WR":>6s} | '
              f'{"long n":>7s} {"long PF":>8s} | {"short n":>8s} {"short PF":>9s}')
        for regime in ('TREND', 'CHOP', 'SHOCK', None):
            grp = [t for t in trades if t['regime'] == regime]
            s = summarize(grp)
            longs = summarize([t for t in grp if t['side'] == 'LONG'])
            shorts = summarize([t for t in grp if t['side'] == 'SHORT'])
            label = regime or 'unknown'
            print(f'{label:8s} {s["n"]:>4d} {str(s["PF"]):>8s} {str(s["expectancy_R"]):>8s} '
                  f'{str(s["win_rate"]):>6s} | {longs["n"]:>7d} {str(longs["PF"]):>8s} | '
                  f'{shorts["n"]:>8d} {str(shorts["PF"]):>9s}')

        for state in ('positive', 'negative', 'zero', None):
            grp = [t for t in trades if t['funding_state'] == state]
            s = summarize(grp)
            print(f'  funding={str(state):9s} n={s["n"]:>4d} PF={str(s["PF"]):>8s} '
                  f'E[R]={str(s["expectancy_R"]):>8s} WR={str(s["win_rate"]):>6s}')


if __name__ == '__main__':
    main()
