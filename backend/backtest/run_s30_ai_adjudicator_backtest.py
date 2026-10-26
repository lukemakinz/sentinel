"""S30: retrospective test of the AI adjudicator (scalp_monitor.ai_adjudicator)
on S20 H1's raw candidate queue (development window, ETH/SOL/BNB).

Each candidate is shown to gpt-4o-mini as ANONYMIZED, normalized readings
only — no symbol, no date, no raw price — and the model independently picks
LONG / SHORT / PASS. This anonymization is what makes a retrospective run
defensible: the historical-leakage risk this project has always flagged
for AI backtesting (the model may have seen a named symbol's specific
period during its own training) is greatly reduced when it is never told
which symbol or date it is looking at. It is a mitigation, not a proof of
zero leakage, and is reported as such.

Outcome is a simple triple-barrier (does the trade reach +1.5x ATR before
-1.0x ATR within 16 bars), reusing the exact same labeling as S29's ML
experiment for methodological consistency — NOT S20's full patient
trailing exit; that is a disclosed simplification, isolating the
selection question from exit sophistication.

Real, metered API calls — every call's token usage and estimated cost is
recorded and totalled.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
)
from l1_filter.order_block_oi_cvd_scalp import OrderBlockCVDConfig, cvd_features
from scalp_monitor.ai_adjudicator import adjudicate
from .metrics_data import load_metrics
from .run_s29_ml_classifier_research import _label_triple_barrier
from .scalp_data import load_archives


SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WINDOWS = {
    'development': ('2025-04-01', '2026-02-01',
                    pd.Timestamp('2025-08-01', tz='UTC'), pd.Timestamp('2026-02-01', tz='UTC')),
    'validation': ('2025-04-01', '2026-04-01',
                  pd.Timestamp('2026-02-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC')),
}
LOOKBACK_CANDLES = 8


def _build_candidate_context(bars: pd.DataFrame, i: int, side: int) -> dict:
    row = bars.iloc[i]
    atr = float(row.atr)
    zone_top, zone_bottom = (
        (row.ob_bull_top, row.ob_bull_bottom) if side == 1 else (row.ob_bear_top, row.ob_bear_bottom))
    displacement_atr = float(abs(zone_top - zone_bottom) / atr) if atr > 0 else None
    recent = bars.iloc[max(0, i - LOOKBACK_CANDLES):i + 1]
    recent_pct = (recent.close.pct_change().dropna() * 100).round(3).tolist()
    return {
        'adx': round(float(row.htf_adx), 2),
        'regime': 'up' if side == 1 else 'down',
        'obv_diff_for_regime_direction': round(side * float(row.obv - row.obv_ema), 4),
        'cvd_diff_for_regime_direction': round(side * float(row.cvd - row.cvd_ema), 4),
        'oi_change_for_regime_direction': round(side * float(row.oi_change), 4) if np.isfinite(row.oi_change) else None,
        'rsi_for_regime_direction': round(float(row.rsi14) if side == 1 else 100 - float(row.rsi14), 2),
        'displacement_atr': round(displacement_atr, 3) if displacement_atr is not None else None,
        'atr_pct': round(atr / float(row.close) * 100, 4),
        'recent_candles_pct': recent_pct,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s30_ai_adjudicator')
    parser.add_argument('--limit', type=int, default=None, help='cap number of AI calls (pilot runs)')
    parser.add_argument('--window', choices=('development', 'validation'), default='development')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    warmup, end, window_start, window_end = WINDOWS[args.window]
    suffix = '' if args.window == 'development' else f'_{args.window}'

    config = OrderBlockOIConfig('S30_ai_source', route='oi', partial_r=1.5, trail_atr=2.5, target_r=8.0)
    cvd_config = OrderBlockCVDConfig('S30_ai_features', 'oi_cvd_flow')

    all_rows = []
    for symbol in SYMBOLS:
        minutes, funding, _ = load_archives(symbol, warmup, end, str(args.cache))
        metrics, _ = load_metrics(symbol, warmup, end, str(args.cache))
        bars = cvd_features(minutes, metrics, cvd_config)
        bars['toptrader_zscore'] = 0.0  # unused by route='oi', but the function reads the column
        signals = generate_order_block_oi_signals(bars, config, symbol)
        high, low, close, atr = (bars.high.to_numpy(), bars.low.to_numpy(),
                                 bars.close.to_numpy(), bars.atr.to_numpy())
        label_long = _label_triple_barrier(high, low, close, atr, 1)
        label_short = _label_triple_barrier(high, low, close, atr, -1)
        for signal in signals:
            ts = signal['timestamp']
            if not (window_start <= ts < window_end):
                continue
            i = bars.index.get_loc(ts)
            side = signal['side']
            label = label_long[i] if side == 1 else label_short[i]
            if not np.isfinite(label):
                continue
            context = _build_candidate_context(bars, i, side)
            if any(v is None for v in context.values()):
                continue
            all_rows.append({'symbol': symbol, 'timestamp': ts, 'side': side,
                             'label': label, 'context': context})
        print(symbol, 'candidates ready:', len([r for r in all_rows if r['symbol'] == symbol]), flush=True)

    if args.limit:
        all_rows = all_rows[:args.limit]
    print('total candidates for AI review:', len(all_rows), flush=True)

    results, total_cost, errors = [], 0.0, 0
    for n, row in enumerate(all_rows):
        try:
            verdict, usage = adjudicate(row['context'])
        except Exception as exc:
            errors += 1
            print('AI call failed:', exc, flush=True)
            continue
        total_cost += usage['cost_usd']
        results.append({**row, 'verdict': verdict['verdict'],
                        'confidence': verdict['confidence'], 'reasoning': verdict['reasoning'],
                        'usage': usage})
        if (n + 1) % 25 == 0:
            print(f'{n + 1}/{len(all_rows)} reviewed, running cost ${total_cost:.4f}', flush=True)

    def _expectancy_r(labels) -> float:
        wr = float(np.mean(labels))
        return wr * 1.5 - (1 - wr) * 1.0

    baseline_labels = [r['label'] for r in results]
    agree = [r for r in results
            if (r['verdict'] == 'LONG' and r['side'] == 1)
            or (r['verdict'] == 'SHORT' and r['side'] == -1)]
    disagree = [r for r in results
               if (r['verdict'] == 'LONG' and r['side'] == -1)
               or (r['verdict'] == 'SHORT' and r['side'] == 1)]
    passed = [r for r in results if r['verdict'] == 'PASS']

    summary = {
        'candidates_reviewed': len(results),
        'api_errors': errors,
        'total_estimated_cost_usd': round(total_cost, 4),
        'verdict_counts': {
            'agree_with_regime': len(agree), 'disagree_with_regime': len(disagree),
            'pass': len(passed),
        },
        'baseline_win_rate': round(float(np.mean(baseline_labels)), 4) if results else None,
        'baseline_expectancy_r': round(_expectancy_r(baseline_labels), 4) if results else None,
        'agree_win_rate': round(float(np.mean([r['label'] for r in agree])), 4) if agree else None,
        'agree_expectancy_r': round(_expectancy_r([r['label'] for r in agree]), 4) if agree else None,
        'disagree_win_rate': round(float(np.mean([r['label'] for r in disagree])), 4) if disagree else None,
        'note': ('disagree cohort has no valid stop/target from the original signal '
                '(opposite side) — win_rate shown uses the ORIGINAL side\'s label for '
                'reference only, not a tradeable outcome'),
    }
    print(json.dumps(summary, indent=2))
    (output / f'summary{suffix}.json').write_text(json.dumps(summary, indent=2, default=str))
    (output / f'decisions{suffix}.json').write_text(json.dumps(
        [{k: v for k, v in r.items() if k != 'context'} | {'context': r['context']} for r in results],
        indent=2, default=str))


if __name__ == '__main__':
    main()
