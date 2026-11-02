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
    funding: dict[str, pd.Series] | None = None,
    funding_multiplier: float = 1.0,
    quantity_steps: dict[str, float] | None = None,
    panel: pd.DataFrame | None = None,
    config_for_day=None,
) -> BookASimResult:
    """``funding``/``quantity_steps`` default off so frozen results are unchanged.

    ``funding`` maps symbol to settled perpetual funding rates; longs pay
    positive rates on their notional at each settlement inside the day.
    ``quantity_steps`` rounds rebalance quantities to exchange contract sizes.
    """
    # ``panel`` (daily closes, end-of-day index) and ``config_for_day`` (a
    # point-in-time universe per rebalance day) are research hooks; both
    # default to the frozen behaviour.
    full_panel = panel if panel is not None else build_daily_panel(minutes_by_symbol, config)
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
    funding_paid = 0.0
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

    previous_day = None
    for i, day in enumerate(panel.index):
        closes = panel.loc[day]
        if funding and quantities:
            window_start = previous_day if previous_day is not None else day - pd.Timedelta(days=1)
            for symbol, quantity in sorted(quantities.items()):
                rates = funding.get(symbol)
                if rates is None or rates.empty:
                    continue
                settled = rates.loc[(rates.index > window_start) & (rates.index <= day)]
                if len(settled):
                    payment = quantity * float(closes[symbol]) * float(settled.sum()) * funding_multiplier
                    cash -= payment
                    funding_paid += payment
        previous_day = day
        equity = cash
        for symbol, quantity in quantities.items():
            price = float(closes[symbol])
            if not np.isfinite(price) or price <= 0:
                raise ValueError(f'Invalid close for held {symbol} on {day}')
            equity += quantity * price
        peak_equity = max(peak_equity, equity)

        if day in rebalance_set:
            day_config = config_for_day(day) if config_for_day is not None else config
            target = target_weights_for_day(full_panel, day, day_config)
            if risk is not None:
                ind = compute_risk_indicators(
                    full_panel, day, day_config, equity=equity, peak_equity=peak_equity,
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
                quantity = target_notional / price if target_notional > 0 else 0.0
                step = (quantity_steps or {}).get(symbol)
                if step:
                    quantity = round(quantity / step) * step
                    target_notional = quantity * price
                    turnover_usd += abs(target_notional - current_notional) - abs(
                        target.get(symbol, 0.0) * equity - current_notional)
                if quantity > 0:
                    target_quantities[symbol] = quantity
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
        'funding_paid': float(funding_paid),
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
