"""Daily paper-forward of frozen BENCH_AB_R2 from 2026-10-27 (no orders).

Every run recomputes the whole forward window from the frozen warmup, scores
complete UTC days only, stores a per-day ledger and flags revisions of days
that were already scored. Status rules come from the frozen protocol in
docs/research/paper_forward_bench_ab_r2/protocol.json.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from django.conf import settings
import pandas as pd

from .bench_ab_r2_replay import available_bounds, book_b_signals, load_market, replay
from .run_bench_ab_r2 import COSTS, _daily_summary
from .sharpe_stats import deflated_sharpe

FORWARD_START = pd.Timestamp('2026-10-27', tz='UTC')
CAPITAL = 500.0
TARGET_USD_PER_DAY = 5.0
REFERENCE_USD_PER_DAY = 0.14
MIN_EXPECTATION_RATIO = 0.50
MIN_STATUS_DAYS = 30
MIN_PROMOTION_DAYS = 90
PRIOR_STUDIES = 133
PROTOCOL = Path(settings.BASE_DIR).parent / 'docs/research/paper_forward_bench_ab_r2/protocol.json'


def ledger_path() -> Path:
    root = Path(getattr(settings, 'PAPER_FORWARD_DIR', Path(settings.BASE_DIR).parent / 'data' / 'paper_forward'))
    return root / 'bench_ab_r2.json'


def _as_dict(series: pd.Series) -> dict:
    return {pd.Timestamp(k).strftime('%Y-%m-%d'): round(float(v), 6) for k, v in series.sort_index().items()}


def status_for(stress: dict, days: int, revisions: dict | None = None) -> str:
    if stress['max_drawdown_pct'] > 10.0:
        return 'BREACH_STOP'
    if revisions:
        return 'DATA_REVISED'
    if days < MIN_STATUS_DAYS:
        return 'INSUFFICIENT'
    rate = float(stress.get(
        'usd_per_calendar_day', stress['net_pnl'] / max(days, 1),
    ))
    if stress['net_pnl'] <= 0 or rate < REFERENCE_USD_PER_DAY * MIN_EXPECTATION_RATIO:
        return 'BELOW_EXPECTATION'
    if days < MIN_PROMOTION_DAYS:
        return 'OBSERVE'
    if float(stress.get('positive_month_share', 0.0)) < 0.5:
        return 'BELOW_EXPECTATION'
    return 'ON_TRACK'


def run_paper_forward(cache: str, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz='UTC')
    monthly_end, end = available_bounds(now, cache)
    if end <= FORWARD_START:
        return {'status': 'NOT_STARTED', 'forward_start': str(FORWARD_START.date()),
                'data_through': str((end - pd.Timedelta(days=1)).date())}
    path = ledger_path()
    previous = json.loads(path.read_text()) if path.exists() else {}
    data_through = str((end - pd.Timedelta(days=1)).date())
    if (previous.get('forward_start') == str(FORWARD_START.date())
            and previous.get('data_through') == data_through):
        # Publication probes are cheap; a two-year replay is not. Returning the
        # immutable ledger also makes hourly publication retries inexpensive.
        return {**previous, 'unchanged': True}
    minutes, funding, _ = load_market(cache, monthly_end, end)
    signals_b = book_b_signals(minutes)

    scenarios = {}
    for scenario in COSTS:
        run = replay(minutes, funding, signals_b, FORWARD_START, end, scenario)
        daily = run['daily'].copy()
        daily.index = pd.to_datetime(daily.index, utc=True)
        summary = _daily_summary(daily, CAPITAL)
        equity_before = CAPITAL + daily.sort_index().cumsum().shift(fill_value=0.0)
        summary.update({
            'gap_to_target_usd_per_day': TARGET_USD_PER_DAY - summary['usd_per_calendar_day'],
            'book_a_net_pnl': float(run['daily_a'].sum()),
            'book_b_net_pnl': float(run['daily_b'].sum()),
            'book_b_trades': run['trades_b'],
            'sharpe': deflated_sharpe(daily.sort_index() / equity_before, PRIOR_STUDIES),
            'days': {'total': _as_dict(run['daily']), 'book_a': _as_dict(run['daily_a']),
                     'book_b': _as_dict(run['daily_b'])},
        })
        scenarios[scenario] = summary

    stress = scenarios['stress']
    days = len(stress['days']['total'])
    old_days = (previous.get('scenarios', {}).get('stress', {}).get('days', {}).get('total', {}))
    revisions = {
        day: {'before': value, 'after': stress['days']['total'][day]}
        for day, value in old_days.items()
        if day in stress['days']['total'] and abs(stress['days']['total'][day] - value) > 1e-6
    }
    monitoring_status = status_for(stress, days, revisions)
    dsr = stress.get('sharpe', {}).get('dsr')
    report = {
        'protocol_sha256': sha256(PROTOCOL.read_bytes()).hexdigest() if PROTOCOL.exists() else None,
        'computed_at': str(now),
        'forward_start': str(FORWARD_START.date()),
        'data_through': data_through,
        'forward_days': days,
        'status': monitoring_status,
        'expected_stress_usd_per_day': REFERENCE_USD_PER_DAY,
        'revisions': revisions,
        'promotion_gate': {
            'allowed': False,
            'minimum_days': MIN_PROMOTION_DAYS,
            'statistical_support': dsr is not None and dsr >= 0.5,
            'book_b_risk_compliant': False,
            'reason': (
                'Book B exceeds the frozen portfolio risk limit; composite promotion is blocked.'
            ),
        },
        'scenarios': scenarios,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, indent=2, default=str))
    tmp.replace(path)
    return report


def format_report(report: dict) -> str:
    if report['status'] == 'NOT_STARTED':
        return (f"Paper-forward BENCH_AB_R2: start {report['forward_start']}, "
                f"dane dostępne do {report['data_through']} — brak pełnej doby.")
    s = report['scenarios']['stress']
    lines = [
        f"Paper-forward BENCH_AB_R2 ($500) — {report['forward_days']} dni "
        f"({report['forward_start']} → {report['data_through']}), status {report['status']}",
        f"stress: PnL ${s['net_pnl']:+.2f} (A ${s['book_a_net_pnl']:+.2f}, B ${s['book_b_net_pnl']:+.2f}, "
        f"{s['book_b_trades']} tr.), ${s['usd_per_calendar_day']:+.3f}/dzień "
        f"(oczekiwane ~${report['expected_stress_usd_per_day']:.2f}), do $5/dzień: "
        f"${s['gap_to_target_usd_per_day']:.2f}",
        f"zwrot {s['return_pct']:+.2f}%, max DD {s['max_drawdown_pct']:.2f}% (stop > 10%)",
    ]
    if report['revisions']:
        lines.append(f"⚠️ zmienione dni po ponownym przeliczeniu: {sorted(report['revisions'])}")
    return '\n'.join(lines)
