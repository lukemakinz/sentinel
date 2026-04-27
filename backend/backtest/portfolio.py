"""Portfolio backtest helpers for multi-symbol evaluation."""
from dataclasses import dataclass, field
from datetime import datetime

from .metrics import BacktestMetrics
from .simulator import BacktestConfig, BacktestSimulator
from l1_filter.mtf import build_top_down_context


@dataclass
class PortfolioBacktestResult:
    symbols: list[str]
    per_symbol: dict[str, BacktestMetrics] = field(default_factory=dict)
    combined: BacktestMetrics | None = None


def run_portfolio_backtest(
    symbols: list[str],
    strategy: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float = 10000.0,
    risk_per_trade: float = 0.005,
    stop_profile: str = 'medium',
    weights: dict[str, float] | None = None,
    allocation_mode: str = 'equal',
) -> PortfolioBacktestResult:
    if not symbols:
        return PortfolioBacktestResult(symbols=[], combined=BacktestMetrics())

    capital_weights = _resolve_weights(symbols, start_date, weights, allocation_mode)
    per_symbol: dict[str, BacktestMetrics] = {}
    equity_curves: list[list[float]] = []
    trades: list[dict] = []

    for symbol in symbols:
        per_symbol_capital = initial_capital * capital_weights[symbol]
        cfg = BacktestConfig(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=per_symbol_capital,
            risk_per_trade=risk_per_trade,
            stop_profile=stop_profile,
        )
        metrics = BacktestSimulator(cfg).run()
        per_symbol[symbol] = metrics
        equity_curves.append(metrics.equity_curve or [per_symbol_capital])
        for trade in metrics.trades:
            trades.append({**trade, 'symbol': symbol})

    combined_curve = _combine_equity_curves(equity_curves)
    combined = BacktestMetrics.from_trades(
        trades,
        combined_curve,
        initial_capital=initial_capital,
    )
    return PortfolioBacktestResult(symbols=symbols, per_symbol=per_symbol, combined=combined)


def _resolve_weights(
    symbols: list[str],
    start_date: datetime,
    weights: dict[str, float] | None,
    allocation_mode: str,
) -> dict[str, float]:
    if weights:
        return _normalize_weights(symbols, weights)
    if allocation_mode == 'regime':
        return _regime_weights(symbols, start_date)
    return _normalize_weights(symbols, None)


def _normalize_weights(symbols: list[str], weights: dict[str, float] | None) -> dict[str, float]:
    if not weights:
        equal = 1.0 / len(symbols)
        return {symbol: equal for symbol in symbols}

    normalized = {symbol: max(0.0, float(weights.get(symbol, 0.0))) for symbol in symbols}
    total = sum(normalized.values())
    if total <= 0:
        equal = 1.0 / len(symbols)
        return {symbol: equal for symbol in symbols}
    return {symbol: value / total for symbol, value in normalized.items()}


def _regime_weights(symbols: list[str], start_date: datetime) -> dict[str, float]:
    base = {symbol: 1.0 for symbol in symbols}
    scores = {}
    for symbol in symbols:
        ctx = _symbol_regime_context(symbol, start_date)
        if not ctx:
            scores[symbol] = base[symbol]
            continue

        score = 1.0
        bias_1d = ctx.get('bias_1d', {})
        bias_4h = ctx.get('bias_4h', {})
        state_4h = ctx.get('state_4h', {})
        state_1h = ctx.get('state_1h', {})
        timing_15m = ctx.get('timing_15m', {})

        if bias_1d.get('direction') == bias_4h.get('direction') != 'NEUTRAL':
            score += 0.35
        if state_4h.get('state') == 'continuation':
            score += 0.35
        if state_4h.get('divergence_aligned'):
            score += 0.15
        if state_1h.get('state') == 'aligned_continuation':
            score += 0.25
        if timing_15m.get('divergence_aligned'):
            score += 0.15
        score += min(float(ctx.get('volatility_4h', 0.0)) * 8.0, 0.45)
        score += min(float(ctx.get('volatility_1h', 0.0)) * 5.0, 0.30)
        score += min(float(ctx.get('bias_15m', {}).get('strength', 0.0)) / 100.0, 0.20)

        # Alts get extra allocation only when the regime is clearly active.
        if symbol in {'SOLUSDT', 'BNBUSDT', 'XRPUSDT'}:
            if state_4h.get('state') == 'continuation' and state_1h.get('state') == 'aligned_continuation':
                score += 0.45
            elif state_4h.get('state') == 'reversal' and state_4h.get('divergence_aligned'):
                score += 0.25
            elif float(ctx.get('volatility_4h', 0.0)) >= 0.04:
                score += 0.20

        scores[symbol] = max(score, 0.25)

    return _normalize_weights(symbols, scores)


def _symbol_regime_context(symbol: str, start_date: datetime) -> dict | None:
    candles_1d = _get_candles_before(symbol, '1d', start_date, 250)
    candles_4h = _get_candles_before(symbol, '4h', start_date, 100)
    candles_1h = _get_candles_before(symbol, '1h', start_date, 100)
    candles_15m = _get_candles_before(symbol, '15m', start_date, 100)
    if not all((candles_1d, candles_4h, candles_1h, candles_15m)):
        candles_1d = candles_1d or _get_candles_after(symbol, '1d', start_date, 30)
        candles_4h = candles_4h or _get_candles_after(symbol, '4h', start_date, 40)
        candles_1h = candles_1h or _get_candles_after(symbol, '1h', start_date, 60)
        candles_15m = candles_15m or _get_candles_after(symbol, '15m', start_date, 80)
    if not all((candles_1d, candles_4h, candles_1h, candles_15m)):
        return None
    ctx = build_top_down_context(candles_1d, candles_4h, candles_1h, candles_15m)
    ctx['volatility_4h'] = _normalized_range(candles_4h[-20:])
    ctx['volatility_1h'] = _normalized_range(candles_1h[-24:])
    return ctx


def _get_candles_before(symbol: str, interval: str, ts: datetime, limit: int) -> list[dict]:
    from ingester.models import Candle

    qs = (
        Candle.objects
        .filter(symbol=symbol, interval=interval, is_closed=True, timestamp__lt=ts)
        .order_by('-timestamp')[:limit]
    )
    return [
        {
            'open': float(c.open),
            'high': float(c.high),
            'low': float(c.low),
            'close': float(c.close),
            'volume': float(c.volume),
        }
        for c in reversed(list(qs))
    ]


def _get_candles_after(symbol: str, interval: str, ts: datetime, limit: int) -> list[dict]:
    from ingester.models import Candle

    qs = (
        Candle.objects
        .filter(symbol=symbol, interval=interval, is_closed=True, timestamp__gte=ts)
        .order_by('timestamp')[:limit]
    )
    return [
        {
            'open': float(c.open),
            'high': float(c.high),
            'low': float(c.low),
            'close': float(c.close),
            'volume': float(c.volume),
        }
        for c in list(qs)
    ]


def _normalized_range(candles: list[dict]) -> float:
    if not candles:
        return 0.0
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    closes = [c['close'] for c in candles]
    base = max(sum(closes) / len(closes), 1e-9)
    return (max(highs) - min(lows)) / base


def _combine_equity_curves(curves: list[list[float]]) -> list[float]:
    if not curves:
        return []
    max_len = max(len(curve) for curve in curves)
    combined: list[float] = []
    for i in range(max_len):
        total = 0.0
        for curve in curves:
            total += curve[i] if i < len(curve) else curve[-1]
        combined.append(total)
    return combined
