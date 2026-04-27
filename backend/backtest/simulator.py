"""Backtest simulator — replays historical OHLCV, applies L1+L3, tracks P&L."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from django.conf import settings

from executor.l3_calculator import L3Calculator
from .metrics import BacktestMetrics
from .slippage_model import apply_slippage, compute_fee, OrderType

logger = logging.getLogger(__name__)

_calc = L3Calculator()

PENDING_ORDER_TTL = timedelta(hours=4)   # Cancel limit if not filled in 4h
L1_SCAN_INTERVAL  = timedelta(hours=1)   # Run L1 every hour


@dataclass
class BacktestConfig:
    symbol:          str
    strategy:        str = 'S1'
    start_date:      datetime = None
    end_date:        datetime = None
    initial_capital: float = 10000.0
    risk_per_trade:  float = 0.005   # 0.5% per trade
    stop_profile:    str = 'medium'


class BacktestSimulator:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.current_capital = config.initial_capital
        self.open_positions:  list[dict] = []
        self.pending_orders:  list[dict] = []
        self.closed_trades:   list[dict] = []
        self.equity_curve:    list[float] = [config.initial_capital]
        self._last_l1_scan:   Optional[datetime] = None

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self) -> BacktestMetrics:
        candles_1m = self._load_candles()
        logger.info(f"Backtest {self.config.symbol}/{self.config.strategy}: "
                    f"{len(candles_1m)} 1m candles")

        for candle in candles_1m:
            ts = candle['timestamp']

            # Cancel expired pending orders
            self._expire_pending_orders(ts)

            # Try to fill pending limit orders
            self._check_pending_fills(candle, ts)

            # Update open positions (SL/TP/time-kill)
            self._update_positions(candle)

            # Run L1 scanner once per hour
            if self._should_scan(ts):
                trade_context = self._scan_l1(ts)
                if trade_context:
                    trade_context['stop_profile'] = self.config.stop_profile
                    execution_strategy = trade_context.get('strategy', self.config.strategy)
                    trade_params = _calc.calculate(
                        trade_context,
                        {'action': 'APPROVE', 'size_multiplier': 1.0},
                        strategy=execution_strategy,
                    )
                    if trade_params:
                        if trade_params.get('order_type') == 'MARKET':
                            self._open_position(trade_params, ts)
                        else:
                            self._add_pending_order(trade_params, ts)
                self._last_l1_scan = ts

            self.equity_curve.append(self._current_equity())

        return BacktestMetrics.from_trades(
            self.closed_trades,
            self.equity_curve,
            initial_capital=self.config.initial_capital,
        )

    # ── Order management ───────────────────────────────────────────────────

    def _add_pending_order(self, trade_params: dict, ts: datetime):
        if self.open_positions:
            return  # Only one position at a time
        if self.pending_orders:
            return  # Only one pending order at a time
        trade_params['created_at'] = ts
        trade_params['entry_session'] = self._session_for_timestamp(ts)
        self.pending_orders.append(trade_params)

    def _check_pending_fills(self, candle: dict, ts: datetime):
        candle = {k: float(v) if hasattr(v, '__float__') else v for k, v in candle.items()}
        filled = []
        current_session = self._session_for_timestamp(ts)
        for order in self.pending_orders:
            if order.get('entry_session') != current_session:
                continue
            entry = order['entry_price']
            side  = order['side']
            # LONG: fills if candle low <= entry (limit buy)
            if side == 'LONG'  and candle['low'] <= entry:
                self._open_position(order, ts)
                filled.append(order)
            # SHORT: fills if candle high >= entry (limit sell)
            elif side == 'SHORT' and candle['high'] >= entry:
                self._open_position(order, ts)
                filled.append(order)
        self.pending_orders = [o for o in self.pending_orders if o not in filled]

    def _expire_pending_orders(self, ts: datetime):
        self.pending_orders = [
            o for o in self.pending_orders
            if (ts - o['created_at']) < PENDING_ORDER_TTL
            and o.get('entry_session') == self._session_for_timestamp(ts)
        ]

    # ── Position management ────────────────────────────────────────────────

    def _open_position(self, trade_params: dict, ts: datetime):
        if self.current_capital <= 0:
            return
        r = abs(trade_params['entry_price'] - trade_params['stop_loss'])
        if r <= 0:
            return

        risk_usd = self.current_capital * self.config.risk_per_trade * trade_params.get('size_multiplier', 1.0)
        leverage = max(1, int(trade_params.get('leverage', getattr(settings, 'MAX_LEVERAGE', 10))))
        quantity_by_risk = risk_usd / r

        order_type = OrderType.MARKET if trade_params.get('order_type') == 'MARKET' else OrderType.LIMIT
        entry = apply_slippage(trade_params['entry_price'], order_type, trade_params['side'])
        max_margin_pct = float(getattr(settings, 'MAX_MARGIN_PER_TRADE_PCT', 0.15))
        max_margin_usd = self.current_capital * max_margin_pct
        max_notional = max_margin_usd * leverage
        quantity_by_margin = max_notional / entry if entry > 0 else 0.0
        quantity = min(quantity_by_risk, quantity_by_margin)
        if quantity <= 0:
            return

        position_size_usd = quantity * entry
        margin_used = position_size_usd / leverage if leverage > 0 else position_size_usd
        fee   = compute_fee(position_size_usd, order_type)
        if margin_used > max_margin_usd or (margin_used + fee) > self.current_capital:
            return

        session = self._session_for_timestamp(ts)
        position = {
            'symbol':       trade_params['symbol'],
            'side':         trade_params['side'],
            'entry_price':  entry,
            'initial_entry_price': entry,
            'stop_loss':    trade_params['stop_loss'],
            'initial_stop_loss': trade_params['stop_loss'],
            'take_profits': trade_params['take_profits'],
            'quantity':     quantity,
            'initial_quantity': quantity,
            'position_size_usd': position_size_usd,
            'margin_used':  margin_used,
            'leverage':     leverage,
            'margin_mode':  trade_params.get('margin_mode', getattr(settings, 'DEFAULT_MARGIN_MODE', 'isolated')),
            'liquidation_price': trade_params.get('liquidation_price'),
            'r_value':      r,
            'strategy':     trade_params['strategy'],
            'stop_profile': trade_params.get('stop_profile', self.config.stop_profile),
            'entry_mode':   trade_params.get('entry_mode', 'LIMIT'),
            'opened_at':    ts,
            'session':      session,
            'tp1_hit':      False,
            'tp2_hit':      False,
            'fees':         fee,
            'fees_realized': 0.0,
            'realized_pnl': 0.0,
            'partial_exits': [],
            'best_price': entry,
        }
        self.open_positions.append(position)

    def _update_positions(self, candle: dict):
        # Ensure all candle values are float (DB returns Decimal)
        candle = {k: float(v) if hasattr(v, '__float__') else v for k, v in candle.items()}
        remaining = []
        for pos in self.open_positions:
            if pos['side'] == 'LONG':
                pos['best_price'] = max(float(pos.get('best_price', pos['entry_price'])), candle['high'])
            else:
                pos['best_price'] = min(float(pos.get('best_price', pos['entry_price'])), candle['low'])
            closed = self._check_position(pos, candle)
            if not closed:
                remaining.append(pos)
        self.open_positions = remaining

    def _check_position(self, pos: dict, candle: dict) -> bool:
        """Returns True if position was fully closed."""
        price = candle['close']
        high, low = candle['high'], candle['low']
        side = pos['side']

        # Stop Loss
        if (side == 'LONG'  and low  <= pos['stop_loss']) or \
           (side == 'SHORT' and high >= pos['stop_loss']):
            self._close_position(pos, pos['stop_loss'], 'STOP_LOSS')
            return True

        tp_levels = [tp for tp in pos['take_profits'] if not tp.get('runner', False)]

        # TP1
        if not pos['tp1_hit'] and len(tp_levels) > 0 and tp_levels[0]['level']:
            tp1 = tp_levels[0]['level']
            if (side == 'LONG' and high >= tp1) or (side == 'SHORT' and low <= tp1):
                tp1_ratio = float(tp_levels[0].get('ratio', 0.40))
                pos['tp1_hit']  = True
                self._record_partial(pos, tp1, tp1_ratio, 'TP1')
                fee_buffer = abs(pos['entry_price']) * 0.0005
                if side == 'LONG':
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + fee_buffer)
                else:
                    pos['stop_loss'] = min(pos['stop_loss'], pos['entry_price'] - fee_buffer)

        # TP2
        if pos['tp1_hit'] and not pos['tp2_hit'] and len(tp_levels) > 1 and tp_levels[1]['level']:
            tp2 = tp_levels[1]['level']
            if (side == 'LONG' and high >= tp2) or (side == 'SHORT' and low <= tp2):
                pos['tp2_hit']  = True
                self._record_partial(pos, tp2, float(tp_levels[1].get('ratio', 0.40)), 'TP2')
                tp1_level = tp_levels[0]['level']
                if side == 'LONG':
                    pos['stop_loss'] = max(pos['stop_loss'], tp1_level)
                else:
                    pos['stop_loss'] = min(pos['stop_loss'], tp1_level)

        self._update_trailing_stop(pos)

        # Time-kill check after intrabar SL/TP logic
        if _calc.check_time_kill(
            side, pos['opened_at'], pos['initial_entry_price'], pos['initial_stop_loss'],
            price, strategy=pos.get('strategy', 'S1'),
            tp1_hit=pos.get('tp1_hit', False), tp2_hit=pos.get('tp2_hit', False)
        ):
            self._close_position(pos, price, 'TIME_KILL')
            return True

        # Runner: chandelier or time-kill handles it — keep open
        return False

    def _close_position(self, pos: dict, exit_price, reason: str):
        exit_price = apply_slippage(float(exit_price), OrderType.MARKET, pos['side'])
        remaining_qty = pos['quantity']
        fee = compute_fee(remaining_qty * exit_price, OrderType.MARKET)
        entry_fee_share = max(pos.get('fees', 0.0) - pos.get('fees_realized', 0.0), 0.0)

        if pos['side'] == 'LONG':
            pnl = (exit_price - pos['entry_price']) * remaining_qty - fee - entry_fee_share
        else:
            pnl = (pos['entry_price'] - exit_price) * remaining_qty - fee - entry_fee_share

        pnl += pos.get('realized_pnl', 0.0)

        pnl_pct = pnl / max(pos['position_size_usd'], 1e-9) * 100

        self.current_capital += pnl
        self.closed_trades.append({
            'symbol':       pos['symbol'],
            'side':         pos['side'],
            'entry_price':  pos['entry_price'],
            'exit_price':   exit_price,
            'position_size_usd': round(pos.get('position_size_usd', pos['quantity'] * pos['entry_price']), 2),
            'margin_used':  round(pos.get('margin_used', 0.0), 2),
            'leverage':     pos.get('leverage', 1),
            'pnl':          round(pnl, 2),
            'pnl_pct':      round(pnl_pct, 4),
            'close_reason': reason,
            'strategy':     pos.get('strategy', 'S1'),
            'stop_profile': pos.get('stop_profile', self.config.stop_profile),
            'entry_mode':   pos.get('entry_mode', 'LIMIT'),
            'opened_at':    pos.get('opened_at'),
            'session':      pos.get('session', 'unknown'),
            'partials':     pos.get('partial_exits', []),
        })

    def _record_partial(self, pos: dict, price: float, ratio: float, label: str):
        """Realize a partial exit immediately and reduce remaining quantity."""
        ratio = max(0.0, min(float(ratio), 1.0))
        close_qty = min(pos['initial_quantity'] * ratio, pos['quantity'])
        if close_qty <= 0:
            return

        fee = compute_fee(close_qty * price, OrderType.MARKET)
        entry_fee_share = pos.get('fees', 0.0) * (close_qty / max(pos['initial_quantity'], 1e-9))
        if pos['side'] == 'LONG':
            pnl = (price - pos['entry_price']) * close_qty - fee - entry_fee_share
        else:
            pnl = (pos['entry_price'] - price) * close_qty - fee - entry_fee_share

        pos['quantity'] -= close_qty
        pos['fees_realized'] += entry_fee_share
        pos['realized_pnl'] += pnl
        pos.setdefault('partial_exits', []).append({
            'label': label,
            'price': round(price, 4),
            'ratio': round(ratio, 4),
            'quantity': round(close_qty, 8),
            'pnl': round(pnl, 4),
        })

    def _update_trailing_stop(self, pos: dict):
        """Give S1C runner more room while still locking in structure-based progress."""
        if pos.get('strategy') != 'S1C' or not pos.get('tp1_hit'):
            return

        r = float(pos.get('r_value') or 0.0)
        if r <= 0:
            return

        best = float(pos.get('best_price', pos['entry_price']))
        side = pos['side']
        if side == 'LONG':
            trail_mult = 0.8 if pos.get('tp2_hit') else 1.1
            trail_stop = best - trail_mult * r
            pos['stop_loss'] = max(pos['stop_loss'], trail_stop)
        else:
            trail_mult = 0.8 if pos.get('tp2_hit') else 1.1
            trail_stop = best + trail_mult * r
            pos['stop_loss'] = min(pos['stop_loss'], trail_stop)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _should_scan(self, ts: datetime) -> bool:
        if self._last_l1_scan is None:
            return True
        return (ts - self._last_l1_scan) >= L1_SCAN_INTERVAL

    def _current_equity(self) -> float:
        unrealized = 0.0
        for pos in self.open_positions:
            unrealized += pos.get('unrealized_pnl', 0)
        return self.current_capital + unrealized

    @staticmethod
    def _session_for_timestamp(ts: datetime) -> str:
        hour = ts.hour
        if 2 <= hour < 5:
            return 'asian'
        if 7 <= hour < 10:
            return 'london'
        if 13 <= hour < 16:
            return 'ny'
        if 16 <= hour < 18:
            return 'ny_continuation'
        return 'other'

    def _load_candles(self) -> list[dict]:
        """
        Auto-selects the interval with best coverage of the requested date range.
        Picks the interval whose candles span the most of [start_date, end_date].
        """
        from ingester.models import Candle
        from django.db.models import Min, Max

        requested_days = (self.config.end_date - self.config.start_date).days
        best_interval  = None
        best_count     = 0
        best_coverage  = 0.0

        for interval in ('1h', '4h', '15m', '5m', '1m'):   # prefer 1h first
            agg = Candle.objects.filter(
                symbol=self.config.symbol,
                interval=interval,
                is_closed=True,
                timestamp__gte=self.config.start_date,
                timestamp__lt=self.config.end_date,
            ).aggregate(cnt=__import__('django.db.models',fromlist=['Count']).Count('id'),
                        first=Min('timestamp'), last=Max('timestamp'))

            cnt = agg['cnt'] or 0
            if cnt < 50:
                continue

            # Coverage = days spanned by available data vs requested range
            if agg['first'] and agg['last']:
                spanned = (agg['last'] - agg['first']).days
                coverage = spanned / max(requested_days, 1)
            else:
                coverage = 0.0

            if coverage > best_coverage or (coverage == best_coverage and cnt > best_count):
                best_interval = interval
                best_count    = cnt
                best_coverage = coverage

        if not best_interval:
            logger.warning(
                f"No candle data for {self.config.symbol} "
                f"{self.config.start_date:%Y-%m-%d}–{self.config.end_date:%Y-%m-%d}. "
                f"Run: python manage.py download_history --symbol {self.config.symbol} --years 1 --interval 1h"
            )
            return []

        logger.info(
            f"Backtest {self.config.symbol}: using {best_interval} "
            f"({best_count:,} candles, {best_coverage:.0%} coverage)"
        )
        self._sim_interval = best_interval
        qs = Candle.objects.filter(
            symbol=self.config.symbol,
            interval=best_interval,
            is_closed=True,
            timestamp__gte=self.config.start_date,
            timestamp__lt=self.config.end_date,
        ).order_by('timestamp').values('open', 'high', 'low', 'close', 'volume', 'timestamp')
        return list(qs)

    def _scan_l1(self, ts: datetime) -> Optional[dict]:
        """Run L1 scanner on historical data up to ts. Returns TradeContext or None."""
        from l1_filter.scanner import L1Scanner

        class HistoricalScanner(L1Scanner):
            def __init__(self, symbol, ts):
                self._symbol = symbol
                self._ts = ts

            def _get_candles(self, symbol, interval, limit):
                from ingester.models import Candle
                qs = (Candle.objects
                      .filter(symbol=symbol, interval=interval,
                              is_closed=True, timestamp__lt=self._ts)
                      .order_by('-timestamp')[:limit])
                return [
                    {'open': float(c.open), 'high': float(c.high),
                     'low':  float(c.low),  'close': float(c.close), 'volume': float(c.volume)}
                    for c in reversed(list(qs))
                ]

            def _save(self, *args, **kwargs):
                pass  # Don't save to DB during backtest

        try:
            scanner = HistoricalScanner(self.config.symbol, ts)
            return scanner.scan(self.config.symbol, now=ts, strategy=self.config.strategy)
        except Exception as e:
            logger.debug(f"L1 scan error at {ts}: {e}")
            return None
