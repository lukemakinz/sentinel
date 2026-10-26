"""Diagnostic (not a gated protocol): among candidates that pass order
block + regime + OBV + OI (S43's original logic, unmodified), split by
S44C's liquidity_ok flag, run the FULL unfiltered candidate set through
execute_cluster once (development window, base costs), then join realized
trades back to their liquidity_ok tag by setup_id/timestamp to compare
the profit factor of the cohort S44C would have KEPT vs the cohort it
would have REMOVED. This answers a different question than the gated
protocol: not "does the filtered strategy pass", but "is the filter
actually separating good trades from bad ones, among trades that would
have executed anyway under one-global-position arbitration".
"""
from dataclasses import replace

from l1_filter.s44c_dynamic_liquidity_scalp import S44CLiquidityConfig, liquidity_features
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .scalp_data import load_archives
from collections import Counter
import numpy as np

TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-09-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'


def generate_unfiltered_signals(bars, config, symbol):
    """Identical to s44c_dynamic_liquidity_scalp.generate_s44c_signals
    EXCEPT the liquidity_ok gate is skipped (recorded, not enforced), so
    every order-block+regime+OBV+OI candidate is emitted regardless."""
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
    liquidity_ok = bars.liquidity_ok.to_numpy(dtype=bool)
    ob_bull_confirmed = bars.ob_bull_confirmed.to_numpy()
    ob_bull_top, ob_bull_bottom = bars.ob_bull_top.to_numpy(), bars.ob_bull_bottom.to_numpy()
    ob_bear_confirmed = bars.ob_bear_confirmed.to_numpy()
    ob_bear_top, ob_bear_bottom = bars.ob_bear_top.to_numpy(), bars.ob_bear_bottom.to_numpy()

    active = {1: [], -1: []}
    records = []
    for i in range(n):
        active[1] = [z for z in active[1] if z['expires'] > i]
        active[-1] = [z for z in active[-1] if z['expires'] > i]
        if ob_bull_confirmed[i] and np.isfinite(ob_bull_top[i]) and np.isfinite(ob_bull_bottom[i]):
            active[1].append({'top': float(ob_bull_top[i]), 'bottom': float(ob_bull_bottom[i]),
                              'expires': i + config.zone_ttl_bars})
        if ob_bear_confirmed[i] and np.isfinite(ob_bear_top[i]) and np.isfinite(ob_bear_bottom[i]):
            active[-1].append({'top': float(ob_bear_top[i]), 'bottom': float(ob_bear_bottom[i]),
                               'expires': i + config.zone_ttl_bars})
        if not np.isfinite(atr[i]):
            continue
        for side in (1, -1):
            if side == 1:
                touched = [z for z in active[1] if low[i] <= z['top'] and close[i] >= z['bottom']]
            else:
                touched = [z for z in active[-1] if high[i] >= z['bottom'] and close[i] <= z['top']]
            if not touched:
                continue
            for z in touched:
                active[side].remove(z)
            regime_ok = htf_trend_up[i] if side == 1 else htf_trend_down[i]
            if not (regime_ok and np.isfinite(htf_adx[i]) and htf_adx[i] >= config.adx_threshold):
                continue
            flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue
            if not np.isfinite(oi_change[i]):
                continue
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue
            # NOTE: no liquidity_ok gate here -- recorded as a tag instead.
            zone = touched[0]
            stop = (zone['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                    else zone['top'] + config.stop_buffer_atr_mult * atr[i])
            risk = side * (close[i] - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': bars.index[i], 'side': side, 'reference': float(close[i]),
                'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 3.0,
                'atr': float(atr[i]), 'score': 6,
                'setup': f's44c_unfiltered_{symbol}',
                'setup_id': f'S44Cdiag:v1:{symbol}:{direction}:{bars.index[i].isoformat()}',
                'liquidity_ok': bool(liquidity_ok[i]),
            })
    records.sort(key=lambda x: x['timestamp'])
    counts = Counter(x['timestamp'] for x in records)
    return [x for x in records if counts[x['timestamp']] == 1]


def main():
    config = S44CLiquidityConfig()
    data = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, '/tmp/sentinel-scalp-cache')
        metrics, _ = load_metrics(symbol, WARMUP, END, '/tmp/sentinel-scalp-cache')
        data[symbol] = minutes, funding, metrics

    tag_by_setup_id = {}
    raw = {}
    for symbol in TRADED:
        bars = liquidity_features(data[symbol][0], data[symbol][2], config)
        signals = generate_unfiltered_signals(bars, config, symbol)
        raw[symbol] = signals
        for s in signals:
            tag_by_setup_id[s['setup_id']] = s['liquidity_ok']

    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}
    result = execute_cluster(
        markets, raw, config.execution(), DEV_START, DEV_END,
        initial_capital=250, symbol_priority=TRADED,
    )
    trades = result['trades']
    print('total raw candidates:', sum(len(v) for v in raw.values()),
          '(liquidity_ok=True:', sum(1 for v in raw.values() for s in v if s['liquidity_ok']), ')')
    print('total REALIZED trades (one-global-position arbitration):', len(trades))

    def pf(group):
        gross_profit = sum(t['gross_pnl'] for t in group if t['gross_pnl'] > 0)
        gross_loss = -sum(t['gross_pnl'] for t in group if t['gross_pnl'] < 0)
        net = sum(t['pnl'] for t in group)
        wins = sum(1 for t in group if t['pnl'] > 0)
        return {
            'trades': len(group),
            'win_rate': wins / len(group) if group else None,
            'profit_factor': (gross_profit / gross_loss) if gross_loss > 0 else float('inf'),
            'net_pnl': net,
            'avg_r': sum(t['r_multiple'] for t in group) / len(group) if group else None,
        }

    kept, removed = [], []
    unmatched = 0
    for t in trades:
        tag = tag_by_setup_id.get(t['setup_id'])
        if tag is None:
            unmatched += 1
            continue
        (kept if tag else removed).append(t)

    print('unmatched (should be 0):', unmatched)
    print()
    print('=== REALIZED trades where liquidity_ok=True (S44C would KEEP) ===')
    print(pf(kept))
    print()
    print('=== REALIZED trades where liquidity_ok=False (S44C would REMOVE) ===')
    print(pf(removed))


if __name__ == '__main__':
    main()
