"""Telegram command handlers. Read-only except pause/resume; no live trading."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

HELP = (
    'Sentinel — komendy:\n'
    '/status — feed, pauza, budżet AI, otwarte setupy\n'
    '/scan [SYMBOL] — setup search teraz (ok. 20 s)\n'
    '/raport — wyniki dziennika setupów i shadow (AI vs baseline)\n'
    '/koszt — wydatki AI dziś i w 7 dni\n'
    '/paper — paper-forward Book A+B od 2026-10-27\n'
    '/pauza — wstrzymaj analizy, AI i dziennik\n'
    '/wznow — wznów\n'
    'Handel na żywo nie da się włączyć z telefonu.'
)


def _age(seconds):
    if seconds is None:
        return 'brak danych'
    return f'{seconds:.0f}s' if seconds < 120 else f'{seconds / 60:.0f} min'


def cmd_status(_args) -> str:
    from l1_filter.models import SetupObservation
    from l2_agents.auction_service import ai_budget_status
    from risk.models import system_paused

    from .watchdog import feed_ages, stale_streams

    ages = feed_ages()
    stale = stale_streams(ages)
    budget = ai_budget_status()
    open_setups = SetupObservation.objects.filter(
        kind='SETUP', outcome__in=['OPEN', 'FILLED']).count()
    feed = ', '.join(f'{k} {_age(v)}' for k, v in ages.items())
    return '\n'.join([
        f"{'⏸ PAUZA' if system_paused() else '▶️ działa'} | feed {'🚨 ' + ','.join(stale) if stale else 'OK'}",
        f'wiek danych: {feed}',
        f"AI dziś: ${budget['spent_today_usd']:.4f} / ${budget['daily_budget_usd']:.2f}",
        f'otwarte setupy w dzienniku: {open_setups}',
    ])


def cmd_scan(args) -> str:
    from l1_filter.setup_search import run_setup_search

    report = run_setup_search(symbols=[a.upper() for a in args] or None)
    rows = [r for r in report['rows'] if r['status'] != 'NO_SETUP'][:10]
    if not rows:
        return f"Brak setupów w toku ({report['universe']} rynków)."
    lines = [f"Setup search — {report['universe']} rynków (top {len(rows)}):"]
    for row in rows:
        lines.append(f"\n{row['symbol']} {row['side']} {row['status']} {row['score']}/7\n→ {row['next']}")
    lines.append('\n' + report['warning'])
    return '\n'.join(lines)


def cmd_report(_args) -> str:
    from l1_filter.setup_journal import journal_summary
    from l2_agents.management.commands.auction_shadow_report import build_report

    journal = journal_summary()
    shadow = build_report()['paired_comparison']

    def line(name, s):
        if not s.get('filled_closed', s.get('closed')):
            return f'{name}: brak zamkniętych'
        closed = s.get('filled_closed', s.get('closed'))
        return (f"{name}: {closed} zamkn., WR {s['win_rate']}, "
                f"śr. {s.get('mean_net_r', s.get('expectancy_net_r'))}R, PF {s['profit_factor']}")

    episodes = journal['episodes']
    return '\n'.join([
        'Dziennik setup search (TP1, koszty stress):',
        line('• ścisłe RR≥1:3', journal['strict_rr_1_3']),
        line('• wszystkie', journal['all_setups_to_tp1']),
        f"• sweepy: {episodes['total']}, z MSS {episodes['reached_mss']}, bez MSS {episodes['no_mss']}",
        'Shadow:',
        line('• AI', shadow['ai']),
        line('• baseline', shadow['mechanical_baseline']),
        'Min. ~100 zamkniętych, zanim wyciągniemy wnioski.',
    ])


def cmd_paper(_args) -> str:
    import json

    from backtest.paper_forward_ab import format_report, ledger_path

    path = ledger_path()
    if not path.exists():
        return 'Paper-forward jeszcze nie przeliczony (raz na dobę ok. 03:00 UTC).'
    return format_report(json.loads(path.read_text()))


def cmd_cost(_args) -> str:
    from l2_agents.auction_service import ai_budget_status

    b = ai_budget_status()
    return (f"AI dziś: ${b['spent_today_usd']:.4f} (limit ${b['daily_budget_usd']:.2f}, "
            f"zostało ${b['remaining_today_usd']:.4f})\nAI 7 dni: ${b['spent_last_7_days_usd']:.4f}")


def cmd_pause(_args, by='telegram') -> str:
    from risk.models import ControlFlag

    ControlFlag.set('paused', True, by=by)
    return '⏸ Wstrzymano: shadow, AI i dziennik. Feed dalej zbiera dane. /wznow aby wznowić.'


def cmd_resume(_args, by='telegram') -> str:
    from risk.models import ControlFlag

    ControlFlag.set('paused', False, by=by)
    return '▶️ Wznowiono.'


COMMANDS = {
    '/start': lambda _a: HELP, '/help': lambda _a: HELP,
    '/status': cmd_status, '/scan': cmd_scan, '/raport': cmd_report,
    '/koszt': cmd_cost, '/paper': cmd_paper, '/pauza': cmd_pause, '/wznow': cmd_resume,
}


def handle(text: str) -> str:
    parts = (text or '').strip().split()
    if not parts:
        return HELP
    command = parts[0].split('@')[0].lower()
    handler = COMMANDS.get(command)
    if handler is None:
        return HELP
    try:
        return handler(parts[1:])
    except Exception as exc:  # report, never crash the bot loop
        return f'Błąd: {type(exc).__name__}: {exc}'


def daily_summary() -> str:
    from l1_filter.setup_journal import journal_summary

    since = timezone.now() - timedelta(days=1)
    day = journal_summary(since=since)['all_setups_to_tp1']
    return '\n'.join(['☀️ Podsumowanie dnia', cmd_status([]),
                      f"setupy 24h: {day['setups']}, zamknięte {day['filled_closed']}, "
                      f"suma {day['total_net_r']}R", cmd_cost([]), cmd_paper([])])
