"""S29: let a classifier find its own combination of the same causal
features every hand-crafted rule in S16-S28 already drew from (regime
strength, OBV/CVD flow, OI change, recent order-block presence, RSI,
volatility), instead of another single hand-picked AND/OR threshold.

Strict train/test discipline: the model is fit ONLY on the development
window (2025-08-01..2026-02-01); the decision threshold (0.55) is fixed
BEFORE looking at any validation-window result — not chosen by scanning
thresholds against the test set, which would be p-hacking with extra
steps. Validation (2026-02-01..2026-04-01) is scored exactly once. Labels
use a simple triple-barrier (+1.5x ATR before -1.0x ATR within 16 bars,
i.e. 4h) — a fixed-horizon proxy for a good trade, not S20's patient
trailing exit; this isolates the entry-selection question from exit
sophistication, a disclosed simplification.

This is exploratory research, not a frozen protocol with promotion
gates — it exists to answer one question honestly: does a model find a
combination of existing signals with more edge than any hand-crafted rule
tested so far? Reuses cached archives from S18/S20 — no new data source.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from l1_filter.order_block_oi_cvd_scalp import OrderBlockCVDConfig, cvd_features
from .metrics_data import load_metrics
from .scalp_data import load_archives


SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-04-01'
DEV_WINDOW = (pd.Timestamp('2025-08-01', tz='UTC'), pd.Timestamp('2026-02-01', tz='UTC'))
VAL_WINDOW = (pd.Timestamp('2026-02-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC'))
BARRIER_BARS = 16       # 4h on 15m bars
REWARD_ATR = 1.5
RISK_ATR = 1.0
DECISION_THRESHOLD = 0.55   # fixed before any validation-window result is seen
FEATURES = ['adx', 'obv_diff', 'cvd_diff', 'oi_chg', 'ob_recent', 'atr_pct', 'rsi_side']


def _label_triple_barrier(high, low, close, atr, side, k=BARRIER_BARS,
                          reward_mult=REWARD_ATR, risk_mult=RISK_ATR):
    n = len(close)
    labels = np.full(n, np.nan)
    for i in range(n - k):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        entry = close[i]
        target = entry + side * reward_mult * atr[i]
        stop = entry - side * risk_mult * atr[i]
        label = 0.0
        for j in range(i + 1, i + k + 1):
            if side == 1:
                if low[j] <= stop:
                    break
                if high[j] >= target:
                    label = 1.0
                    break
            else:
                if high[j] >= stop:
                    break
                if low[j] <= target:
                    label = 1.0
                    break
        labels[i] = label
    return labels


def _build_side_rows(bars: pd.DataFrame, side: int, symbol: str) -> pd.DataFrame:
    regime = bars.htf_trend_up if side == 1 else bars.htf_trend_down
    high, low, close, atr = (bars.high.to_numpy(), bars.low.to_numpy(),
                             bars.close.to_numpy(), bars.atr.to_numpy())
    label = _label_triple_barrier(high, low, close, atr, side)

    ob_confirmed = bars.ob_bull_confirmed if side == 1 else bars.ob_bear_confirmed
    ob_recent = ob_confirmed.rolling(8, min_periods=1).max().astype(bool)

    frame = pd.DataFrame({
        'timestamp': bars.index,
        'symbol': symbol,
        'side': side,
        'adx': bars.htf_adx.to_numpy(),
        'obv_diff': side * (bars.obv - bars.obv_ema).to_numpy(),
        'cvd_diff': side * (bars.cvd - bars.cvd_ema).to_numpy(),
        'oi_chg': side * bars.oi_change.to_numpy(),
        'ob_recent': ob_recent.astype(float).to_numpy(),
        'atr_pct': (bars.atr / bars.close).to_numpy(),
        'rsi_side': np.where(side == 1, bars.rsi14, 100 - bars.rsi14),
        'label': label,
    })
    frame = frame.loc[regime.to_numpy() & frame[FEATURES + ['label']].notna().all(axis=1)]
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s29_ml_classifier')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    config = OrderBlockCVDConfig('S29_ml_features', 'oi_cvd_flow')
    rows = []
    for symbol in SYMBOLS:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, str(args.cache))
        metrics, _ = load_metrics(symbol, WARMUP, END, str(args.cache))
        bars = cvd_features(minutes, metrics, config)
        for side in (1, -1):
            rows.append(_build_side_rows(bars, side, symbol))
        print(symbol, 'features built', flush=True)

    dataset = pd.concat(rows, ignore_index=True)
    dataset['timestamp'] = pd.to_datetime(dataset['timestamp'], utc=True)
    train = dataset[(dataset.timestamp >= DEV_WINDOW[0]) & (dataset.timestamp < DEV_WINDOW[1])]
    test = dataset[(dataset.timestamp >= VAL_WINDOW[0]) & (dataset.timestamp < VAL_WINDOW[1])]

    model = HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.05, max_iter=200, random_state=13,
        l2_regularization=1.0)
    model.fit(train[FEATURES], train['label'])

    train_pred = model.predict_proba(train[FEATURES])[:, 1]
    train_auc = roc_auc_score(train['label'], train_pred)

    test_pred = model.predict_proba(test[FEATURES])[:, 1]
    test_auc = roc_auc_score(test['label'], test_pred)

    def _expectancy_r(labels: pd.Series) -> float:
        win_rate = labels.mean()
        return win_rate * REWARD_ATR - (1 - win_rate) * RISK_ATR

    base_rate_train = train['label'].mean()
    base_rate_test = test['label'].mean()
    selected = test.loc[test_pred >= DECISION_THRESHOLD]
    selected_train = train.loc[train_pred >= DECISION_THRESHOLD]

    report = {
        'train_rows': len(train), 'test_rows': len(test),
        'train_auc': float(train_auc), 'test_auc': float(test_auc),
        'base_rate_train': float(base_rate_train), 'base_rate_test': float(base_rate_test),
        'base_expectancy_r_train': float(_expectancy_r(train['label'])),
        'base_expectancy_r_test': float(_expectancy_r(test['label'])),
        'decision_threshold': DECISION_THRESHOLD,
        'selected_train_rows': int(len(selected_train)),
        'selected_train_win_rate': float(selected_train['label'].mean()) if len(selected_train) else None,
        'selected_train_expectancy_r': float(_expectancy_r(selected_train['label'])) if len(selected_train) else None,
        'selected_test_rows': int(len(selected)),
        'selected_test_win_rate': float(selected['label'].mean()) if len(selected) else None,
        'selected_test_expectancy_r': float(_expectancy_r(selected['label'])) if len(selected) else None,
    }
    print(report)

    (output / 'summary.json').write_text(pd.Series(report).to_json(indent=2))

    if hasattr(model, 'feature_importances_'):
        (output / 'feature_importances.json').write_text(
            pd.Series(model.feature_importances_, index=FEATURES).to_json(indent=2))
    else:
        try:
            from sklearn.inspection import permutation_importance
            perm = permutation_importance(model, test[FEATURES], test['label'],
                                          n_repeats=5, random_state=13, scoring='roc_auc')
            (output / 'feature_importances.json').write_text(
                pd.Series(perm.importances_mean, index=FEATURES).to_json(indent=2))
        except Exception as exc:
            print('permutation importance failed:', exc)


if __name__ == '__main__':
    main()
