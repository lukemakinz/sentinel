"""Print this week's Book A rebalance hint + Book B regime flags (paper ops)."""
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT, compute_risk_indicators, exposure_multiplier
from backtest.extend_scalp_cache import data_end_exclusive, load_range_resilient
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM, build_daily_panel, target_weights_for_day
from l1_filter.book_b_quiet_breakout import BOOK_B_QUIET_V2, BookBQuietBreakoutConfig
from l1_filter.book_b_quiet_router import BookBQuietRouterConfig
from l1_filter.book_b_shared_risk import daily_indicator_table
from .scalp_data import load_archives


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
CACHE = '/tmp/sentinel-scalp-cache'


def _quiet_ok(row, cfg: BookBQuietBreakoutConfig) -> bool:
    if row.get('btc_above_sma200', 0) < 1:
        return False
    if float(row.get('btc_vol_percentile', 1)) > cfg.max_btc_vol_percentile:
        return False
    if float(row.get('breadth_sma50', 0)) < cfg.min_breadth_sma50:
        return False
    return True


def main() -> None:
    end = data_end_exclusive()
    minutes = {}
    for s in SYMBOLS:
        try:
            minutes[s], _, _ = load_range_resilient(
                s, pd.Timestamp('2024-08-01', tz='UTC'), end, CACHE)
        except Exception:
            minutes[s] = load_archives(s, '2024-08-01', str(end.date()), CACHE, repair_from_daily=True)[0]
    panel = build_daily_panel(minutes, BOOK_A_ALT_RM)
    day = panel.index[-1]
    ind = compute_risk_indicators(panel, day, BOOK_A_ALT_RM)
    mult = exposure_multiplier(ind, BOOK_A_RISK_DEFAULT)
    weights = target_weights_for_day(panel, day, BOOK_A_ALT_RM)
    scaled = {s: w * mult for s, w in weights.items()} if mult > 0 else {}
    table = daily_indicator_table(minutes, BOOK_A_ALT_RM)
    row = table.loc[day] if day in table.index else None

    print('=== Book A+B paper snapshot (UTC) ===')
    print(f'As of daily close: {day}')
    print(f'Book A exposure_mult: {mult:.2f}')
    print(f'Book A target weights (scaled): {scaled or "CASH"}')
    if row is not None:
        breadth = float(row.get('breadth_sma50', 0))
        router = BookBQuietRouterConfig()
        active = router.v2 if breadth >= router.breadth_v2_threshold else router.v1
        ok = _quiet_ok(row, active)
        print(f'Book B router → **{active.name}** (breadth={breadth:.2f})')
        print(f'Book B regime OK: {ok} (vol_pct={row.get("btc_vol_percentile", 0):.2f})')
    print('Not live orders — run weekly rebalance for A; B uses 1h Donchian when regime OK.')


if __name__ == '__main__':
    main()
