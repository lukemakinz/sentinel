"""S46: S20 H1's exact entry/exit, with exactly one additional rule --
reject any candidate whose most recently known funding rate (strictly
BEFORE the signal's own timestamp) is negative or unknown. Nothing else
changes: same order block/regime/OBV/OI logic (S20's original, unfixed
sign convention -- S44A's fix was tested separately and did not help),
same universe, same exit management.

This rule was discovered via a diagnostic (S45/S45b/S45c) run on these
same historical windows, then frozen by a decision rule agreed BEFORE
seeing S45c's regression/bootstrap output:
    negative_funding coefficient (controlling for symbol/window/side):
        beta = -0.593R, HC3 p=0.002, 95% CI [-0.961, -0.225]
    bootstrap (10000 resamples): median -0.592R, 95% CI [-0.978, -0.241],
        P(beta<0) = 99.97%
    leave-one-symbol-out: effect persists in validation and retrospective
        with SOL excluded; only development flips sign without SOL --
        judged "does not vanish", not a disqualifying reversal.

Any backtest of THIS module on the development/validation/retrospective
windows is therefore IN-SAMPLE / DISCOVERY-AFFECTED, not an independent
validation -- the funding<0 veto was chosen because it looked good on
exactly this data. The real gate is genuinely new data collected after
this rule was frozen (forward paper trading). The historical run exists
for characterization only (trade count, drawdown, symbol/side mix,
monthly shape), not as a promotion gate.

No magnitude threshold, no funding moving average, no funding momentum,
no symbol-specific rule, no combination with S44A's OI fix, S44C's
liquidity filter, or the S45 regime filter, no leverage/sizing change --
all deliberately excluded to keep this the single clean hypothesis that
was actually tested and frozen.
"""
from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
)


def funding_rate_at(funding_series, ts):
    """Most recently known funding rate strictly before `ts` (never at or
    after -- a rate settling exactly at the entry minute is treated as not
    yet known). Returns None if no funding history exists before `ts`."""
    prior = funding_series[funding_series.index < ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def s46_execution() -> OrderBlockOIConfig:
    """S20 H1 exactly: route='oi', partial_r=1.5, trail_atr=2.5, target_r=8.0."""
    return OrderBlockOIConfig('S46_funding_veto', 'oi', partial_r=1.5, trail_atr=2.5, target_r=8.0)


def generate_funding_vetoed_signals(bars, funding_series, symbol) -> list[dict]:
    """S20 H1's raw candidates, with the funding veto applied BEFORE
    execution -- not filtered from an already-realized trade list. This
    matters: execute_cluster holds one global position, so removing a
    candidate here can free a slot for a different candidate that would
    never have been reached in the unfiltered backtest."""
    config = s46_execution()
    candidates = generate_order_block_oi_signals(bars, config, symbol)
    kept = []
    for signal in candidates:
        rate = funding_rate_at(funding_series, signal['timestamp'])
        if rate is None or rate < 0:
            continue
        kept.append(signal)
    return kept
