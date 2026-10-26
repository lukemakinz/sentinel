"""Prospective, conservative outcome labels for shadow-only AI candidates."""
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class ShadowOutcome:
    outcome: str
    exit_reason: str
    filled_at: datetime | None
    closed_at: datetime
    exit_price: float | None
    pnl_r: float | None
    mfe_r: float | None
    mae_r: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def replay_one_r_barrier(direction: str, entry: float, stop: float,
                         created_at: datetime, expires_at: datetime,
                         candles: list[dict]) -> ShadowOutcome | None:
    """Resolve a limit candidate at +1R/-1R, stop-first on ambiguous bars.

    Returns ``None`` when candle coverage is not complete through expiry.  The
    standardized barrier measures the AI selector independently from the more
    complex partial-exit policy used by an execution strategy.
    """
    if direction not in {'LONG', 'SHORT'} or entry <= 0:
        raise ValueError('Invalid direction or entry')
    r_value = abs(entry - stop)
    if r_value <= 0:
        raise ValueError('Stop must differ from entry')
    rows = sorted(
        (row for row in candles if created_at <= row['timestamp'] < expires_at),
        key=lambda row: row['timestamp'],
    )
    if not rows:
        return None
    # Never label a signal using a truncated future window.
    if rows[-1]['timestamp'] < expires_at.replace(second=0, microsecond=0) - _one_minute():
        return None

    target = entry + r_value if direction == 'LONG' else entry - r_value
    filled_at = None
    mfe_r = mae_r = 0.0
    for row in rows:
        high, low = float(row['high']), float(row['low'])
        if filled_at is None:
            fill_touched = low <= entry if direction == 'LONG' else high >= entry
            if not fill_touched:
                continue
            filled_at = row['timestamp']

        if direction == 'LONG':
            favorable = (high - entry) / r_value
            adverse = (low - entry) / r_value
            stop_touched = low <= stop
            target_touched = high >= target
        else:
            favorable = (entry - low) / r_value
            adverse = (entry - high) / r_value
            stop_touched = high >= stop
            target_touched = low <= target
        mfe_r, mae_r = max(mfe_r, favorable), min(mae_r, adverse)

        # OHLC cannot reveal intrabar ordering.  Counting a simultaneous stop
        # and target as a win would be optimistic, so the stop always wins.
        if stop_touched:
            return ShadowOutcome(
                'LOSS', 'SL', filled_at, row['timestamp'], stop,
                -1.0, mfe_r, mae_r,
            )
        if target_touched:
            return ShadowOutcome(
                'WIN', 'TP1', filled_at, row['timestamp'], target,
                1.0, mfe_r, mae_r,
            )

    if filled_at is None:
        return ShadowOutcome(
            'EXPIRED', 'EXPIRED', None, expires_at, None,
            None, None, None,
        )

    exit_price = float(rows[-1]['close'])
    pnl_r = (
        (exit_price - entry) / r_value
        if direction == 'LONG' else (entry - exit_price) / r_value
    )
    outcome = 'WIN' if pnl_r > 0.1 else 'LOSS' if pnl_r < -0.1 else 'BREAKEVEN'
    return ShadowOutcome(
        outcome, 'TIME_KILL', filled_at, rows[-1]['timestamp'], exit_price,
        pnl_r, mfe_r, mae_r,
    )


def _one_minute():
    from datetime import timedelta
    return timedelta(minutes=1)
