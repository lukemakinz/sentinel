"""Prospective, trigger-aware resolution of auction plans in shadow only."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def _match_zone(entry_zone: list[float], snapshot: dict) -> dict | None:
    if not entry_zone or len(entry_zone) != 2:
        return None
    low, high = sorted(float(value) for value in entry_zone)
    for zone in snapshot.get('zones') or []:
        zone_low = float(zone['low'])
        zone_high = float(zone['high'])
        tolerance = max(abs(zone_low), abs(zone_high), 1.0) * 1e-8
        if abs(low - zone_low) <= tolerance and abs(high - zone_high) <= tolerance:
            return zone
    return None


def create_shadow_plan(analysis):
    """Convert a validated ``ARM`` into deterministic, non-executable geometry."""
    from .models import AuctionShadowPlan

    if analysis.action != 'ARM':
        return None
    existing = AuctionShadowPlan.objects.filter(analysis=analysis).first()
    if existing is not None:
        return existing

    decision = analysis.decision
    snapshot = analysis.snapshot
    zone = _match_zone(decision.get('entry_zone'), snapshot)
    if zone is None:
        raise ValueError('ARM entry zone must match a supplied snapshot zone')

    zone_low = float(zone['low'])
    zone_high = float(zone['high'])
    reference = (zone_low + zone_high) / 2.0
    atr = float(snapshot.get('instrument', {}).get('15m', {}).get('atr14') or 0.0)
    if atr <= 0:
        raise ValueError('ARM requires a positive 15m ATR')
    buffer_price = max(atr * 0.15, reference * 0.0005)
    direction = decision['direction']
    structural_stop = (
        zone_low - buffer_price if direction == 'LONG'
        else zone_high + buffer_price
    )
    ttl_minutes = int(decision.get('ttl_minutes') or 0)
    if ttl_minutes <= 0:
        raise ValueError('ARM requires a positive TTL')

    costs = {
        'entry_taker_fee_bps': float(getattr(settings, 'PAPER_TAKER_FEE_BPS', 5)),
        'target_maker_fee_bps': float(getattr(settings, 'PAPER_MAKER_FEE_BPS', 2)),
        'stop_taker_fee_bps': float(getattr(settings, 'PAPER_TAKER_FEE_BPS', 5)),
        'market_slippage_bps': float(getattr(settings, 'PAPER_MARKET_SLIPPAGE_BPS', 5)),
        'same_bar_policy': 'STOP_FIRST',
        'trigger_timeframe': '1m_closed',
    }
    return AuctionShadowPlan.objects.create(
        analysis=analysis,
        symbol=analysis.symbol,
        strategy_id=analysis.strategy_id,
        direction=direction,
        zone_kind=zone.get('kind') or 'UNKNOWN',
        zone_low=zone_low,
        zone_high=zone_high,
        structural_stop=structural_stop,
        target_r=float(getattr(settings, 'AUCTION_SHADOW_TARGET_R', 1.5)),
        management_policy=decision['management_policy'],
        armed_at=analysis.timestamp,
        expires_at=analysis.timestamp + timedelta(minutes=ttl_minutes),
        cost_assumptions=costs,
    )


def _adverse_market_fill(price: float, direction: str, *, entry: bool,
                         slippage_bps: float) -> float:
    slip = slippage_bps / 10_000.0
    if direction == 'LONG':
        return price * (1.0 + slip if entry else 1.0 - slip)
    return price * (1.0 - slip if entry else 1.0 + slip)


def _triggered(plan, row: dict) -> bool:
    low, high = float(row['low']), float(row['high'])
    opened, close = float(row['open']), float(row['close'])
    touched = low <= plan.zone_high and high >= plan.zone_low
    if plan.strategy_id == 'SAI1_FAILED_AUCTION':
        return (
            low < plan.zone_low and close > plan.zone_high
            if plan.direction == 'LONG'
            else high > plan.zone_high and close < plan.zone_low
        )
    if plan.strategy_id in {'SAI1_IFVG_FLIP', 'SAI1_TREND_RETEST'}:
        return touched and (
            close > plan.zone_high and close > opened
            if plan.direction == 'LONG'
            else close < plan.zone_low and close < opened
        )
    return False


def _pre_invalidated(plan, row: dict) -> bool:
    close = float(row['close'])
    return (
        close <= plan.structural_stop
        if plan.direction == 'LONG'
        else close >= plan.structural_stop
    )


def _close_plan(plan, row: dict, reason: str, raw_exit: float, fee_bps: float):
    costs = plan.cost_assumptions
    slippage = float(costs['market_slippage_bps']) if reason != 'TARGET' else 0.0
    exit_price = _adverse_market_fill(
        raw_exit, plan.direction, entry=False, slippage_bps=slippage,
    ) if slippage else raw_exit
    risk = abs(plan.entry_price - plan.structural_stop)
    gross = (
        (exit_price - plan.entry_price) / risk
        if plan.direction == 'LONG'
        else (plan.entry_price - exit_price) / risk
    )
    fee_cost = (
        plan.entry_price * float(costs['entry_taker_fee_bps']) / 10_000.0
        + exit_price * fee_bps / 10_000.0
    ) / risk
    plan.state = 'CLOSED'
    plan.closed_at = row['timestamp']
    plan.exit_price = exit_price
    plan.exit_reason = reason
    plan.gross_r = round(gross, 6)
    plan.net_r = round(gross - fee_cost, 6)
    plan.save(update_fields=[
        'state', 'closed_at', 'exit_price', 'exit_reason', 'gross_r', 'net_r',
        'mfe_r', 'mae_r',
    ])


def resolve_plan(plan, now=None) -> str:
    """Advance one plan using only closed 1m candles already in the database."""
    from ingester.models import Candle

    now = now or timezone.now()
    rows = list(Candle.objects.filter(
        symbol=plan.symbol,
        interval='1m',
        is_closed=True,
        timestamp__gte=plan.armed_at,
        timestamp__lt=min(now, plan.expires_at),
    ).order_by('timestamp').values('timestamp', 'open', 'high', 'low', 'close'))
    if not rows:
        return 'NO_DATA'

    if plan.state == 'ARMED':
        for row in rows:
            if _pre_invalidated(plan, row):
                plan.state = 'INVALID'
                plan.closed_at = row['timestamp']
                plan.exit_reason = 'PRE_INVALIDATION'
                plan.trigger_evidence = {'candle': {k: str(v) for k, v in row.items()}}
                plan.save(update_fields=[
                    'state', 'closed_at', 'exit_reason', 'trigger_evidence',
                ])
                return 'INVALID'
            if _triggered(plan, row):
                slippage = float(plan.cost_assumptions['market_slippage_bps'])
                entry = _adverse_market_fill(
                    float(row['close']), plan.direction, entry=True,
                    slippage_bps=slippage,
                )
                risk = abs(entry - plan.structural_stop)
                if risk <= 0:
                    plan.state = 'INVALID'
                    plan.closed_at = row['timestamp']
                    plan.exit_reason = 'PRE_INVALIDATION'
                    plan.save(update_fields=['state', 'closed_at', 'exit_reason'])
                    return 'INVALID'
                plan.state = 'TRIGGERED'
                plan.triggered_at = row['timestamp']
                plan.entry_price = entry
                plan.target_price = (
                    entry + risk * plan.target_r
                    if plan.direction == 'LONG'
                    else entry - risk * plan.target_r
                )
                plan.mfe_r = 0.0
                plan.mae_r = 0.0
                plan.trigger_evidence = {'candle': {k: str(v) for k, v in row.items()}}
                plan.save(update_fields=[
                    'state', 'triggered_at', 'entry_price', 'target_price',
                    'mfe_r', 'mae_r', 'trigger_evidence',
                ])
                break

    if plan.state == 'TRIGGERED':
        risk = abs(plan.entry_price - plan.structural_stop)
        future_rows = [row for row in rows if row['timestamp'] > plan.triggered_at]
        for row in future_rows:
            high, low = float(row['high']), float(row['low'])
            if plan.direction == 'LONG':
                favorable = (high - plan.entry_price) / risk
                adverse = (low - plan.entry_price) / risk
                stop_touched = low <= plan.structural_stop
                target_touched = high >= plan.target_price
            else:
                favorable = (plan.entry_price - low) / risk
                adverse = (plan.entry_price - high) / risk
                stop_touched = high >= plan.structural_stop
                target_touched = low <= plan.target_price
            plan.mfe_r = max(float(plan.mfe_r or 0.0), favorable)
            plan.mae_r = min(float(plan.mae_r or 0.0), adverse)
            if stop_touched:
                _close_plan(
                    plan, row, 'STOP', plan.structural_stop,
                    float(plan.cost_assumptions['stop_taker_fee_bps']),
                )
                return 'CLOSED'
            if target_touched:
                _close_plan(
                    plan, row, 'TARGET', plan.target_price,
                    float(plan.cost_assumptions['target_maker_fee_bps']),
                )
                return 'CLOSED'
        if future_rows:
            plan.save(update_fields=['mfe_r', 'mae_r'])

    if now < plan.expires_at:
        return plan.state

    # Do not manufacture an expiry outcome when candle coverage is stale.
    if rows[-1]['timestamp'] < plan.expires_at - timedelta(minutes=2):
        return 'INCOMPLETE_DATA'
    if plan.state == 'ARMED':
        plan.state = 'EXPIRED'
        plan.closed_at = plan.expires_at
        plan.exit_reason = 'NO_TRIGGER'
        plan.save(update_fields=['state', 'closed_at', 'exit_reason'])
        return 'EXPIRED'
    if plan.state == 'TRIGGERED':
        row = rows[-1]
        _close_plan(
            plan, row, 'TIME', float(row['close']),
            float(plan.cost_assumptions['stop_taker_fee_bps']),
        )
        return 'CLOSED'
    return plan.state


def resolve_open_plans(now=None) -> dict:
    from .models import AuctionShadowPlan

    counts: dict[str, int] = {}
    for plan in AuctionShadowPlan.objects.filter(
        state__in=('ARMED', 'TRIGGERED'),
    ).order_by('armed_at').iterator():
        result = resolve_plan(plan, now=now)
        counts[result] = counts.get(result, 0) + 1
    return counts
