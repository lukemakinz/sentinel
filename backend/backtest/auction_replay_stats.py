"""Paired statistics for the M0 / M1 / M3 historical replay.

Every candidate episode has exactly one market outcome (the M0 plan).  A policy
that vetoes the candidate scores 0 R for it; one that keeps it scores the M0
outcome.  Unfilled plans (no trigger / pre-invalidation) score 0 R for all.
Uplift is therefore exactly paired and needs no assumption about independence
between policies; uncertainty comes from a day-block bootstrap because
candidates on the same day share market conditions.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

POLICIES = ('m0', 'm1', 'm3')
MANAGEMENT_POLICIES = {
    'p1': 'p1_structural',
    'p2': 'p2_hybrid',
}


def frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    if 'outcome' in df:
        df = df[~df.outcome.isin({'NO_DATA', 'INCOMPLETE_DATA'})].copy()
        if df.empty:
            return df
    df['bar_close'] = pd.to_datetime(df.bar_close, utc=True)
    df['day'] = df.bar_close.dt.floor('D')
    df['filled'] = df.state.eq('CLOSED') & df.net_r.notna()
    outcome = df.net_r.where(df.filled, 0.0).astype(float)
    df['r_m0'] = outcome
    df['r_m1'] = outcome.where(df.m1.eq('ARM'), 0.0)
    df['r_m3'] = outcome.where(df.m3.eq('ARM'), 0.0)
    management = df['management'] if 'management' in df else pd.Series(
        [{} for _ in range(len(df))], index=df.index,
    )
    for short, key in MANAGEMENT_POLICIES.items():
        values = management.apply(
            lambda payload: (payload or {}).get(key) or {},
        )
        df[f'{short}_complete'] = values.apply(bool) & values.apply(
            lambda value: bool(value.get('complete')),
        )
        df[f'{short}_tp1_hit'] = values.apply(
            lambda value: bool(value.get('tp1_hit')),
        )
        df[f'r_{short}'] = values.apply(
            lambda value: float(value.get('net_r') or 0.0)
            if value.get('complete') else 0.0,
        )
    return df


def _max_drawdown(series: pd.Series) -> float:
    equity = series.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


def policy_summary(df: pd.DataFrame, policy: str, days: float,
                   usd_per_r: float) -> dict:
    taken = df if policy == 'm0' else df[df[policy].eq('ARM')]
    filled = taken[taken.filled]
    r = filled.net_r.astype(float)
    wins, losses = r[r > 0].sum(), r[r <= 0].sum()
    ordered = df.sort_values('bar_close')[f'r_{policy}']
    total = float(df[f'r_{policy}'].sum())
    return {
        'candidates_kept': int(len(taken)),
        'filled_trades': int(len(filled)),
        'fill_rate': round(len(filled) / len(taken), 4) if len(taken) else None,
        'win_rate': round(float((r > 0).mean()), 4) if len(r) else None,
        'expectancy_per_trade_r': round(float(r.mean()), 4) if len(r) else None,
        'expectancy_per_candidate_r': round(total / len(df), 4) if len(df) else None,
        'total_r': round(total, 2),
        'profit_factor': round(float(wins / abs(losses)), 3) if losses < 0 else None,
        'max_drawdown_r': round(_max_drawdown(ordered), 2),
        'trades_per_day': round(len(filled) / days, 3) if days else None,
        'usd_per_day': round(total * usd_per_r / days, 3) if days else None,
        'avg_cost_r': (round(float((filled.gross_r - filled.net_r).mean()), 4)
                       if len(filled) else None),
    }


def day_block_bootstrap(df: pd.DataFrame, column: str, reps: int = 5000,
                        seed: int = 7) -> dict:
    """Mean per candidate with a 95% CI from resampling whole days."""
    if df.empty:
        return {'mean': None, 'ci95': [None, None], 'p_le_0': None}
    grouped = df.groupby('day')[column].agg(['sum', 'count'])
    sums, counts = grouped['sum'].to_numpy(), grouped['count'].to_numpy()
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(sums), size=(reps, len(sums)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    point = float(sums.sum() / counts.sum())
    return {
        'mean': round(point, 4),
        'ci95': [round(float(np.quantile(means, 0.025)), 4),
                 round(float(np.quantile(means, 0.975)), 4)],
        'p_le_0': round(float((means <= 0).mean()), 4),
    }


def management_policy_summary(df: pd.DataFrame, policy: str, days: float,
                              usd_per_r: float) -> dict:
    completed = df[df[f'{policy}_complete']]
    r = completed[f'r_{policy}'].astype(float)
    wins, losses = r[r > 0].sum(), r[r <= 0].sum()
    ordered = df.sort_values('bar_close')[f'r_{policy}']
    total = float(df[f'r_{policy}'].sum())
    return {
        'comparison_candidates': int(len(df)),
        'filled_trades': int(len(completed)),
        'win_rate': round(float((r > 0).mean()), 4) if len(r) else None,
        'tp1_hit_rate': round(float(completed[f'{policy}_tp1_hit'].mean()), 4)
        if len(completed) else None,
        'expectancy_per_trade_r': round(float(r.mean()), 4) if len(r) else None,
        'expectancy_per_candidate_r': round(total / len(df), 4) if len(df) else None,
        'total_r': round(total, 2),
        'profit_factor': round(float(wins / abs(losses)), 3) if losses < 0 else None,
        'max_drawdown_r': round(_max_drawdown(ordered), 2),
        'trades_per_day': round(len(completed) / days, 3) if days else None,
        'usd_per_day': round(total * usd_per_r / days, 3) if days else None,
    }


def summarize(records: list[dict], *, start, end, usd_per_r: float) -> dict:
    df = frame(records)
    days = (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 86400
    if df.empty:
        return {'candidates': 0}
    df['d_m1'] = df.r_m1 - df.r_m0
    df['d_m3'] = df.r_m3 - df.r_m0
    for policy in MANAGEMENT_POLICIES:
        df[f'd_{policy}'] = df[f'r_{policy}'] - df.r_m0
    out = {
        'candidates': int(len(df)),
        'days': round(days, 1),
        'usd_per_r': usd_per_r,
        'policies': {p: policy_summary(df, p, days, usd_per_r) for p in POLICIES},
        'expectancy_per_candidate_ci': {
            p: day_block_bootstrap(df, f'r_{p}') for p in POLICIES},
        'paired_uplift_vs_m0': {
            'm1': day_block_bootstrap(df, 'd_m1'),
            'm3': day_block_bootstrap(df, 'd_m3'),
        },
        'management_policies': {
            policy: management_policy_summary(df, policy, days, usd_per_r)
            for policy in MANAGEMENT_POLICIES
        },
        'management_uplift_vs_p0': {
            policy: day_block_bootstrap(df, f'd_{policy}')
            for policy in MANAGEMENT_POLICIES
        },
        'vetoed_candidate_mean_r': {
            p: (round(float(df.loc[~df[p].eq('ARM'), 'r_m0'].mean()), 4)
                if (~df[p].eq('ARM')).any() else None)
            for p in ('m1', 'm3')},
        'exit_reasons': df.exit_reason.replace('', 'NONE').value_counts().to_dict(),
        'by_year': {},
        'by_symbol': {},
        'by_regime': {},
        'by_global_state_m0': {},
    }
    for year, part in df.groupby(df.bar_close.dt.year):
        out['by_year'][str(year)] = {
            p: round(float(part[f'r_{p}'].sum()), 2) for p in POLICIES} | {
            'candidates': int(len(part))}
    for name, part in df.groupby('symbol'):
        out['by_symbol'][name] = {
            p: round(float(part[f'r_{p}'].sum()), 2) for p in POLICIES} | {
            'candidates': int(len(part)), 'filled': int(part.filled.sum())}
    for name, part in df.groupby('regime'):
        out['by_regime'][name] = {'candidates': int(len(part)),
                                  'm0_total_r': round(float(part.r_m0.sum()), 2)}
    for name, part in df.groupby(df.global_state.fillna('UNKNOWN')):
        out['by_global_state_m0'][name] = {
            'candidates': int(len(part)), 'filled': int(part.filled.sum()),
            'm0_mean_r_per_candidate': round(float(part.r_m0.mean()), 4)}
    # Three frozen policies on one sample: report the multiplicity explicitly.
    out['multiple_testing_note'] = (
        'Three entry/filter policies and two preregistered management policies '
        'were evaluated retrospectively on one sample. Treat a CI that excludes '
        '0 at 95% as suggestive only; Bonferroni for 4 uplift tests would '
        'require ~98.75%, followed by a true forward holdout.')
    return out


def verdict(summary: dict) -> list[str]:
    lines = []
    for p, label in (('m1', 'M1 trend filter'), ('m3', 'M3 global context')):
        u = summary['paired_uplift_vs_m0'][p]
        if u['mean'] is None:
            continue
        lo, hi = u['ci95']
        if lo > 0:
            lines.append(f'{label}: improves M0 per candidate (CI {lo:+.3f}..{hi:+.3f} R).')
        elif hi < 0:
            lines.append(f'{label}: hurts M0 per candidate (CI {lo:+.3f}..{hi:+.3f} R).')
        else:
            lines.append(f'{label}: no detectable effect (CI {lo:+.3f}..{hi:+.3f} R).')
    base = summary['expectancy_per_candidate_ci']['m0']
    if base['mean'] is not None:
        lo, hi = base['ci95']
        state = ('positive' if lo > 0 else 'negative' if hi < 0 else
                 'not distinguishable from zero')
        lines.append(f'M0 baseline edge is {state} (CI {lo:+.3f}..{hi:+.3f} R per candidate).')
    for policy, label in (('p1', 'P1 scale + protected stop'),
                          ('p2', 'P2 scale + runner trail')):
        uplift = (summary.get('management_uplift_vs_p0') or {}).get(policy) or {}
        lo, hi = uplift.get('ci95', [None, None])
        if lo is None:
            continue
        state = 'improves P0' if lo > 0 else 'hurts P0' if hi < 0 else 'has no detectable effect'
        lines.append(f'{label}: {state} (CI {lo:+.3f}..{hi:+.3f} R per candidate).')
    return lines


def _fmt(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return '—'
    return f'{value}'
