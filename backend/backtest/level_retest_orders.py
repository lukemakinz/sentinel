"""Causal materialization of independently resting level-retest orders."""
from copy import deepcopy

import pandas as pd


def materialize_first_retests(minutes, armed_signals, penetration_bps=2.0):
    """Move each pre-armed signal to its first executable touch.

    This lets independent resting orders coexist across symbols while the
    account replay still enforces one *open* position.  The original arm time
    remains in evidence.  Gaps through the limit are skipped conservatively;
    minute OHLC cannot prove the fill path or queue priority in that case.
    """
    penetration = penetration_bps / 10000
    materialized = []
    for original in armed_signals:
        signal = deepcopy(original)
        armed_at = pd.Timestamp(signal['timestamp'])
        expires = armed_at + pd.Timedelta(
            minutes=signal.get('limit_ttl_minutes', 15))
        limit = float(signal['limit_price'])
        side = int(signal['side'])
        future = minutes.loc[(minutes.index >= armed_at) & (minutes.index < expires)]
        threshold = limit * (1 - side * penetration)
        for row in future.itertuples():
            touched = row.low <= threshold if side == 1 else row.high >= threshold
            if not touched:
                continue
            # The generic simulator accepts a resting limit only while the bar
            # opens on the pre-touch side.  A gap-through is intentionally not
            # reconstructed from OHLC.
            if side * (row.open - limit) <= 0:
                break
            evidence = dict(signal.get('evidence') or {})
            evidence.update({
                'armed_at': str(armed_at),
                'first_retest_at': str(row.Index),
                'independent_resting_order': True,
                'penetration_bps': float(penetration_bps),
            })
            signal['timestamp'] = row.Index
            signal['limit_ttl_minutes'] = 1
            signal['evidence'] = evidence
            materialized.append(signal)
            break
    materialized.sort(key=lambda item: item['timestamp'])
    return materialized
