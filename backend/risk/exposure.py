"""Portfolio exposure engine: alts are one bet on BTC until proven otherwise.

Measures signed BTC-beta exposure, gross notional and total risk to stops,
and checks a proposed trade against portfolio limits before entry. Betas are
estimated from 1h returns versus BTC; the static table is only a fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from django.conf import settings

from .portfolio_heat import BTC_BETAS, DEFAULT_BETA

MIN_BARS_FOR_BETA = 200


@dataclass(frozen=True)
class ExposureLimits:
    max_open_risk_pct: float = 0.5     # sum of distance-to-stop risk, % of equity
    max_net_beta_x: float = 1.5        # |signed BTC-beta notional| / equity
    max_gross_x: float = 3.0           # gross notional / equity

    @classmethod
    def from_settings(cls) -> 'ExposureLimits':
        return cls(
            max_open_risk_pct=float(getattr(settings, 'PORTFOLIO_MAX_OPEN_RISK_PCT', 0.5)),
            max_net_beta_x=float(getattr(settings, 'PORTFOLIO_MAX_NET_BETA_X', 1.5)),
            max_gross_x=float(getattr(settings, 'PORTFOLIO_MAX_GROSS_X', 3.0)),
        )


@dataclass
class Exposure:
    equity: float
    gross_x: float = 0.0
    net_beta_x: float = 0.0
    open_risk_pct: float = 0.0
    by_symbol: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {'equity': self.equity, 'gross_x': round(self.gross_x, 4),
                'net_beta_x': round(self.net_beta_x, 4),
                'open_risk_pct': round(self.open_risk_pct, 4), 'by_symbol': self.by_symbol}


def beta_from_returns(asset: np.ndarray, btc: np.ndarray) -> float | None:
    if len(asset) < MIN_BARS_FOR_BETA or len(asset) != len(btc):
        return None
    variance = float(np.var(btc, ddof=1))
    if variance <= 0:
        return None
    return float(np.cov(asset, btc, ddof=1)[0, 1] / variance)


def estimate_betas(symbols, days: int = 30) -> dict[str, dict]:
    """BTC beta per symbol from stored 1h candles; falls back to the static table."""
    from datetime import timedelta

    import pandas as pd
    from django.utils import timezone

    from ingester.models import Candle

    since = timezone.now() - timedelta(days=days)

    def closes(symbol):
        rows = Candle.objects.filter(symbol=symbol, interval='1h', timestamp__gte=since) \
            .order_by('timestamp').values_list('timestamp', 'close')
        return pd.Series({ts: float(c) for ts, c in rows}, dtype=float)

    btc = closes('BTCUSDT')
    out = {}
    for symbol in set(symbols):
        if symbol == 'BTCUSDT':
            out[symbol] = {'beta': 1.0, 'source': 'definition'}
            continue
        joined = pd.concat([closes(symbol), btc], axis=1, join='inner').dropna()
        returns = np.log(joined).diff().dropna().to_numpy()
        beta = beta_from_returns(returns[:, 0], returns[:, 1]) if len(returns) else None
        out[symbol] = ({'beta': beta, 'source': f'{len(returns)}x1h'} if beta is not None
                       else {'beta': BTC_BETAS.get(symbol, DEFAULT_BETA), 'source': 'static_fallback'})
    return out


def _leg(symbol, side, quantity, entry, stop, price, beta) -> dict:
    sign = 1 if side == 'LONG' else -1
    notional = abs(quantity) * price
    # Risk to stop is zero once the stop sits beyond entry in the profitable direction.
    risk = max(0.0, sign * (entry - stop)) * abs(quantity)
    return {'symbol': symbol, 'side': side, 'notional': notional,
            'beta_notional': sign * beta * notional, 'risk_to_stop': risk}


def portfolio_exposure(legs: list[dict], equity: float) -> Exposure:
    exposure = Exposure(equity=equity)
    if equity <= 0:
        return exposure
    for leg in legs:
        bucket = exposure.by_symbol.setdefault(leg['symbol'], {'notional': 0.0, 'beta_notional': 0.0})
        bucket['notional'] += leg['notional']
        bucket['beta_notional'] += leg['beta_notional']
        exposure.gross_x += leg['notional'] / equity
        exposure.net_beta_x += leg['beta_notional'] / equity
        exposure.open_risk_pct += leg['risk_to_stop'] / equity * 100
    return exposure


def check_new_trade(existing: list[dict], proposed: dict, equity: float,
                    limits: ExposureLimits | None = None) -> tuple[bool, str, dict]:
    """Would the portfolio stay inside limits after adding ``proposed``?"""
    limits = limits or ExposureLimits.from_settings()
    after = portfolio_exposure(existing + [proposed], equity)
    breaches = []
    if after.open_risk_pct > limits.max_open_risk_pct + 1e-12:
        breaches.append(f'open risk {after.open_risk_pct:.2f}% > {limits.max_open_risk_pct}%')
    if abs(after.net_beta_x) > limits.max_net_beta_x + 1e-12:
        breaches.append(f'net BTC-beta {after.net_beta_x:+.2f}x > ±{limits.max_net_beta_x}x')
    if after.gross_x > limits.max_gross_x + 1e-12:
        breaches.append(f'gross {after.gross_x:.2f}x > {limits.max_gross_x}x')
    reason = '; '.join(breaches) or 'portfolio exposure within limits'
    return not breaches, reason, after.as_dict()


def legs_from_open_positions(betas: dict | None = None) -> list[dict]:
    from executor.models import Position

    all_positions = list(Position.objects.filter(status='OPEN'))
    local = [p for p in all_positions if p.source != 'exchange']
    locally_represented = {(p.symbol, p.side) for p in local}
    # Exchange rows are mirrors.  Include them only when no local intended row
    # represents the same leg, otherwise gross/open risk would be counted twice.
    positions = local + [
        p for p in all_positions
        if p.source == 'exchange' and (p.symbol, p.side) not in locally_represented
    ]
    betas = betas or estimate_betas([p.symbol for p in positions])
    return [
        _leg(p.symbol, p.side, p.remaining_quantity or p.quantity, p.entry_price,
             p.stop_loss, p.current_price or p.entry_price, betas[p.symbol]['beta'])
        for p in positions
    ]


def proposed_leg(trade_params: dict, beta: float) -> dict:
    return _leg(trade_params['symbol'], trade_params['side'], trade_params['quantity'],
                trade_params['entry_price'], trade_params['stop_loss'],
                trade_params['entry_price'], beta)
