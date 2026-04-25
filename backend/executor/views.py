"""Executor API views — manual position entry, live monitoring, AI evaluation."""
import logging
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Position

logger = logging.getLogger(__name__)

MAINTENANCE_MARGIN = 0.005  # 0.5% — standard Binance futures


def _compute_live_adx(symbol: str) -> float:
    """Compute real ADX from last 60 1h candles. Falls back to 25.0 if insufficient data."""
    try:
        from ingester.models import Candle
        from l1_filter.utils import compute_adx
        candles = list(
            Candle.objects.filter(symbol=symbol, interval='1h', is_closed=True)
            .order_by('-timestamp')[:60]
            .values('open', 'high', 'low', 'close', 'volume')
        )
        if len(candles) < 29:
            return 25.0
        candle_dicts = [{'open': float(c['open']), 'high': float(c['high']),
                         'low': float(c['low']), 'close': float(c['close']),
                         'volume': float(c['volume'])} for c in reversed(candles)]
        return round(compute_adx(candle_dicts), 2)
    except Exception:
        return 25.0


# ── Pure computation helpers (testable without DB) ──────────────────────────

def compute_liquidation_price(side: str, entry_price: float, leverage: int) -> float:
    """Simplified isolated-margin liquidation price."""
    if leverage <= 0:
        return 0.0
    if side == 'LONG':
        return entry_price * (1 - 1 / leverage + MAINTENANCE_MARGIN)
    return entry_price * (1 + 1 / leverage - MAINTENANCE_MARGIN)


def compute_live_pnl(side: str, entry_price: float, current_price: float,
                     quantity: float, margin_usd: float,
                     stop_loss: float = None, take_profit_1: float = None,
                     liquidation_price: float = None) -> dict:
    """Compute all live metrics for a position."""
    if side == 'LONG':
        pnl_usd = (current_price - entry_price) * quantity
    else:
        pnl_usd = (entry_price - current_price) * quantity

    pnl_pct_margin = (pnl_usd / margin_usd * 100) if margin_usd > 0 else 0.0

    # Progress toward TP1 (0% = at entry, 100% = at TP1, negative = moving toward SL)
    sl_progress_pct = 0.0
    if stop_loss and take_profit_1:
        total_range = abs(take_profit_1 - entry_price)
        if total_range > 0:
            if side == 'LONG':
                sl_progress_pct = (current_price - entry_price) / total_range * 100
            else:
                sl_progress_pct = (entry_price - current_price) / total_range * 100
            sl_progress_pct = max(-100, min(100, sl_progress_pct))

    # Distance to liquidation
    liq_distance_pct = 0.0
    if liquidation_price:
        if side == 'LONG':
            liq_distance_pct = (current_price - liquidation_price) / current_price * 100
        else:
            liq_distance_pct = (liquidation_price - current_price) / current_price * 100

    return {
        'pnl_usd':           round(pnl_usd, 2),
        'pnl_pct_margin':    round(pnl_pct_margin, 2),
        'sl_progress_pct':   round(sl_progress_pct, 1),
        'liq_distance_pct':  round(liq_distance_pct, 2),
    }


# ── API Views ────────────────────────────────────────────────────────────────

@api_view(['POST'])
def manual_position_open(request):
    """Manually enter a live trade for monitoring."""
    d = request.data
    symbol    = d.get('symbol', 'BTCUSDT')
    side      = d.get('side', 'LONG')
    entry     = float(d.get('entry_price', 0))
    leverage  = int(d.get('leverage', 1))
    margin    = float(d.get('margin_usd', 100))
    sl        = float(d.get('stop_loss', 0)) or None
    tp1       = float(d.get('take_profit_1', 0)) or None
    tp2       = float(d.get('take_profit_2', 0)) or None

    if entry <= 0 or margin <= 0:
        return Response({'error': 'entry_price and margin_usd are required'}, status=400)

    quantity         = (margin * leverage) / entry
    position_size    = margin * leverage
    liq_price        = compute_liquidation_price(side, entry, leverage)

    position = Position.objects.create(
        symbol=symbol, side=side, status='OPEN',
        entry_price=entry, current_price=entry,
        quantity=quantity, remaining_quantity=quantity,
        position_size_usd=position_size,
        leverage=leverage,
        margin_usd=margin,
        stop_loss=sl or (entry * 0.97 if side == 'LONG' else entry * 1.03),
        take_profit_1=tp1,
        take_profit_2=tp2,
        liquidation_price=liq_price,
        source='manual',
    )

    return Response({
        'id': position.id,
        'symbol': symbol,
        'side': side,
        'entry_price': entry,
        'quantity': round(quantity, 6),
        'position_size_usd': position_size,
        'liquidation_price': round(liq_price, 2),
        'margin_usd': margin,
        'leverage': leverage,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def position_live(request, position_id):
    """Live monitoring data for a position — poll every 30s."""
    try:
        pos = Position.objects.get(pk=position_id, status='OPEN')
    except Position.DoesNotExist:
        return Response({'error': 'Position not found or closed'}, status=404)

    # Get current price
    from ingester.models import Candle
    latest = Candle.objects.filter(symbol=pos.symbol, interval='1m').order_by('-timestamp').first()
    current_price = float(latest.close) if latest else pos.entry_price

    margin = pos.margin_usd or pos.position_size_usd
    live   = compute_live_pnl(
        side=pos.side,
        entry_price=pos.entry_price,
        current_price=current_price,
        quantity=pos.remaining_quantity,
        margin_usd=margin,
        stop_loss=pos.stop_loss,
        take_profit_1=pos.take_profit_1,
        liquidation_price=pos.liquidation_price,
    )

    age_minutes = int((timezone.now() - pos.opened_at).total_seconds() / 60)

    return Response({
        'id': pos.id,
        'symbol': pos.symbol,
        'side': pos.side,
        'entry_price': pos.entry_price,
        'current_price': current_price,
        'stop_loss': pos.stop_loss,
        'take_profit_1': pos.take_profit_1,
        'take_profit_2': pos.take_profit_2,
        'liquidation_price': pos.liquidation_price,
        'leverage': pos.leverage,
        'margin_usd': margin,
        'position_size_usd': pos.position_size_usd,
        'age_minutes': age_minutes,
        'tp1_hit': pos.tp1_hit,
        'tp2_hit': pos.tp2_hit,
        **live,
    })


@api_view(['POST'])
def position_evaluate(request, position_id):
    """On-demand AI evaluation of current position quality."""
    try:
        pos = Position.objects.get(pk=position_id, status='OPEN')
    except Position.DoesNotExist:
        return Response({'error': 'Position not found'}, status=404)

    from django.conf import settings
    if not settings.ANTHROPIC_API_KEY:
        return Response({'error': 'ANTHROPIC_API_KEY not configured'}, status=503)

    # Build TradeContext from current market data
    from ingester.models import Candle, FundingRate
    latest_candle = Candle.objects.filter(symbol=pos.symbol, interval='1h').order_by('-timestamp').first()
    latest_funding = FundingRate.objects.filter(symbol=pos.symbol).order_by('-timestamp').first()

    current_price = float(latest_candle.close) if latest_candle else pos.entry_price
    margin = pos.margin_usd or pos.position_size_usd
    live   = compute_live_pnl(pos.side, pos.entry_price, current_price,
                               pos.remaining_quantity, margin, pos.stop_loss, pos.take_profit_1)

    trade_context = {
        'symbol':        pos.symbol,
        'direction':     pos.side,
        'timestamp':     timezone.now().isoformat(),
        'atr':           float(latest_candle.high - latest_candle.low) if latest_candle else 0,
        'funding_rate':  float(latest_funding.funding_rate) if latest_funding else 0,
        'adx_value':     _compute_live_adx(pos.symbol),
        'current_pnl':   live['pnl_pct_margin'],
        'age_minutes':   int((timezone.now() - pos.opened_at).total_seconds() / 60),
        'sl_progress':   live['sl_progress_pct'],
        'liq_distance':  live['liq_distance_pct'],
        'leverage':      pos.leverage,
    }

    try:
        from l2_agents.orchestrator import L2Orchestrator
        decision = L2Orchestrator().run(trade_context)
        return Response({
            'action':          decision.get('action'),
            'size_multiplier': decision.get('size_multiplier'),
            'agents_summary':  decision.get('agents_summary', {}),
            'recommendation':  _make_recommendation(decision, live),
            'evaluated_at':    timezone.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Evaluate error: {e}", exc_info=True)
        return Response({'error': str(e)}, status=500)


def _make_recommendation(decision: dict, live: dict) -> str:
    action  = decision.get('action')
    pnl_pct = live.get('pnl_pct_margin', 0)

    if action == 'REJECT':
        veto = decision.get('veto_reason', '')
        if veto == 'risk_manager':
            return 'CUT — Risk Manager veto: close position'
        if pnl_pct > 0:
            return 'CONSIDER CLOSING — Take partial profit, conditions degraded'
        return 'CUT — Setup conditions no longer valid'

    mult = decision.get('size_multiplier', 1.0)
    if action == 'APPROVE':
        if mult == 1.0:
            return 'HOLD — Setup still valid, full conviction'
        if mult >= 0.75:
            return 'HOLD — Setup valid with slight caution'
        return 'HOLD (reduced conviction) — Consider tightening SL'

    return 'HOLD — Monitor closely'
