"""Celery tasks for trade execution and position monitoring."""
import logging
from datetime import datetime, timezone
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='executor.process_signal')
def process_signal(consensus_signal_id):
    """Legacy consensus entrypoint; fail closed while that app is disabled."""
    try:
        from consensus.models import ConsensusSignal
    except (ImportError, RuntimeError) as exc:
        logger.error('Legacy consensus execution path is disabled: %s', exc)
        return {'ok': False, 'reason': 'legacy_consensus_disabled'}
    from risk.manager import RiskManager
    from .paper_engine import PaperTradingEngine
    from ingester.models import Candle, WatchedPair
    from django.conf import settings

    try:
        signal = ConsensusSignal.objects.get(id=consensus_signal_id)
    except ConsensusSignal.DoesNotExist:
        return

    if signal.action_taken:
        return

    active_symbols = set(WatchedPair.get_active_symbols())
    if signal.symbol not in active_symbols:
        logger.info(f"Trade skipped: {signal.symbol} is not enabled in active WatchedPair list")
        signal.action_taken = True
        signal.save()
        return

    # Get current price
    latest = Candle.objects.filter(
        symbol=signal.symbol, interval='1m',
    ).order_by('-timestamp').values_list('close', flat=True).first()

    if not latest:
        logger.warning(f"No price data for {signal.symbol}")
        return

    current_price = float(latest)
    side = 'LONG' if signal.bias == 'LONG' else 'SHORT'

    # Risk evaluation
    rm = RiskManager()
    approved, result = rm.evaluate_trade(signal.symbol, side, signal.tier, current_price)

    if not approved:
        logger.info(f"Trade rejected: {signal.symbol} — {result.get('reason', 'unknown')}")
        signal.action_taken = True
        signal.save()
        return

    # Execute based on mode
    mode = settings.TRADING_MODE

    if mode == 'paper':
        engine = PaperTradingEngine()
        engine.open_position(result, signal)
    elif mode == 'signal_only':
        logger.info(f"🔔 SIGNAL: {signal.symbol} {side} (signal_only mode)")
    elif mode in {'semi_auto', 'full_auto'}:
        if not settings.LIVE_TRADING_ENABLED:
            logger.warning("Live trading mode requested but LIVE_TRADING_ENABLED is false")
        elif not getattr(settings, 'EXCHANGE_SIDE_STOPS_IMPLEMENTED', False):
            # Fail closed: the adapter submits only the entry. Without a resting
            # stop on the exchange a crash would leave the position unprotected.
            logger.error("Live order refused: exchange-side stop orders are not implemented")
        else:
            from .exchange_adapters import get_exchange_adapter
            from .live_execution import submit_protected_entry
            adapter = get_exchange_adapter()
            # Deterministic id: a retried submit cannot open the position twice.
            exchange_result = submit_protected_entry(adapter, {
                **result,
                'client_oid': f'sentinel-{signal.id}',
            }, signal_ref=f'consensus:{signal.id}')
            logger.info(f"Live order submit {signal.symbol}: ok={exchange_result.ok} payload={exchange_result.payload}")
            if (not exchange_result.ok
                    and exchange_result.payload.get('manual_reconciliation_required')):
                from risk.trading_state import escalate
                escalate(
                    'HALT',
                    (
                        f'Order {exchange_result.payload.get("client_oid")} has an uncertain '
                        'exchange outcome; manual reconciliation is required.'
                    ),
                    by='executor', manual_unlock=True,
                )
    else:
        logger.info(f"Mode '{mode}' — no auto execution")

    signal.action_taken = True
    signal.save()


@shared_task(name='executor.monitor_positions')
def monitor_positions():
    """Check paper SL/TP only; exchange positions need exchange-side orders."""
    from .paper_engine import PaperTradingEngine
    from .models import Position
    engine = PaperTradingEngine()
    engine.check_positions()
    return {
        'paper_open': Position.objects.filter(
            status='OPEN', source__in=('paper', 'auto'),
        ).count(),
        'exchange_open_untouched': Position.objects.filter(
            status='OPEN', source='exchange',
        ).count(),
    }


@shared_task(name='executor.daily_reset')
def daily_reset():
    """Reset daily risk counters — runs at midnight UTC."""
    from risk.kill_switches import reset_daily
    reset_daily()
    logger.info("Daily risk counters reset")


@shared_task(name='executor.weekly_reset')
def weekly_reset():
    """Reset weekly risk counters — runs Monday midnight UTC."""
    from risk.kill_switches import reset_weekly
    reset_weekly()
    logger.info("Weekly risk counters reset")


@shared_task(name='executor.force_close_all')
def force_close_all():
    """Close paper positions and submit reduce-only closes for KuCoin mirrors.

    Exchange mirrors remain OPEN locally until the next exchange sync proves
    that the position is gone.  A failed close escalates to a manual HALT.
    """
    from django.conf import settings
    from .models import Position
    from .paper_engine import PaperTradingEngine

    open_positions = Position.objects.filter(
        status='OPEN', source__in=('paper', 'auto'),
    )
    exchange_positions = list(Position.objects.filter(status='OPEN', source='exchange'))
    exchange_open = len(exchange_positions)
    if not open_positions.exists() and not exchange_open:
        return {
            'closed': 0,
            'exchange_close_submitted': 0,
            'exchange_close_failed': 0,
            'exchange_open_untouched': 0,
        }

    engine = PaperTradingEngine()
    closed = 0
    for position in open_positions:
        try:
            engine._update_position_price(position)
            engine._close_position(position, float(position.current_price), 'EOD_FORCE_CLOSE')
            closed += 1
        except Exception as e:
            logger.error(f"Force close failed for {position.id}: {e}")

    logger.info(f"EOD force close: {closed} position(s) closed")
    submitted = 0
    failed = 0
    untouched = 0
    if exchange_open and settings.LIVE_TRADING_ENABLED:
        from .exchange_adapters import get_exchange_adapter

        adapter = get_exchange_adapter()
        for position in exchange_positions:
            result = adapter.close_position({
                'symbol': position.symbol,
                'side': position.side,
                'quantity': position.remaining_quantity or position.quantity,
                'leverage': position.leverage,
                'margin_mode': 'isolated',
                'client_oid': f'sentinel-eod-{position.id}',
            })
            if result.ok:
                from .live_execution import ACTIVE_INTENT_STATUSES
                from .models import ExchangeExecutionIntent

                ExchangeExecutionIntent.objects.filter(
                    symbol=position.symbol,
                    side=position.side,
                    status__in=ACTIVE_INTENT_STATUSES,
                ).update(status='CLOSING')
                submitted += 1
                logger.warning(
                    'EOD reduce-only close submitted for exchange position %s; awaiting sync',
                    position.id,
                )
            else:
                failed += 1
                logger.critical(
                    'EOD reduce-only close failed for exchange position %s: %s',
                    position.id,
                    result.payload,
                )
    elif exchange_open:
        untouched = exchange_open

    if failed or untouched:
        from risk.trading_state import escalate
        escalate(
            'HALT',
            (
                f'EOD could not close {failed + untouched} of {exchange_open} '
                'exchange position(s).'
            ),
            by='eod_watchdog', manual_unlock=True,
        )
        logger.critical(
            'EOD left %s exchange position(s) without an accepted close and halted new trading',
            failed + untouched,
        )
    return {
        'closed': closed,
        'exchange_close_submitted': submitted,
        'exchange_close_failed': failed,
        'exchange_open_untouched': untouched,
    }


@shared_task(name='executor.block_new_entries_eod')
def block_new_entries_eod():
    """Soft block: log warning that no new entries should be opened after 18:00 UTC."""
    from .models import Position
    open_count = Position.objects.filter(status='OPEN').count()
    logger.info(f"EOD soft block active (18:00 UTC) — {open_count} positions still open, no new entries")
    # Hard enforcement is in check_kill_switches via killzone gate A1 (off-session = no new entries)


@shared_task(name='executor.transfer_profit_reserve_to_spot')
def transfer_profit_reserve_to_spot(amount_usd: float | None = None):
    """Move only the configured share of profit above the capital baseline."""
    from django.conf import settings
    from django.db import transaction
    from .exchange_adapters import get_exchange_adapter
    from .models import AccountState

    if not settings.LIVE_TRADING_ENABLED:
        return {'ok': False, 'reason': 'live_trading_disabled'}

    with transaction.atomic():
        state = AccountState.objects.select_for_update().order_by('-updated_at').first()
        if not state:
            return {'ok': False, 'reason': 'missing_account_state'}

        reserve_ratio = min(max(float(getattr(settings, 'PROFIT_TO_SPOT_RATIO', 0.10)), 0.0), 1.0)
        capital_baseline = float(getattr(
            settings, 'LIVE_CAPITAL_BASELINE_USD', settings.INITIAL_BALANCE,
        ))
        already_reserved = max(float(state.spot_reserve_balance or 0.0), 0.0)
        profit_before_reserve = max(float(state.balance) + already_reserved - capital_baseline, 0.0)
        reserve_target = profit_before_reserve * reserve_ratio
        available = max(reserve_target - already_reserved, 0.0)
        requested = float(amount_usd) if amount_usd is not None else available
        if requested > available + 1e-9:
            return {
                'ok': False,
                'reason': 'amount_exceeds_unreserved_profit',
                'available_usd': round(available, 2),
            }
        transfer_amount = min(requested, available)
        if transfer_amount <= 0:
            return {'ok': False, 'reason': 'no_unreserved_profit'}

        adapter = get_exchange_adapter()
        result = adapter.transfer_profit_to_spot(transfer_amount)
        if result.ok:
            # Keep the local high-water accounting correct before the next sync.
            state.balance = max(float(state.balance) - transfer_amount, 0.0)
            state.spot_reserve_balance = already_reserved + transfer_amount
            state.save(update_fields=['balance', 'spot_reserve_balance', 'updated_at'])
    logger.info(f"Spot reserve transfer attempt: ok={result.ok} payload={result.payload}")
    return {'ok': result.ok, 'payload': result.payload, 'amount_usd': round(transfer_amount, 2)}


@shared_task(name='executor.sync_live_exchange_state')
def sync_live_exchange_state():
    """Fetch live futures account overview and open positions from the exchange."""
    from django.conf import settings
    from .exchange_adapters import get_exchange_adapter
    from .models import AccountState, Position, ExchangeOpenOrder, ExchangeFill, ExchangeClosedOrder

    if not settings.LIVE_TRADING_ENABLED:
        return {'ok': False, 'reason': 'live_trading_disabled'}

    adapter = get_exchange_adapter()
    overview = adapter.get_account_overview('USDT')
    positions = adapter.get_positions()
    open_orders = adapter.get_open_orders()
    stop_orders = adapter.get_stop_orders()
    fills = adapter.get_recent_fills()
    closed_orders = adapter.get_recent_closed_orders()
    normalized_regular_orders = adapter.normalize_open_orders(open_orders.payload) if open_orders.ok else []
    normalized_stop_orders = adapter.normalize_stop_orders(stop_orders.payload) if stop_orders.ok else []
    payload = {
        'overview_ok': overview.ok,
        'positions_ok': positions.ok,
        'orders_ok': open_orders.ok and stop_orders.ok,
        'regular_orders_ok': open_orders.ok,
        'stop_orders_ok': stop_orders.ok,
        'fills_ok': fills.ok,
        'closed_orders_ok': closed_orders.ok,
        'overview': overview.payload,
        'positions': positions.payload,
        'open_orders': open_orders.payload,
        'stop_orders': stop_orders.payload,
        'fills': fills.payload,
        'closed_orders': closed_orders.payload,
        'normalized_positions': adapter.normalize_positions(positions.payload) if positions.ok else [],
        'normalized_regular_orders': normalized_regular_orders,
        'normalized_stop_orders': normalized_stop_orders,
        'normalized_open_orders': normalized_regular_orders + normalized_stop_orders,
        'normalized_fills': adapter.normalize_recent_fills(fills.payload) if fills.ok else [],
        'normalized_closed_orders': adapter.normalize_recent_closed_orders(closed_orders.payload) if closed_orders.ok else [],
    }
    normalized_positions = payload['normalized_positions']
    if positions.ok:
        # Compare before mirroring: an unexplained difference halts trading.
        from .reconcile import (
            halt_on_mismatch,
            local_intended_positions,
            protective_stop_mismatches,
            reconcile,
        )
        from .live_execution import UNRESOLVED_INTENT_STATUSES
        from .models import ExchangeExecutionIntent
        pending_client_oids = {
            str(order.get('client_oid') or '')
            for order in normalized_regular_orders
            if order.get('client_oid')
        }
        mismatches = reconcile(
            local_intended_positions(), normalized_positions,
            pending_client_oids=pending_client_oids,
        )
        mismatches.extend(protective_stop_mismatches(
            normalized_positions,
            normalized_stop_orders,
            stop_orders_ok=stop_orders.ok,
        ))
        mismatches.extend({
            'symbol': intent.symbol,
            'issue': 'UNRESOLVED_EXECUTION_INTENT',
            'client_oid': intent.client_oid,
            'status': intent.status,
        } for intent in ExchangeExecutionIntent.objects.filter(
            status__in=UNRESOLVED_INTENT_STATUSES,
        ))
        payload['reconciliation'] = {'mismatches': mismatches,
                                     'halted': halt_on_mismatch(mismatches)}
    normalized_open_orders = payload['normalized_open_orders']
    normalized_fills = payload['normalized_fills']
    normalized_closed_orders = payload['normalized_closed_orders']
    if overview.ok:
        data = overview.payload.get('data', {}) if isinstance(overview.payload, dict) else {}
        balance = float(data.get('availableBalance') or 0.0)
        equity = float(data.get('accountEquity') or balance)
        unrealized = float(data.get('unrealisedPNL') or data.get('unrealizedPNL') or 0.0)
        state = AccountState.objects.order_by('-updated_at').first()
        if state is None:
            peak_equity = equity
            AccountState.objects.create(
                balance=balance,
                equity=equity,
                unrealized_pnl=unrealized,
                peak_equity=peak_equity,
            )
        else:
            state.balance = balance
            state.equity = equity
            state.unrealized_pnl = unrealized
            state.peak_equity = max(float(state.peak_equity or 0.0), equity)
            state.save(update_fields=['balance', 'equity', 'unrealized_pnl', 'peak_equity', 'updated_at'])

    if positions.ok:
        from .models import ExchangeExecutionIntent

        active_intents = list(ExchangeExecutionIntent.objects.filter(
            status__in=('PREPARED', 'ACCEPTED', 'UNCERTAIN', 'OPEN', 'CLOSING'),
        ))
        intents_by_key = {(intent.symbol, intent.side): intent for intent in active_intents}
        exchange_keys = {
            (pos['symbol'], pos['side'])
            for pos in normalized_positions
            if abs(float(pos.get('quantity_base') or 0.0)) > 0
        }
        for intent in active_intents:
            key = (intent.symbol, intent.side)
            if key in exchange_keys and intent.status == 'ACCEPTED':
                intent.status = 'OPEN'
                intent.save(update_fields=['status', 'updated_at'])
            elif intent.status == 'CLOSING' and key not in exchange_keys:
                intent.status = 'CLOSED'
                intent.save(update_fields=['status', 'updated_at'])

        active_keys = set()
        for pos in normalized_positions:
            key = (pos['symbol'], pos['side'])
            active_keys.add(key)
            intent = intents_by_key.get(key)
            entry_price = float(pos['entry_price'] or 0.0)
            mark_price = float(pos['mark_price'] or entry_price)
            placeholder_stop = entry_price if entry_price > 0 else mark_price
            defaults = {
                'status': 'OPEN',
                'entry_price': entry_price,
                'current_price': mark_price,
                'quantity': pos['quantity_base'],
                'remaining_quantity': pos['quantity_base'],
                'position_size_usd': pos['position_size_usd'],
                'leverage': pos['leverage'],
                'stop_loss': placeholder_stop,
                'take_profit_1': None,
                'take_profit_2': None,
                'take_profit_3': None,
                'margin_usd': 0.0,
                'unrealized_pnl': pos['unrealized_pnl'],
                'source': 'exchange',
                'strategy': intent.strategy if intent else 'LIVE',
                'consensus_signal_id': (
                    int(intent.signal_ref.split(':', 1)[1])
                    if intent and intent.signal_ref.startswith('consensus:')
                    and intent.signal_ref.split(':', 1)[1].isdigit()
                    else None
                ),
                'analyst_snapshot': ({'execution_intent': intent.client_oid} if intent else {}),
            }
            Position.objects.update_or_create(
                symbol=pos['symbol'],
                side=pos['side'],
                source='exchange',
                status='OPEN',
                defaults=defaults,
            )

        stale_qs = Position.objects.filter(source='exchange', status='OPEN')
        for local_pos in stale_qs:
            if (local_pos.symbol, local_pos.side) not in active_keys:
                local_pos.status = 'CANCELLED'
                local_pos.close_reason = 'EXCHANGE_SYNC_STALE'
                local_pos.save(update_fields=['status', 'close_reason'])

    if open_orders.ok and stop_orders.ok:
        active_order_ids = set()
        for order in normalized_open_orders:
            order_id = str(order.get('order_id') or '')
            if not order_id:
                continue
            active_order_ids.add(order_id)
            ExchangeOpenOrder.objects.update_or_create(
                order_id=order_id,
                defaults={
                    'client_oid': str(order.get('client_oid') or ''),
                    'symbol': order.get('symbol') or '',
                    'side': order.get('side') or 'LONG',
                    'order_type': str(order.get('order_type') or ''),
                    'price': float(order.get('price') or 0.0),
                    'size': float(order.get('size') or 0.0),
                    'status': str(order.get('status') or 'active'),
                    'source': 'exchange',
                },
            )

        stale_orders = ExchangeOpenOrder.objects.filter(source='exchange')
        for local_order in stale_orders:
            if local_order.order_id not in active_order_ids:
                local_order.status = 'stale'
                local_order.save(update_fields=['status', 'updated_at'])

    if fills.ok:
        for fill in normalized_fills:
            filled_at = datetime.fromtimestamp(fill['filled_at_ms'] / 1000, tz=timezone.utc) if fill.get('filled_at_ms') else datetime.now(timezone.utc)
            ExchangeFill.objects.update_or_create(
                trade_id=fill['trade_id'],
                defaults={
                    'order_id': fill.get('order_id', ''),
                    'symbol': fill.get('symbol') or '',
                    'side': fill.get('side') or 'LONG',
                    'price': float(fill.get('price') or 0.0),
                    'size': float(fill.get('size') or 0.0),
                    'value': float(fill.get('value') or 0.0),
                    'fee': float(fill.get('fee') or 0.0),
                    'pnl': float(fill.get('pnl') or 0.0),
                    'liquidity': str(fill.get('liquidity') or ''),
                    'source': 'exchange',
                    'filled_at': filled_at,
                },
            )
    if closed_orders.ok:
        for order in normalized_closed_orders:
            closed_at = datetime.fromtimestamp(order['closed_at_ms'] / 1000, tz=timezone.utc) if order.get('closed_at_ms') else datetime.now(timezone.utc)
            ExchangeClosedOrder.objects.update_or_create(
                order_id=order['order_id'],
                defaults={
                    'client_oid': order.get('client_oid', ''),
                    'symbol': order.get('symbol') or '',
                    'side': order.get('side') or 'LONG',
                    'order_type': str(order.get('order_type') or ''),
                    'price': float(order.get('price') or 0.0),
                    'size': float(order.get('size') or 0.0),
                    'filled_size': float(order.get('filled_size') or 0.0),
                    'status': str(order.get('status') or 'done'),
                    'cancel_reason': str(order.get('cancel_reason') or ''),
                    'source': 'exchange',
                    'closed_at': closed_at,
                },
            )
    logger.info(
        "Live exchange sync: overview_ok=%s positions_ok=%s orders_ok=%s stop_orders_ok=%s fills_ok=%s closed_orders_ok=%s",
        overview.ok,
        positions.ok,
        open_orders.ok,
        stop_orders.ok,
        fills.ok,
        closed_orders.ok,
    )
    critical_reads = {
        'account': overview.ok,
        'positions': positions.ok,
        'orders': open_orders.ok,
        'stop_orders': stop_orders.ok,
    }
    critical_failures = [name for name, ok in critical_reads.items() if not ok]
    payload['critical_read_failures'] = critical_failures
    if critical_failures:
        # No new exposure is allowed when the supervisor cannot prove the
        # current account, position and protection state. Recovery is manual:
        # run the read-only preflight first, then release through the CLI.
        from risk.trading_state import escalate
        escalate(
            'CLOSE_ONLY',
            'Exchange visibility lost: ' + ', '.join(critical_failures),
            by='executor',
            manual_unlock=True,
        )
    return {
        'ok': (
            overview.ok and positions.ok and open_orders.ok and stop_orders.ok
            and fills.ok and closed_orders.ok
        ),
        'payload': payload,
    }
