"""Weekly-rebalance portfolio simulator for Book A (S73+BTC)."""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import (
    BookARiskOverlayConfig,
    compute_risk_indicators,
    exposure_multiplier,
)
from l1_filter.book_a_small_tsmom import (
    BookASmallTsmomConfig,
    build_daily_panel,
    target_weights_for_day,
)


@dataclass
class BookASimResult:
    summary: dict
    equity_curve: pd.Series
    daily_pnl: pd.Series
    risk_log: pd.DataFrame | None = None


def _rebalance_days(index: pd.DatetimeIndex, weekday: int) -> list[pd.Timestamp]:
    days = []
    for ts in index:
        if ts.weekday() == weekday:
            days.append(ts)
    return days


def _scale_weights(weights: dict[str, float], mult: float) -> dict[str, float]:
    if mult <= 0 or not weights:
        return {}
    return {s: w * mult for s, w in weights.items()}


def simulate_book_a(
    minutes_by_symbol: dict[str, pd.DataFrame],
    config: BookASmallTsmomConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial_capital: float = 250.0,
    risk: BookARiskOverlayConfig | None = None,
) -> BookASimResult:
    full_panel = build_daily_panel(minutes_by_symbol, config)
    panel = full_panel.loc[(full_panel.index >= start) & (full_panel.index < end)]
    if panel.empty:
        raise ValueError('Empty panel for simulation window')

    # Quantity/cash ledger.  Target weights are only instructions at the
    # weekly rebalance; between rebalances the holdings must drift with price.
    # Keeping the last target weights here would silently simulate a free
    # daily rebalance back to target.
    cash = float(initial_capital)
    quantities: dict[str, float] = {}
    equity = float(initial_capital)
    peak_equity = initial_capital
    fees_paid = 0.0
    rebalance_count = 0
    equity_points = {}
    daily_pnl = {}
    risk_rows = []

    rebalance_candidates = _rebalance_days(panel.index, config.rebalance_weekday)
    if config.rebalance_every_n_weeks > 1:
        rebalance_set = set()
        for i, day in enumerate(rebalance_candidates):
            if i % config.rebalance_every_n_weeks == 0:
                rebalance_set.add(day)
    else:
        rebalance_set = set(rebalance_candidates)
    prev_equity = equity

    for i, day in enumerate(panel.index):
        closes = panel.loc[day]
        equity = cash
        for symbol, quantity in quantities.items():
            price = float(closes[symbol])
            if not np.isfinite(price) or price <= 0:
                raise ValueError(f'Invalid close for held {symbol} on {day}')
            equity += quantity * price
        peak_equity = max(peak_equity, equity)

        if day in rebalance_set:
            target = target_weights_for_day(full_panel, day, config)
            if risk is not None:
                ind = compute_risk_indicators(
                    full_panel, day, config, equity=equity, peak_equity=peak_equity,
                )
                mult = exposure_multiplier(ind, risk)
                target = _scale_weights(target, mult)
                risk_rows.append({**ind, 'exposure_mult': mult, 'equity': equity})

            filtered = {}
            for symbol, w in target.items():
                notional = w * equity
                if notional >= config.min_position_usd:
                    filtered[symbol] = w
            # Preserve the absolute gross exposure produced by volatility
            # targeting and the risk overlay.  Re-normalising the surviving
            # positions to 100% here silently cancels both mechanisms and also
            # concentrates capital after the minimum-notional filter removes a
            # small position.  Unallocated weight intentionally remains cash.
            target = filtered

            turnover_usd = 0.0
            target_quantities = {}
            # Stable ordering makes floating-point cash aggregation exactly
            # reproducible across processes with different hash seeds.
            symbols = sorted(set(quantities) | set(target))
            for symbol in symbols:
                price = float(closes[symbol])
                if not np.isfinite(price) or price <= 0:
                    raise ValueError(f'Invalid rebalance close for {symbol} on {day}')
                current_notional = quantities.get(symbol, 0.0) * price
                target_notional = target.get(symbol, 0.0) * equity
                turnover_usd += abs(target_notional - current_notional)
                if target_notional > 0:
                    target_quantities[symbol] = target_notional / price
                cash += current_notional - target_notional
            fee = turnover_usd * (config.taker_fee_bps / 10000.0)
            fees_paid += fee
            cash -= fee
            quantities = target_quantities
            equity = cash + sum(
                quantity * float(closes[symbol])
                for symbol, quantity in quantities.items()
            )
            rebalance_count += 1

        equity_points[day] = equity
        daily_pnl[day] = equity - prev_equity
        prev_equity = equity

    curve = pd.Series(equity_points).sort_index()
    pnl_series = pd.Series(daily_pnl).sort_index()
    net = float(equity - initial_capital)
    days = max(1, (end - start).days)
    peak = curve.cummax()
    dd = ((curve - peak) / peak).min()

    summary = {
        'name': config.name if risk is None else f'{config.name}+{risk.name}',
        'initial_capital': initial_capital,
        'final_equity': float(equity),
        'net_pnl': net,
        'fees_paid': float(fees_paid),
        'rebalances': rebalance_count,
        'calendar_days': days,
        'mean_calendar_day_pnl': net / days,
        'max_drawdown_fraction': float(dd) if np.isfinite(dd) else 0.0,
        'config': asdict(config),
        'risk_overlay': asdict(risk) if risk else None,
    }
    risk_log = pd.DataFrame(risk_rows) if risk_rows else None
    return BookASimResult(
        summary=summary,
        equity_curve=curve,
        daily_pnl=pnl_series,
        risk_log=risk_log,
    )
