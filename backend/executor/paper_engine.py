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

# Conservative defaults.  They are configurable because the paper engine must
# be able to replay the exact same execution assumptions as research.
MARKET_SLIPPAGE = 0.0005   # 5 bps — BTC/ETH
ALT_SLIPPAGE    = 0.0015   # 15 bps — less liquid alts
TAKER_FEE       = 0.0005   # 5 bps
MAKER_FEE       = 0.0002   # 2 bps

_ALT_PAIRS = {'SOLUSDT', 'BNBUSDT', 'AVAXUSDT', 'DOTUSDT', 'ADAUSDT'}


def _slippage_rate(symbol: str) -> float:
    default = ALT_SLIPPAGE if symbol in _ALT_PAIRS else MARKET_SLIPPAGE
    setting = 'PAPER_ALT_SLIPPAGE_BPS' if symbol in _ALT_PAIRS else 'PAPER_MARKET_SLIPPAGE_BPS'
    return float(getattr(settings, setting, default * 10_000)) / 10_000


def _apply_entry_slippage(price: float, side: str, symbol: str,
                          order_type: str = 'MARKET') -> float:
    """Return an adverse entry fill.  Resting limits have no price slippage."""
    if order_type.upper() == 'LIMIT':
        return price
    rate = _slippage_rate(symbol)
    return price * (1 + rate) if side == 'LONG' else price * (1 - rate)


def _apply_exit_slippage(price: float, side: str, symbol: str,
                         order_type: str = 'MARKET') -> float:
    """Return an adverse exit fill (opposite direction to entry slippage)."""
    if order_type.upper() == 'LIMIT':
        return price
    rate = _slippage_rate(symbol)
    return price * (1 - rate) if side == 'LONG' else price * (1 + rate)


def _apply_slippage(price: float, side: str, symbol: str) -> float:
    """Backward-compatible alias for an entry market fill."""
    return _apply_entry_slippage(price, side, symbol)


def _fee_rate(order_type: str = 'MARKET') -> float:
    if order_type.upper() == 'LIMIT':
        return float(getattr(settings, 'PAPER_MAKER_FEE_BPS', MAKER_FEE * 10_000)) / 10_000
    return float(getattr(settings, 'PAPER_TAKER_FEE_BPS', TAKER_FEE * 10_000)) / 10_000


def _apply_fee(price: float, quantity: float, order_type: str = 'MARKET') -> float:
    return price * quantity * _fee_rate(order_type)


class PaperTradingEngine:
    """Simulated trading engine for paper mode."""

    def open_position(self, trade_params, consensus_signal=None):
        """Open a new paper position."""
        tps = trade_params['take_profits']
        side = trade_params['side']
        symbol = trade_params['symbol']
        quantity = float(trade_params['quantity'])
        order_type = str(trade_params.get('order_type') or 'MARKET').upper()
        reference_entry = float(trade_params['entry_price'])
        entry_fill = _apply_entry_slippage(reference_entry, side, symbol, order_type)
        entry_fee = _apply_fee(entry_fill, quantity, order_type)

        snapshot = dict(getattr(consensus_signal, 'analyst_details', None) or {})
        snapshot['_paper_execution'] = {
            'reference_entry': reference_entry,
            'entry_fill': entry_fill,
            'entry_fee': entry_fee,
            'entry_order_type': order_type,
            'initial_stop_loss': float(trade_params['stop_loss']),
            'tp_ratios': [float(tp.get('ratio', tp.get('close_pct', 0.0))) for tp in tps],
            'stop_management_policy': str(getattr(
                settings, 'PAPER_STOP_MANAGEMENT_POLICY', 'INITIAL_STOP_ONLY')).upper(),
        }

        position = Position.objects.create(
            symbol=symbol,
            side=side,
            entry_price=entry_fill,
            current_price=entry_fill,
            quantity=quantity,
            position_size_usd=entry_fill * quantity,
            leverage=trade_params.get('leverage', 1),
            stop_loss=trade_params['stop_loss'],
            take_profit_1=tps[0]['level'] if len(tps) > 0 else None,
            take_profit_2=tps[1]['level'] if len(tps) > 1 else None,
            take_profit_3=tps[2]['level'] if len(tps) > 2 else None,
            remaining_quantity=quantity,
            # Entry commission is a realized trading cost and must be present
            # before any target or stop is processed.
            realized_pnl=-entry_fee,
            strategy=trade_params.get('strategy', 'S1'),
            tier=trade_params.get('tier', ''),
            consensus_signal_id=consensus_signal.id if consensus_signal else None,
            analyst_snapshot=snapshot,
            source='paper',
        )

        logger.info(
            f"📈 PAPER OPEN: {position.symbol} {position.side} "
            f"qty={position.quantity:.6f} @ {position.entry_price:.2f} "
            f"SL={position.stop_loss:.2f} TP1={position.take_profit_1}"
        )

        self._update_account_state()
        return position

    def check_positions(self):
        """Check paper positions only; exchange mirrors are never simulated."""
        positions = Position.objects.filter(
            status='OPEN', source__in=('paper', 'auto'),
        )

        for position in positions:
            market_bar = self._update_position_price(position)
            self._check_sl_tp(position, market_bar)

    def _update_position_price(self, position):
        """Update position with current market price."""
        from ingester.models import Candle
        latest = Candle.objects.filter(
            symbol=position.symbol, interval='1m',
        ).order_by('-timestamp').values('open', 'high', 'low', 'close').first()

        if latest:
            market_bar = {key: float(value) for key, value in latest.items()}
            position.current_price = market_bar['close']
            if position.side == 'LONG':
                position.unrealized_pnl = (position.current_price - position.entry_price) * position.remaining_quantity
            else:
                position.unrealized_pnl = (position.entry_price - position.current_price) * position.remaining_quantity
            position.save()
            return market_bar
        return None

    def _check_sl_tp(self, position, market_bar=None):
        """Check SL/TP using the observed bar range with conservative ordering."""
        if position.status != 'OPEN' or position.remaining_quantity <= 0:
            return
        price = position.current_price
        high = float((market_bar or {}).get('high', price))
        low = float((market_bar or {}).get('low', price))
        open_price = float((market_bar or {}).get('open', price))

        # Stop has priority when both stop and target occur in the same 1m bar.
        # Without tick data this is the conservative, non-look-ahead assumption.
        if position.side == 'LONG' and low <= position.stop_loss:
            stop_reference = min(float(position.stop_loss), open_price)
            self._close_position(position, stop_reference, 'STOP_LOSS')
            return
        elif position.side == 'SHORT' and high >= position.stop_loss:
            stop_reference = max(float(position.stop_loss), open_price)
            self._close_position(position, stop_reference, 'STOP_LOSS')
            return

        # Take Profit 1
        if not position.tp1_hit and position.take_profit_1:
            if (position.side == 'LONG' and high >= position.take_profit_1) or \
               (position.side == 'SHORT' and low <= position.take_profit_1):
                close_qty = position.quantity * self._tp_ratio(position, 0, 0.40)
                if self._partial_or_final(position, close_qty, float(position.take_profit_1), 'TP1'):
                    return
                position.tp1_hit = True
                self._apply_post_tp1_stop(position, price)
                position.save()

        # Take Profit 2
        if not position.tp2_hit and position.take_profit_2 and position.tp1_hit:
            if (position.side == 'LONG' and high >= position.take_profit_2) or \
               (position.side == 'SHORT' and low <= position.take_profit_2):
                close_qty = position.quantity * self._tp_ratio(position, 1, 0.40)
                if self._partial_or_final(position, close_qty, float(position.take_profit_2), 'TP2'):
                    return
                position.tp2_hit = True
                position.save()

        # Some legacy plans have a fixed TP3 and leave a residual runner.
        if position.tp2_hit and position.take_profit_3 and not position.tp3_hit:
            if (position.side == 'LONG' and high >= position.take_profit_3) or \
               (position.side == 'SHORT' and low <= position.take_profit_3):
                close_qty = position.quantity * self._tp_ratio(position, 2, 0.0)
                if self._partial_or_final(position, close_qty, float(position.take_profit_3), 'TP3'):
                    return
                position.tp3_hit = True
                position.save()

        # L3 plans use TP3 as a runner (level=None).  Legacy plans trail only
        # the residual quantity after their fixed third target.
        runner_active = position.tp2_hit and (
            position.take_profit_3 is None or position.tp3_hit)
        if runner_active and position.status == 'OPEN':
            self._check_chandelier(position, price, market_bar)
            if position.status != 'OPEN':
                return

        # Time-based kill: > 8h without hitting 1R → close
        if not position.tp1_hit and self._should_time_kill(position, price):
            self._close_position(position, price, 'TIME_KILL')
            return

    @staticmethod
    def _execution_plan(position) -> dict:
        return dict((position.analyst_snapshot or {}).get('_paper_execution') or {})

    def _tp_ratio(self, position, index: int, default: float) -> float:
        ratios = self._execution_plan(position).get('tp_ratios') or []
        try:
            return max(0.0, min(float(ratios[index]), 1.0))
        except (IndexError, TypeError, ValueError):
            return default

    def _apply_post_tp1_stop(self, position, current_price: float) -> None:
        """Apply only an explicitly selected, researchable stop policy."""
        policy = self._execution_plan(position).get(
            'stop_management_policy', 'INITIAL_STOP_ONLY').upper()
        if policy == 'INITIAL_STOP_ONLY':
            logger.info(f"TP1 hit — initial SL retained for {position.symbol}")
            return

        structural_sl = None
        if policy in {'STRUCTURAL_AFTER_TP1', 'STRUCTURAL_COST_BE_AFTER_TP1'}:
            structural_sl = self._get_structural_sl(position, current_price)

        be_sl = None
        if policy in {'COST_BE_AFTER_TP1', 'STRUCTURAL_COST_BE_AFTER_TP1'}:
            # Cover entry fee, a taker exit fee and adverse market slippage.
            cost_rate = 2 * _fee_rate('MARKET') + _slippage_rate(position.symbol)
            delta = position.entry_price * cost_rate
            be_sl = position.entry_price + delta if position.side == 'LONG' \
                else position.entry_price - delta

        candidates = [value for value in (structural_sl, be_sl) if value is not None]
        if not candidates:
            return
        candidate = max(candidates) if position.side == 'LONG' else min(candidates)
        if position.side == 'LONG' and candidate > position.stop_loss:
            position.stop_loss = candidate
        elif position.side == 'SHORT' and candidate < position.stop_loss:
            position.stop_loss = candidate
        else:
            return
        position.sl_moved_to_be = be_sl is not None
        logger.info(f"TP1 hit — {policy} moved SL to {position.stop_loss:.2f} for {position.symbol}")

    def _get_structural_sl(self, position, current_price: float):
        """Find last intermediate swing HL (LONG) or LH (SHORT) for adaptive SL after TP1."""
        from ingester.models import Candle
        from analysts.structure import detect_swing_points
        import numpy as np

        candles = list(Candle.objects.filter(
            symbol=position.symbol, interval='15m', is_closed=True,
        ).order_by('-timestamp').values('high', 'low')[:30])
        if len(candles) < 10:
            return None

        highs = np.array([float(c['high']) for c in reversed(candles)])
        lows  = np.array([float(c['low'])  for c in reversed(candles)])
        swings = detect_swing_points(highs, lows, lookback=3)

        if position.side == 'LONG':
            hl_levels = [p for _, p, t in swings if t == 'HL' and p < current_price]
            return max(hl_levels) if hl_levels else None
        else:
            lh_levels = [p for _, p, t in swings if t == 'LH' and p > current_price]
            return min(lh_levels) if lh_levels else None

    def _check_chandelier(self, position, price, market_bar=None):
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
            trigger = position.chandelier_stop or position.stop_loss
            low = float((market_bar or {}).get('low', price))
            open_price = float((market_bar or {}).get('open', price))
            if low <= trigger:
                self._close_position(position, min(float(trigger), open_price), 'TP3_CHANDELIER')
        else:
            if current_stop == 0 or new_stop < current_stop:
                position.chandelier_stop = new_stop
                position.save()
            trigger = position.chandelier_stop or position.stop_loss
            high = float((market_bar or {}).get('high', price))
            open_price = float((market_bar or {}).get('open', price))
            if high >= trigger:
                self._close_position(position, max(float(trigger), open_price), 'TP3_CHANDELIER')

    def _should_time_kill(self, position, price) -> bool:
        return _calc.check_time_kill(
            position.side,
            position.opened_at,
            position.entry_price,
            position.stop_loss,
            price,
            strategy=position.strategy,
            tp1_hit=position.tp1_hit,
            tp2_hit=position.tp2_hit,
        )

    def _partial_or_final(self, position, quantity, price, reason) -> bool:
        quantity = min(max(float(quantity), 0.0), float(position.remaining_quantity))
        if quantity <= 0:
            return False
        if quantity >= float(position.remaining_quantity) - 1e-12:
            self._close_position(position, price, reason, order_type='LIMIT')
            return True
        self._partial_close(position, quantity, price, reason, order_type='LIMIT')
        return False

    def _partial_close(self, position, quantity, price, reason, order_type='LIMIT'):
        """Partially close a position and charge the actual exit costs."""
        quantity = min(max(float(quantity), 0.0), float(position.remaining_quantity))
        if quantity <= 0:
            return 0.0
        fill_price = _apply_exit_slippage(
            float(price), position.side, position.symbol, order_type)
        if position.side == 'LONG':
            pnl = (fill_price - position.entry_price) * quantity
        else:
            pnl = (position.entry_price - fill_price) * quantity
        pnl -= _apply_fee(fill_price, quantity, order_type)

        position.remaining_quantity -= quantity
        position.realized_pnl += pnl
        position.save()

        logger.info(
            f"📊 Partial close {reason}: {position.symbol} qty={quantity:.6f} "
            f"fill={fill_price:.4f} net PnL={pnl:+.2f}")
        return pnl

    def _close_position(self, position, exit_price, reason, order_type='MARKET'):
        """Fully close a position."""
        if position.status != 'OPEN':
            return None
        remaining = position.remaining_quantity
        slipped_exit = _apply_exit_slippage(
            float(exit_price), position.side, position.symbol, order_type)
        if position.side == 'LONG':
            final_pnl = (slipped_exit - position.entry_price) * remaining
        else:
            final_pnl = (position.entry_price - slipped_exit) * remaining
        final_pnl -= _apply_fee(slipped_exit, remaining, order_type)

        total_pnl = position.realized_pnl + final_pnl
        pnl_pct = total_pnl / position.position_size_usd * 100 if position.position_size_usd > 0 else 0

        # Realized R uses the original invalidation and includes every partial
        # fill, fee and slippage charge.
        initial_sl = float(self._execution_plan(position).get(
            'initial_stop_loss', position.stop_loss))
        initial_risk_usd = abs(position.entry_price - initial_sl) * position.quantity
        rr = total_pnl / initial_risk_usd if initial_risk_usd > 0 else 0.0

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
            strategy=position.strategy or 'S1',
            side=position.side,
            entry_price=position.entry_price,
            exit_price=slipped_exit,
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
                entry_price=position.entry_price, exit_price=slipped_exit,
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
        return trade_record

    def _update_account_state(self, pnl_change=0):
        """Update account balance and stats."""
        state = AccountState.objects.order_by('-updated_at').first()
        if not state:
            state = AccountState(
                balance=settings.INITIAL_BALANCE,
                equity=settings.INITIAL_BALANCE,
                peak_equity=settings.INITIAL_BALANCE,
                spot_reserve_balance=0.0,
            )

        reserve_ratio = float(getattr(settings, 'PROFIT_TO_SPOT_RATIO', 0.10))
        reserve_transfer = pnl_change * reserve_ratio if pnl_change > 0 else 0.0
        state.spot_reserve_balance += reserve_transfer
        state.balance += (pnl_change - reserve_transfer)
        open_positions = Position.objects.filter(
            status='OPEN', source__in=('paper', 'auto'),
        )
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
