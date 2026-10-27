"""Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado), stdlib only."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def sharpe_moments(returns) -> dict:
    """Per-period Sharpe, sample size, skewness and (non-excess) kurtosis."""
    r = np.asarray(returns, dtype=float)
    t = len(r)
    sd = r.std(ddof=1) if t > 1 else 0.0
    if t < 3 or sd == 0:
        return {'sr': 0.0, 't': t, 'skew': 0.0, 'kurt': 3.0}
    z = (r - r.mean()) / r.std(ddof=0)
    return {'sr': float(r.mean() / sd), 't': t,
            'skew': float((z ** 3).mean()), 'kurt': float((z ** 4).mean())}


def probabilistic_sharpe(m: dict, benchmark_sr: float = 0.0) -> float | None:
    """P(true SR > benchmark) given sample SR, length and higher moments."""
    if m['t'] < 3:
        return None
    denom = 1 - m['skew'] * m['sr'] + (m['kurt'] - 1) / 4 * m['sr'] ** 2
    if denom <= 0:
        return None
    return _N.cdf((m['sr'] - benchmark_sr) * math.sqrt(m['t'] - 1) / math.sqrt(denom))


def expected_max_sharpe(trials: int, sr_variance: float) -> float:
    """Expected maximum Sharpe among ``trials`` independent zero-edge strategies."""
    if trials < 2:
        return 0.0
    return math.sqrt(sr_variance) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1 / (trials * math.e)))


def deflated_sharpe(returns, trials: int, sr_variance: float | None = None) -> dict:
    """PSR against the best Sharpe expected by luck after ``trials`` attempts.

    ``sr_variance`` is the cross-trial variance of Sharpe ratios; when unknown
    we use 1/(T-1), the null sampling variance of the estimator (disclosed).
    """
    m = sharpe_moments(returns)
    variance = sr_variance if sr_variance is not None else 1 / max(m['t'] - 1, 1)
    sr0 = expected_max_sharpe(trials, variance)
    return {
        **m,
        'sr_annualized': m['sr'] * math.sqrt(365),
        'psr_vs_zero': probabilistic_sharpe(m, 0.0),
        'trials': trials,
        'sr_threshold_from_trials': sr0,
        'dsr': probabilistic_sharpe(m, sr0),
    }
