"""Merge Book A + Book B daily PnL and optional portfolio fuse (research)."""
import pandas as pd


def _normalize_index(series: pd.Series) -> pd.Series:
    idx = []
    for t in series.index:
        ts = pd.Timestamp(t)
        if ts.tzinfo is not None:
            ts = ts.tz_convert('UTC').normalize()
        else:
            ts = ts.tz_localize('UTC').normalize()
        idx.append(ts)
    return pd.Series(series.values, index=pd.DatetimeIndex(idx)).sort_index()


def daily_pnl_from_equity(daily_equity: dict, initial: float = 250.0) -> pd.Series:
    if not daily_equity:
        return pd.Series(dtype=float)
    items = sorted(
        (pd.Timestamp(k).tz_localize('UTC') if pd.Timestamp(k).tzinfo is None else pd.Timestamp(k), float(v))
        for k, v in daily_equity.items()
    )
    series = pd.Series({d: v for d, v in items}).sort_index()
    prev = initial
    pnls = {}
    for day, equity in series.items():
        pnls[day] = equity - prev
        prev = equity
    return pd.Series(pnls).sort_index()


def merge_book_daily(a_pnl: pd.Series, b_pnl: pd.Series) -> pd.Series:
    a_pnl = _normalize_index(a_pnl)
    b_pnl = _normalize_index(b_pnl)
    frame = pd.DataFrame({'a': a_pnl, 'b': b_pnl}).fillna(0.0)
    frame['total'] = frame['a'] + frame['b']
    return frame['total']


def trailing_pause_fuse(
    daily_pnl: pd.Series,
    lookback_days: int = 10,
    pause_days: int = 5,
    loss_threshold: float = -8.0,
) -> pd.Series:
    """If rolling sum < threshold, pause (zero) next N days — research upper bound."""
    if daily_pnl.empty:
        return daily_pnl
    out = []
    pause = 0
    values = daily_pnl.tolist()
    index = daily_pnl.index.tolist()
    for i, pnl in enumerate(values):
        if pause > 0:
            out.append(0.0)
            pause -= 1
            continue
        out.append(pnl)
        if i >= lookback_days:
            window = sum(values[i - lookback_days:i])
            if window < loss_threshold:
                pause = pause_days
    return pd.Series(out, index=index)


def summarize_pnl(daily: pd.Series, start, end) -> dict:
    days = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days)
    total = float(daily.sum()) if not daily.empty else 0.0
    return {
        'net_pnl': total,
        'mean_calendar_day_pnl': total / days,
        'days': days,
    }
