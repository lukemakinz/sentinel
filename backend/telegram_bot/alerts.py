"""Human-readable Telegram alerts (Polish) for journal events and the feed."""
from .client import send_message

OUTCOME_TEXT = {
    'TP1_HIT': '✅ TP1 osiągnięty',
    'STOPPED': '❌ SL',
    'TIME': '⏱ wyjście czasowe (72h)',
    'EXPIRED': '⌛ limit wygasł bez wypełnienia',
    'NO_MSS': '— brak MSS',
}


def format_observation(obs) -> str:
    row = obs.payload
    head = f"{obs.symbol} {obs.side} — {obs.first_status} ({row.get('score')}/7)"
    lines = [head, row.get('next', '')]
    if obs.absorption:
        lines.append(f'absorpcja: {obs.absorption}')
    lines.append('Narzędzie obserwacyjne, nie sygnał wejścia.')
    return '\n'.join(line for line in lines if line)


def format_outcome(obs) -> str:
    r = '' if obs.net_r is None else f' ({obs.net_r:+.2f}R po kosztach)'
    strict = 'RR≥1:3' if obs.strict_rr_ok else 'RR<1:3, poza ścisłymi zasadami'
    return (f"{OUTCOME_TEXT.get(obs.outcome, obs.outcome)} — {obs.symbol} {obs.side}{r}\n"
            f"setup z {obs.event_time:%Y-%m-%d %H:%M} UTC, {strict}")


def alert_new(observations, statuses: set[str]) -> int:
    """Send alerts for newly journaled rows whose first status is wanted."""
    sent = 0
    for obs in observations:
        if obs.first_status in statuses and not obs.alerted:
            if send_message(format_observation(obs)):
                sent += 1
            obs.alerted = True
            obs.save(update_fields=['alerted'])
    return sent


def alert_outcomes(observations) -> int:
    """Outcomes of setups that were alerted (others only go to /raport)."""
    return sum(send_message(format_outcome(obs)) for obs in observations
               if obs.alerted and obs.outcome != 'EXPIRED')
