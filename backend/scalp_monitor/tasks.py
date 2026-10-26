"""S20 H1 paper monitor: order block + open interest confirmation, patient
breakeven/chandelier exit — the best-validated strategy in this project
(PF 1.066 development, 1.117 validation, both base costs; fails validation
stress at PF 0.857). Real market data, zero orders ever placed. Exists to
collect honest forward data per
docs/research/s20_ob_oi_patient_runner/protocol.json before any live
capital decision.

Reuses the EXACT frozen S20 H1 config and signal/feature functions from
l1_filter.order_block_oi_confirmation_scalp — not a reimplementation, so
live behavior cannot silently drift from what was backtested. Candle and
open-interest data are fetched directly from Binance's public REST
endpoints (scalp_monitor.candle_sync / oi_history), independent of the
ingester app's own scheduled tasks, whose health could not be verified
from here.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
import pandas as pd

from carry_monitor.live_prices import get_perp_mark_price
from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
    oi_features,
)

from .candle_sync import sync_minute_candles
from .models import ScalpDecisionLog, ScalpPaperTrade
from .oi_history import fetch_recent_open_interest

logger = logging.getLogger(__name__)

SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
CONFIG = OrderBlockOIConfig('S20_live', route='oi', partial_r=1.5, trail_atr=2.5, target_r=8.0)
MINUTES_LOOKBACK_DAYS = 40
FEE_BPS = 5.0
SLIPPAGE_BPS = 2.0


def _load_minutes(symbol: str) -> pd.DataFrame | None:
    from ingester.models import Candle

    cutoff = timezone.now() - timedelta(days=MINUTES_LOOKBACK_DAYS)
    rows = list(Candle.objects.filter(
        symbol=symbol, interval='1m', timestamp__gte=cutoff, is_closed=True,
    ).order_by('timestamp').values('timestamp', 'open', 'high', 'low', 'close',
                                   'volume', 'taker_buy_volume'))
    if len(rows) < 60 * 24 * 30:  # need enough for 4h EMA200 warmup
        return None
    frame = pd.DataFrame(rows).set_index('timestamp')
    frame.index = pd.to_datetime(frame.index, utc=True)
    for column in ('open', 'high', 'low', 'close', 'volume', 'taker_buy_volume'):
        frame[column] = frame[column].astype(float)
    return frame[~frame.index.duplicated(keep='last')].sort_index()


@shared_task(name='scalp_monitor.evaluate_signal')
def evaluate_signal() -> dict:
    """Scheduled every 15 minutes, shortly after each 15m candle closes."""
    now = timezone.now()
    open_trade = ScalpPaperTrade.objects.filter(status='OPEN').order_by('-opened_at').first()
    if open_trade is not None:
        ScalpDecisionLog.objects.create(
            checked_at=now, action='blocked_open_position',
            detail={'symbol': open_trade.symbol})
        return {'action': 'blocked_open_position', 'symbol': open_trade.symbol}

    for symbol in SYMBOLS:
        try:
            sync_minute_candles(symbol, lookback_days=MINUTES_LOOKBACK_DAYS)
            minutes = _load_minutes(symbol)
            if minutes is None:
                ScalpDecisionLog.objects.create(
                    checked_at=now, symbol=symbol, action='insufficient_history')
                continue
            metrics = fetch_recent_open_interest(symbol, hours=12)
            bars = oi_features(minutes, metrics, CONFIG)
            signals = generate_order_block_oi_signals(bars, CONFIG, symbol)
        except Exception:
            logger.exception('scalp_monitor.evaluate_signal failed for %s', symbol)
            ScalpDecisionLog.objects.create(checked_at=now, symbol=symbol, action='error')
            continue

        latest_bar_time = bars.index[-1]
        latest = [s for s in signals if s['timestamp'] == latest_bar_time]
        if not latest:
            ScalpDecisionLog.objects.create(checked_at=now, symbol=symbol, action='no_signal')
            continue

        signal = latest[0]
        trade = _open_trade(symbol, signal, now)
        ScalpDecisionLog.objects.create(
            checked_at=now, symbol=symbol, action='opened',
            detail={'side': trade.side, 'entry': trade.entry_price, 'stop': trade.stop_loss})
        return {'action': 'opened', 'symbol': symbol, 'side': trade.side}

    return {'action': 'no_signal', 'symbol': None}


def _open_trade(symbol: str, signal: dict, now) -> ScalpPaperTrade:
    entry_price = get_perp_mark_price(symbol)
    side = 'LONG' if signal['side'] == 1 else 'SHORT'
    stop = float(signal['stop'])
    r_value = abs(entry_price - stop)
    risk_usd = 0.50  # identical to S20 H1's backtested fixed_risk_usd
    quantity = risk_usd / r_value if r_value > 0 else 0.0
    return ScalpPaperTrade.objects.create(
        symbol=symbol, side=side, status='OPEN', opened_at=now,
        entry_price=entry_price, initial_stop=stop, stop_loss=stop,
        atr_at_entry=float(signal['atr']), r_value=r_value, best_price=entry_price,
        quantity=quantity, notional_usd=quantity * entry_price,
        setup_id=signal.get('setup_id', ''),
    )


@shared_task(name='scalp_monitor.manage_open_position')
def manage_open_position() -> dict:
    """Scheduled every 1-5 minutes: checks the one open paper trade (if any)
    against a live mark price using S20 H1's exact exit rule — breakeven at
    +1.5R, chandelier trail at 2.5x ATR (frozen at entry), 8.0R cap, 240
    minute time stop."""
    trade = ScalpPaperTrade.objects.filter(status='OPEN').order_by('-opened_at').first()
    if trade is None:
        return {'action': 'no_open_position'}

    side = 1 if trade.side == 'LONG' else -1
    price = get_perp_mark_price(trade.symbol)
    now = timezone.now()

    stop_hit = price <= trade.stop_loss if side == 1 else price >= trade.stop_loss
    if stop_hit:
        _close_trade(trade, trade.stop_loss, 'STOP', now)
        return {'action': 'closed', 'reason': 'STOP'}

    target_price = trade.entry_price + side * CONFIG.target_r * trade.r_value
    if side * (price - target_price) >= 0:
        _close_trade(trade, target_price, 'TARGET', now)
        return {'action': 'closed', 'reason': 'TARGET'}

    if (now - trade.opened_at).total_seconds() / 60 >= CONFIG.max_hold_minutes:
        _close_trade(trade, price, 'TIME', now)
        return {'action': 'closed', 'reason': 'TIME'}

    partial_level = trade.entry_price + side * CONFIG.partial_r * trade.r_value
    if not trade.breakeven_activated and side * (price - partial_level) >= 0:
        trade.breakeven_activated = True

    if trade.breakeven_activated:
        trade.best_price = max(trade.best_price, price) if side == 1 else min(trade.best_price, price)
        breakeven = trade.entry_price * (1 + side * 2 * (FEE_BPS + SLIPPAGE_BPS) / 10_000)
        trail = trade.best_price - side * CONFIG.trail_atr * trade.atr_at_entry
        new_stop = max(trade.stop_loss, breakeven, trail) if side == 1 else min(trade.stop_loss, breakeven, trail)
        trade.stop_loss = new_stop

    trade.save()
    return {'action': 'held', 'symbol': trade.symbol, 'price': price, 'stop': trade.stop_loss}


def _close_trade(trade: ScalpPaperTrade, exit_price: float, reason: str, now) -> None:
    side = 1 if trade.side == 'LONG' else -1
    slipped = exit_price * (1 - side * SLIPPAGE_BPS / 10_000)
    fee = abs(slipped * trade.quantity) * FEE_BPS / 10_000
    pnl = side * (slipped - trade.entry_price) * trade.quantity - fee
    trade.status = 'CLOSED'
    trade.closed_at = now
    trade.exit_price = exit_price
    trade.exit_reason = reason
    trade.realized_pnl_usd = pnl
    trade.r_multiple = pnl / (trade.r_value * trade.quantity) if trade.r_value * trade.quantity else 0.0
    trade.save()
    logger.info('S20 paper CLOSE: %s %s pnl=%+.4f r=%+.2f (%s)',
               trade.symbol, trade.side, pnl, trade.r_multiple, reason)
