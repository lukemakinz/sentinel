"""
Paper Trading Engine — simulated order execution using real-time prices.
"""
import logging
from datetime import timedelta, datetime, timezone as dt_tz

from django.conf import settings
from django.utils import timezone

from .models import Position, Trade, AccountState
from .l3_calculator import L3Calculator
from risk.kill_switches import update_after_trade

logger = logging.getLogger(__name__)

_calc = L3Calculator()

# Realistic paper trading slippage (market orders on futures)
MARKET_SLIPPAGE = 0.0005   # 0.05% — conservative BTC/ETH major pairs
ALT_SLIPPAGE    = 0.0015   # 0.15% — SOL/BNB etc.
TAKER_FEE       = 0.0005   # 0.05% Binance taker fee

_ALT_PAIRS = {'SOLUSDT', 'BNBUSDT', 'AVAXUSDT', 'DOTUSDT', 'ADAUSDT'}


def _apply_slippage(price: float, side: str, symbol: str) -> float:
    """Apply realistic market order slippage."""
    rate = ALT_SLIPPAGE if symbol in _ALT_PAIRS else MARKET_SLIPPAGE
    return price * (1 + rate) if side == 'LONG' else price * (1 - rate)


def _apply_fee(price: float, quantity: float) -> float:
    return price * quantity * TAKER_FEE


class PaperTradingEngine:
    """Simulated trading engine for paper mode."""

    def open_position(self, trade_params, consensus_signal=None):
        """Open a new paper position."""
        tps = trade_params['take_profits']

        position = Position.objects.create(
            symbol=trade_params['symbol'],
            side=trade_params['side'],
            entry_price=trade_params['entry_price'],
            current_price=trade_params['entry_price'],
            quantity=trade_params['quantity'],
            position_size_usd=trade_params['position_size_usd'],
            leverage=trade_params.get('leverage', 1),
            stop_loss=trade_params['stop_loss'],
            take_profit_1=tps[0]['level'] if len(tps) > 0 else None,
            take_profit_2=tps[1]['level'] if len(tps) > 1 else None,
            take_profit_3=tps[2]['level'] if len(tps) > 2 else None,
            remaining_quantity=trade_params['quantity'],
            tier=trade_params.get('tier', ''),
            consensus_signal_id=consensus_signal.id if consensus_signal else None,
            analyst_snapshot=consensus_signal.analyst_details if consensus_signal else {},
        )

        logger.info(
            f"📈 PAPER OPEN: {position.symbol} {position.side} "
            f"qty={position.quantity:.6f} @ {position.entry_price:.2f} "
            f"SL={position.stop_loss:.2f} TP1={position.take_profit_1}"
        )

        self._update_account_state()
        return position

    def check_positions(self):
        """Check all open positions against current prices for SL/TP hits."""
        positions = Position.objects.filter(status='OPEN')

        for position in positions:
            self._update_position_price(position)
            self._check_sl_tp(position)

    def _update_position_price(self, position):
        """Update position with current market price."""
        from ingester.models import Candle
        latest = Candle.objects.filter(
            symbol=position.symbol, interval='1m',
        ).order_by('-timestamp').values_list('close', flat=True).first()

        if latest:
            position.current_price = float(latest)
            if position.side == 'LONG':
                position.unrealized_pnl = (position.current_price - position.entry_price) * position.remaining_quantity
            else:
                position.unrealized_pnl = (position.entry_price - position.current_price) * position.remaining_quantity
            position.save()

    def _check_sl_tp(self, position):
        """Check stop loss and take profit levels."""
        price = position.current_price

        # Stop Loss
        if position.side == 'LONG' and price <= position.stop_loss:
            self._close_position(position, price, 'STOP_LOSS')
            return
        elif position.side == 'SHORT' and price >= position.stop_loss:
            self._close_position(position, price, 'STOP_LOSS')
            return

        # Take Profit 1 (close 40%)
        if not position.tp1_hit and position.take_profit_1:
            if (position.side == 'LONG' and price >= position.take_profit_1) or \
               (position.side == 'SHORT' and price <= position.take_profit_1):
                close_qty = position.quantity * 0.40
                self._partial_close(position, close_qty, price, 'TP1')
                position.tp1_hit = True
                # Move SL to breakeven
                position.stop_loss = position.entry_price
                position.sl_moved_to_be = True
                position.save()
                logger.info(f"TP1 hit — SL moved to breakeven for {position.symbol}")

        # Take Profit 2 (close 40% of original — now corrected from 30%)
        if not position.tp2_hit and position.take_profit_2 and position.tp1_hit:
            if (position.side == 'LONG' and price >= position.take_profit_2) or \
               (position.side == 'SHORT' and price <= position.take_profit_2):
                close_qty = position.quantity * 0.40
                self._partial_close(position, close_qty, price, 'TP2')
                position.tp2_hit = True
                position.save()

        # Take Profit 3 — runner (20%) uses chandelier trailing stop, no fixed target
        if position.tp2_hit and not position.tp3_hit:
            self._check_chandelier(position, price)

        # Time-based kill: > 8h without hitting 1R → close
        if not position.tp1_hit and self._should_time_kill(position, price):
            self._close_position(position, price, 'TIME_KILL')
            return

    def _check_chandelier(self, position, price):
        """Update and check chandelier trailing stop for the runner (20%)."""
        from ingester.models import Candle
        candles = list(Candle.objects.filter(
            symbol=position.symbol, interval='1h', is_closed=True,
        ).order_by('-timestamp').values_list('high', 'low', flat=False)[:24])

        if not candles:
            return

        highs = [float(c[0]) for c in reversed(candles)]
        lows  = [float(c[1]) for c in reversed(candles)]

        # Approximate ATR from recent candles
        atr = sum(h - l for h, l in zip(highs[-14:], lows[-14:])) / 14 if len(highs) >= 14 else 0
        if atr <= 0:
            return

        series = highs if position.side == 'LONG' else lows
        new_stop = _calc.compute_chandelier_stop(position.side, series, atr)
        if new_stop is None:
            return

        current_stop = position.chandelier_stop or 0

        if position.side == 'LONG':
            if new_stop > current_stop:
                position.chandelier_stop = new_stop
                position.save()
            if price <= (position.chandelier_stop or position.stop_loss):
                close_qty = position.remaining_quantity
                self._partial_close(position, close_qty, price, 'TP3_CHANDELIER')
                position.tp3_hit = True
                position.status = 'CLOSED'
                position.save()
        else:
            if current_stop == 0 or new_stop < current_stop:
                position.chandelier_stop = new_stop
                position.save()
            if price >= (position.chandelier_stop or position.stop_loss):
                close_qty = position.remaining_quantity
                self._partial_close(position, close_qty, price, 'TP3_CHANDELIER')
                position.tp3_hit = True
                position.status = 'CLOSED'
                position.save()

    def _should_time_kill(self, position, price) -> bool:
        return _calc.check_time_kill(
            position.side,
            position.opened_at,
            position.entry_price,
            position.stop_loss,
            price,
        )

    def _partial_close(self, position, quantity, price, reason):
        """Partially close a position."""
        if position.side == 'LONG':
            pnl = (price - position.entry_price) * quantity
        else:
            pnl = (position.entry_price - price) * quantity

        position.remaining_quantity -= quantity
        position.realized_pnl += pnl
        position.save()

        logger.info(f"📊 Partial close {reason}: {position.symbol} qty={quantity:.6f} PnL={pnl:+.2f}")

    def _close_position(self, position, exit_price, reason):
        """Fully close a position."""
        remaining = position.remaining_quantity
        if position.side == 'LONG':
            final_pnl = (exit_price - position.entry_price) * remaining
        else:
            final_pnl = (position.entry_price - exit_price) * remaining

        total_pnl = position.realized_pnl + final_pnl
        pnl_pct = total_pnl / position.position_size_usd * 100 if position.position_size_usd > 0 else 0

        # Calculate risk-reward
        risk = abs(position.entry_price - position.stop_loss)
        if risk > 0:
            rr = (exit_price - position.entry_price) / risk if position.side == 'LONG' else (position.entry_price - exit_price) / risk
        else:
            rr = 0

        # Apply slippage + fee on market close (realistic paper trading)
        slipped_exit = _apply_slippage(exit_price, position.side, position.symbol)
        fee = _apply_fee(slipped_exit, remaining)
        if position.side == 'LONG':
            final_pnl -= (exit_price - slipped_exit) * remaining + fee
        else:
            final_pnl -= (slipped_exit - exit_price) * remaining + fee
        total_pnl = position.realized_pnl + final_pnl

        position.status = 'CLOSED'
        position.close_reason = reason
        position.closed_at = timezone.now()
        position.realized_pnl = total_pnl
        position.remaining_quantity = 0
        position.save()

        # Create trade journal entry
        duration = (position.closed_at - position.opened_at).total_seconds() / 60

        trade_record = Trade.objects.create(
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            position_size_usd=position.position_size_usd,
            pnl=total_pnl,
            pnl_percent=pnl_pct,
            risk_reward=rr,
            entry_time=position.opened_at,
            exit_time=position.closed_at,
            duration_minutes=int(duration),
            tier=position.tier,
            close_reason=reason,
            analyst_snapshot=position.analyst_snapshot,
            conviction_score=0,
        )

        # Tax event (PIT-38)
        from .models import TaxEvent
        TaxEvent.objects.get_or_create(
            trade=trade_record,
            defaults=dict(
                symbol=position.symbol, side=position.side,
                entry_price=position.entry_price, exit_price=exit_price,
                quantity=position.quantity, pnl_usd=total_pnl,
                close_date=timezone.now().date(),
            )
        )

        # Update risk state
        update_after_trade(pnl_pct)
        self._update_account_state(total_pnl)

        emoji = "✅" if total_pnl >= 0 else "❌"
        logger.info(
            f"{emoji} CLOSED: {position.symbol} {position.side} "
            f"PnL={total_pnl:+.2f} ({pnl_pct:+.1f}%) RR={rr:.1f} [{reason}]"
        )

    def _update_account_state(self, pnl_change=0):
        """Update account balance and stats."""
        state = AccountState.objects.order_by('-updated_at').first()
        if not state:
            state = AccountState(
                balance=settings.INITIAL_BALANCE,
                equity=settings.INITIAL_BALANCE,
                peak_equity=settings.INITIAL_BALANCE,
            )

        state.balance += pnl_change
        open_positions = Position.objects.filter(status='OPEN')
        state.unrealized_pnl = sum(p.unrealized_pnl for p in open_positions)
        state.equity = state.balance + state.unrealized_pnl

        trades = Trade.objects.all()
        state.total_trades = trades.count()
        state.winning_trades = trades.filter(pnl__gt=0).count()
        state.losing_trades = trades.filter(pnl__lt=0).count()
        state.total_pnl = sum(t.pnl for t in trades)

        if state.equity > state.peak_equity:
            state.peak_equity = state.equity
        drawdown = (state.peak_equity - state.equity) / state.peak_equity * 100 if state.peak_equity > 0 else 0
        state.max_drawdown = max(state.max_drawdown, drawdown)

        state.pk = None  # Create new record
        state.save()
