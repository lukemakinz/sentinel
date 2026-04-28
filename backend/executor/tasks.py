"""Celery tasks for trade execution and position monitoring."""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='executor.process_signal')
def process_signal(consensus_signal_id):
    """Process a consensus signal through risk manager and potentially execute."""
    from consensus.models import ConsensusSignal
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
        else:
            from .exchange_adapters import get_exchange_adapter
            adapter = get_exchange_adapter()
            exchange_result = adapter.place_order(result)
            logger.info(f"Live order submit {signal.symbol}: ok={exchange_result.ok} payload={exchange_result.payload}")
    else:
        logger.info(f"Mode '{mode}' — no auto execution")

    signal.action_taken = True
    signal.save()


@shared_task(name='executor.monitor_positions')
def monitor_positions():
    """Check open positions for SL/TP hits — runs every 30 seconds."""
    from .paper_engine import PaperTradingEngine
    engine = PaperTradingEngine()
    engine.check_positions()


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
    """Force close ALL open positions at 22:00 UTC — no overnight positions."""
    from .models import Position
    from .paper_engine import PaperTradingEngine
    from django.utils import timezone

    open_positions = Position.objects.filter(status='OPEN')
    if not open_positions.exists():
        return {'closed': 0}

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
    return {'closed': closed}


@shared_task(name='executor.block_new_entries_eod')
def block_new_entries_eod():
    """Soft block: log warning that no new entries should be opened after 18:00 UTC."""
    from .models import Position
    open_count = Position.objects.filter(status='OPEN').count()
    logger.info(f"EOD soft block active (18:00 UTC) — {open_count} positions still open, no new entries")
    # Hard enforcement is in check_kill_switches via killzone gate A1 (off-session = no new entries)


@shared_task(name='executor.transfer_profit_reserve_to_spot')
def transfer_profit_reserve_to_spot(amount_usd: float | None = None):
    """Attempt to move a reserve slice of profits to spot on the live exchange."""
    from django.conf import settings
    from .exchange_adapters import get_exchange_adapter
    from .models import AccountState

    if not settings.LIVE_TRADING_ENABLED:
        return {'ok': False, 'reason': 'live_trading_disabled'}

    state = AccountState.objects.first()
    if not state:
        return {'ok': False, 'reason': 'missing_account_state'}

    reserve_ratio = float(getattr(settings, 'PROFIT_TO_SPOT_RATIO', 0.10))
    transfer_amount = float(amount_usd) if amount_usd is not None else max(state.balance * reserve_ratio, 0.0)
    if transfer_amount <= 0:
        return {'ok': False, 'reason': 'non_positive_transfer_amount'}

    adapter = get_exchange_adapter()
    result = adapter.transfer_profit_to_spot(transfer_amount)
    logger.info(f"Spot reserve transfer attempt: ok={result.ok} payload={result.payload}")
    return {'ok': result.ok, 'payload': result.payload, 'amount_usd': round(transfer_amount, 2)}


@shared_task(name='executor.sync_live_exchange_state')
def sync_live_exchange_state():
    """Fetch live futures account overview and open positions from the exchange."""
    from django.conf import settings
    from .exchange_adapters import get_exchange_adapter
    from .models import AccountState, Position, ExchangeOpenOrder

    if not settings.LIVE_TRADING_ENABLED:
        return {'ok': False, 'reason': 'live_trading_disabled'}

    adapter = get_exchange_adapter()
    overview = adapter.get_account_overview('USDT')
    positions = adapter.get_positions()
    open_orders = adapter.get_open_orders()
    payload = {
        'overview_ok': overview.ok,
        'positions_ok': positions.ok,
        'orders_ok': open_orders.ok,
        'overview': overview.payload,
        'positions': positions.payload,
        'open_orders': open_orders.payload,
        'normalized_positions': adapter.normalize_positions(positions.payload) if positions.ok else [],
        'normalized_open_orders': adapter.normalize_open_orders(open_orders.payload) if open_orders.ok else [],
    }
    normalized_positions = payload['normalized_positions']
    normalized_open_orders = payload['normalized_open_orders']
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
        active_keys = set()
        for pos in normalized_positions:
            key = (pos['symbol'], pos['side'])
            active_keys.add(key)
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
                'strategy': 'LIVE',
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

    if open_orders.ok:
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
    logger.info(
        "Live exchange sync: overview_ok=%s positions_ok=%s orders_ok=%s",
        overview.ok,
        positions.ok,
        open_orders.ok,
    )
    return {'ok': overview.ok and positions.ok and open_orders.ok, 'payload': payload}
