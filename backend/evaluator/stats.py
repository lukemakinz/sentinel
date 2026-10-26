"""Attribution statistics — win rate per strategy, session, regime, agent."""
from django.db.models import Avg, Count, Q


def get_stats(filters: dict = None) -> dict:
    """
    Returns attribution stats with breakdown per:
    strategy, session, regime, direction, symbol, agent confidence calibration.
    """
    from .models import Signal

    qs = Signal.objects.filter(state='CLOSED').exclude(outcome='EXPIRED')
    if filters:
        qs = qs.filter(**filters)

    total = qs.count()
    if total == 0:
        return {'total': 0, 'message': 'No closed signals yet'}

    wins = qs.filter(outcome__in=('WIN', 'PARTIAL_WIN')).count()

    def breakdown(field):
        return list(
            qs.values(field)
            .annotate(
                count=Count('id'),
                wins=Count('id', filter=Q(outcome__in=('WIN', 'PARTIAL_WIN'))),
                avg_pnl_r=Avg('pnl_r'),
                avg_mfe=Avg('mfe_r'),
                avg_mae=Avg('mae_r'),
            )
            .order_by('-count')
        )

    # Agent calibration: confidence buckets vs actual win rate
    agent_calibration = {}
    for agent in ('context_trader', 'order_flow_quant', 'risk_manager', 'devils_advocate'):
        buckets = []
        for lo, hi in [(50, 60), (60, 70), (70, 80), (80, 100)]:
            bucket_qs = qs.filter(
                **{f'agent_verdicts__{agent}__confidence__gte': lo,
                   f'agent_verdicts__{agent}__confidence__lt': hi}
            )
            c = bucket_qs.count()
            if c > 0:
                w = bucket_qs.filter(outcome__in=('WIN', 'PARTIAL_WIN')).count()
                buckets.append({
                    'confidence_range': f'{lo}-{hi}',
                    'count': c,
                    'actual_win_rate': round(w / c * 100, 1),
                    'expected_win_rate': (lo + hi) / 2,
                })
        if buckets:
            agent_calibration[agent] = buckets

    return {
        'total':           total,
        'win_rate':        round(wins / total * 100, 1),
        'avg_pnl_r':       round(float(qs.aggregate(avg=Avg('pnl_r'))['avg'] or 0), 3),
        'avg_mfe_r':       round(float(qs.aggregate(avg=Avg('mfe_r'))['avg'] or 0), 3),
        'avg_mae_r':       round(float(qs.aggregate(avg=Avg('mae_r'))['avg'] or 0), 3),
        'per_strategy':    breakdown('strategy'),
        'per_direction':   breakdown('direction'),
        'per_regime':      breakdown('regime'),
        'per_symbol':      breakdown('symbol'),
        'shadow_stats': {
            'shadow_total': Signal.objects.filter(shadow=True,  state='CLOSED').count(),
            'real_total':   Signal.objects.filter(shadow=False, state='CLOSED').count(),
            'shadow_wr':    _win_rate(Signal.objects.filter(shadow=True,  state='CLOSED')),
            'real_wr':      _win_rate(Signal.objects.filter(shadow=False, state='CLOSED')),
        },
        'agent_calibration': agent_calibration,
        'agent_brier_scores': _brier_scores(qs),
        'ai_selector': _ai_selector_stats(qs),
        'reentry_stats': _reentry_stats(),
    }


def _ai_selector_stats(qs) -> dict:
    """Compare S12AI APPROVE with the identically-labeled REJECT cohort."""
    ai = qs.filter(strategy='S12AI')

    def cohort(rows):
        pnls = [float(value) for value in rows.values_list('pnl_r', flat=True)
                if value is not None]
        gains = sum(value for value in pnls if value > 0)
        losses = -sum(value for value in pnls if value < 0)
        wins = sum(value > 0 for value in pnls)
        return {
            'resolved': len(pnls),
            'win_rate_pct': round(100 * wins / len(pnls), 1) if pnls else 0.0,
            'avg_pnl_r': round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
            'raw_profit_factor': round(gains / losses, 4) if losses else None,
        }

    approved = cohort(ai.filter(l2_action='APPROVE'))
    rejected = cohort(ai.filter(l2_action='REJECT'))
    total = approved['resolved'] + rejected['resolved']
    return {
        'label': 'standardized counterfactual +1R/-1R before trading costs',
        'total_resolved': total,
        'minimum_required': 100,
        'sample_ready': total >= 100,
        'approved': approved,
        'rejected': rejected,
        'selection_lift_avg_r': round(
            approved['avg_pnl_r'] - rejected['avg_pnl_r'], 4),
    }


def _brier_scores(qs) -> dict:
    """
    Brier score per agent: mean((forecast - outcome)²).
    0.0 = perfect | 0.25 = random | > 0.25 = worse than random.
    Lower is better. Measures calibration of agent confidence.
    """
    scores = {}
    for agent in ('context_trader', 'order_flow_quant', 'risk_manager', 'devils_advocate'):
        pairs = []
        for sig in qs.iterator():
            verdict = (sig.agent_verdicts or {}).get(agent, {})
            confidence = verdict.get('confidence')
            if confidence is None:
                continue
            # forecast = confidence/100 (probability of win)
            # outcome = 1 if WIN, 0 if LOSS/BREAKEVEN
            forecast = confidence / 100.0
            actual   = 1.0 if sig.outcome in ('WIN', 'PARTIAL_WIN') else 0.0
            pairs.append((forecast - actual) ** 2)

        if pairs:
            brier = round(sum(pairs) / len(pairs), 4)
            scores[agent] = {
                'brier_score': brier,
                'n': len(pairs),
                'calibration': 'good' if brier < 0.15 else 'moderate' if brier < 0.25 else 'poor',
            }
    return scores


def _reentry_stats() -> dict:
    """Compare original trades vs re-entries win rates."""
    from .models import Signal
    originals  = Signal.objects.filter(state='CLOSED', is_reentry_of__isnull=True)
    reentries  = Signal.objects.filter(state='CLOSED', is_reentry_of__isnull=False)
    return {
        'original_wr':  _win_rate(originals),
        'reentry_wr':   _win_rate(reentries),
        'original_n':   originals.count(),
        'reentry_n':    reentries.count(),
    }


def _win_rate(qs) -> float:
    total = qs.count()
    if total == 0:
        return 0.0
    wins = qs.filter(outcome__in=('WIN', 'PARTIAL_WIN')).count()
    return round(wins / total * 100, 1)
