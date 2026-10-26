"""Frozen GO/KILL decision logic for S46's forward paper test. This is
the ONLY code allowed to render a verdict on S46 forward data -- written
and frozen BEFORE any forward trade exists, so the thresholds cannot be
adjusted after seeing how the test is going. See
docs/research/s46_funding_veto/FORWARD_PROTOCOL.md for the full
rationale and checkpoint schedule.

Uses a WEEKLY BLOCK bootstrap (not a per-trade bootstrap): resamples
whole ISO weeks with replacement, not individual trades. S45c's own
bootstrap resampled trades independently and flagged this as a known
gap (crypto trades can be time-correlated within a week); the forward
decision -- the one that actually matters for real capital -- uses the
more conservative method.

Expected input: a list of dicts, one per closed forward paper trade,
each with at least: 'opened_at' (ISO string or Timestamp), 'pnl' (net,
post-cost, the real paper-fill result), 'r_multiple'.
"""
from collections import defaultdict

import numpy as np
import pandas as pd

# Frozen thresholds -- do not edit after forward data collection starts.
CHECKPOINT_MIN_TRADES = 30          # early-warning only, circuit breakers only
CIRCUIT_BREAKER_MAX_LOSS_USD = -20.0     # worse than any historical window's stress net_pnl (-$11.90)
CIRCUIT_BREAKER_MAX_LOSING_STREAK = 13   # historical max was 9 (development, base costs)

PRIMARY_CHECKPOINT_TRADES = 100
PRIMARY_CHECKPOINT_DAYS = 180
FINAL_CHECKPOINT_TRADES = 200        # one extension only, then a forced decision
FINAL_CHECKPOINT_DAYS = 360

GO_PF_MIN = 1.10
GO_PF_STRESS_MIN = 1.00
BOOTSTRAP_RESAMPLES = 2000


def _profit_factor(trades):
    gains = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in trades if t['pnl'] < 0)
    if losses <= 0:
        return float('inf') if gains > 0 else None
    return gains / losses


def _longest_losing_streak(trades):
    ordered = sorted(trades, key=lambda t: t['opened_at'])
    longest = streak = 0
    for t in ordered:
        streak = streak + 1 if t['pnl'] < 0 else 0
        longest = max(longest, streak)
    return longest


def _weekly_blocks(trades):
    blocks = defaultdict(list)
    for t in trades:
        ts = pd.Timestamp(t['opened_at'])
        week = (ts.tz_localize(None) if ts.tzinfo is not None else ts).to_period('W')
        blocks[week].append(t)
    return list(blocks.values())


def weekly_block_bootstrap_mean_r(trades, resamples=BOOTSTRAP_RESAMPLES, seed=42):
    """95% CI for mean R via block bootstrap over ISO weeks (not trades),
    so within-week correlation isn't treated as independent evidence."""
    blocks = _weekly_blocks(trades)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(resamples):
        chosen = [blocks[i] for i in rng.integers(0, len(blocks), size=len(blocks))]
        pooled = [t['r_multiple'] for block in chosen for t in block]
        if pooled:
            means.append(float(np.mean(pooled)))
    means = np.asarray(means)
    return {
        'median': float(np.median(means)),
        'ci_95': (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))),
        'p_mean_r_below_0': float(np.mean(means < 0)),
        'n_weekly_blocks': len(blocks),
    }


def check_circuit_breakers(trades):
    """Continuous monitoring, independent of checkpoints -- either trips
    immediately or it doesn't. Not subject to any extension."""
    cumulative = 0.0
    for t in sorted(trades, key=lambda t: t['opened_at']):
        cumulative += t['pnl']
        if cumulative <= CIRCUIT_BREAKER_MAX_LOSS_USD:
            return 'KILL', f'cumulative pnl {cumulative:.2f} breached {CIRCUIT_BREAKER_MAX_LOSS_USD}'
    streak = _longest_losing_streak(trades)
    if streak >= CIRCUIT_BREAKER_MAX_LOSING_STREAK:
        return 'KILL', f'losing streak {streak} >= {CIRCUIT_BREAKER_MAX_LOSING_STREAK}'
    return None, None


def evaluate_checkpoint(trades, stress_replay_trades, elapsed_days, extension_used=False):
    """`trades`: actual paper fills (real costs as experienced).
    `stress_replay_trades`: the same fills replayed with S20/S46's stress
    cost tier applied (maker 5bps/taker 8bps/slippage 5bps/limit-pen 5bps),
    for comparability with every backtest gate in this project.
    Returns one of: 'TOO_EARLY', 'KILL', 'CONTINUE', 'GO', 'FORCED_KILL'.
    """
    verdict, reason = check_circuit_breakers(trades)
    if verdict == 'KILL':
        return {'decision': 'KILL', 'reason': reason}

    n = len(trades)
    if n < CHECKPOINT_MIN_TRADES:
        return {'decision': 'TOO_EARLY', 'reason': f'only {n} trades, circuit breakers only'}

    checkpoint_trades = FINAL_CHECKPOINT_TRADES if extension_used else PRIMARY_CHECKPOINT_TRADES
    checkpoint_days = FINAL_CHECKPOINT_DAYS if extension_used else PRIMARY_CHECKPOINT_DAYS
    if n < checkpoint_trades and elapsed_days < checkpoint_days:
        return {'decision': 'TOO_EARLY', 'reason': f'{n} trades / {elapsed_days} days, '
                f'need {checkpoint_trades} trades OR {checkpoint_days} days (whichever later)'}
    # "whichever comes LATER" -- both conditions must be satisfied together,
    # i.e. wait for the slower of the two, not the faster.
    if n < checkpoint_trades or elapsed_days < checkpoint_days:
        return {'decision': 'TOO_EARLY', 'reason': f'{n} trades / {elapsed_days} days, '
                f'waiting for the later of {checkpoint_trades} trades / {checkpoint_days} days'}

    pf = _profit_factor(trades)
    pf_stress = _profit_factor(stress_replay_trades)
    boot = weekly_block_bootstrap_mean_r(trades)
    lower_ci = boot['ci_95'][0]

    go = (pf is not None and pf > GO_PF_MIN
          and pf_stress is not None and pf_stress >= GO_PF_STRESS_MIN
          and lower_ci > 0)
    clear_kill = (pf is None or pf <= 1.0 or boot['ci_95'][1] <= 0)

    result = {'n': n, 'elapsed_days': elapsed_days, 'PF': pf, 'PF_stress': pf_stress,
              'bootstrap': boot}
    if go:
        result['decision'] = 'GO'
    elif clear_kill:
        result['decision'] = 'FORCED_KILL' if extension_used else 'KILL'
    elif extension_used:
        # ambiguous even after the one allowed extension -> no more waiting
        result['decision'] = 'FORCED_KILL'
        result['reason'] = 'inconclusive after final checkpoint; no further extension permitted'
    else:
        result['decision'] = 'CONTINUE'
        result['reason'] = 'positive but inconclusive; one extension to the final checkpoint permitted'
    return result
