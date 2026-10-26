"""FCM_SAFE25 paper-forward monitor: public data, zero order placement."""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from backtest.fcm_safe25 import safe25_configs
from backtest.funding_carry_v2 import _trend_snapshot, executable_hedge_quantity

from .live_prices import (
    funding_score_bps,
    get_completed_daily_spot_closes,
    get_funding_settlements,
    get_last_closed_mark_high,
    get_perp_price,
    get_spot_price,
)
from .models import CarryDecisionLog, CarryEpisode

logger = logging.getLogger(__name__)

SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
STRATEGY = 'FCM_SAFE25'
PROTOCOL_SHA256 = 'ca4b236e2f33e69ccc0989ae53316f82ae254bff8f0478e16925a98c34f9ce2e'
CONFIGS = safe25_configs()
BASE_CONFIG = CONFIGS['base']
STRESS_CONFIG = CONFIGS['stress']
SEVERE_CONFIG = CONFIGS['severe']


def _previous_month_bounds(now):
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_start = (month_start - timezone.timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    return previous_month_start, month_start


def _live_features(symbol, previous_month_start, month_start) -> dict:
    spot = get_completed_daily_spot_closes(symbol, month_start)
    trend = _trend_snapshot(spot, month_start, BASE_CONFIG)
    funding = funding_score_bps(symbol, previous_month_start, month_start)
    qualified = (
        funding >= BASE_CONFIG.qualification_funding_bps
        and trend['return_30d_pct'] > 0
        and trend['close'] > trend['ema50']
    )
    return {
        'feature_cutoff': str(trend['feature_cutoff']),
        'close': trend['close'],
        'ema50': trend['ema50'],
        'return_30d_pct': trend['return_30d_pct'],
        'prior_month_funding_bps': funding,
        'qualified': qualified,
    }


def _estimated_costs(episode: CarryEpisode, spot_exit: float,
                     perp_exit: float, config) -> float:
    quantity = episode.quantity
    costs = config.costs
    return quantity / 10_000 * (
        episode.spot_entry_price
        * (costs.spot_fee_bps + costs.spot_slippage_bps)
        + episode.perp_entry_price
        * (costs.futures_fee_bps + costs.futures_slippage_bps)
        + spot_exit * (costs.spot_fee_bps + costs.spot_slippage_bps)
        + perp_exit * (costs.futures_fee_bps + costs.futures_slippage_bps)
    )


def _book_funding(episode: CarryEpisode, now) -> tuple[float, int]:
    since = episode.last_funding_accrued_at or episode.opened_at
    if since >= now:
        return 0.0, 0
    settlements = [
        row for row in get_funding_settlements(episode.symbol, since, now)
        if since < row['time'] < now
    ]
    payments = [
        row['rate'] * row['mark_price'] * episode.quantity
        for row in settlements
    ]
    payment = sum(payments)
    episode.funding_accrued_usd += payment
    episode.adverse_funding_usd += sum(min(value, 0.0) for value in payments)
    update_fields = ['funding_accrued_usd', 'adverse_funding_usd']
    if settlements:
        # Advance only to an observed settlement, not wall-clock time. This
        # keeps a delayed exchange response from making a settlement vanish.
        episode.last_funding_accrued_at = max(
            row['time'] for row in settlements)
        update_fields.append('last_funding_accrued_at')
    episode.save(update_fields=update_fields)
    return payment, len(settlements)


def _open_episode(symbol: str, now, features: dict, reason: str) -> CarryEpisode:
    spot_price = get_spot_price(symbol)
    perp_price = get_perp_price(symbol)
    sizing_spot = spot_price * (
        1 + STRESS_CONFIG.costs.spot_slippage_bps / 10_000)
    sizing_perp = perp_price * (
        1 - STRESS_CONFIG.costs.futures_slippage_bps / 10_000)
    hedge = executable_hedge_quantity(
        symbol, sizing_spot, sizing_perp, STRESS_CONFIG)
    quantity = hedge['quantity']
    initial_entry_fee = (
        quantity * sizing_perp
        * STRESS_CONFIG.costs.futures_fee_bps / 10_000)
    initial_equity = STRESS_CONFIG.futures_margin_usd - initial_entry_fee
    episode = CarryEpisode.objects.create(
        strategy=STRATEGY,
        protocol_sha256=PROTOCOL_SHA256,
        symbol=symbol,
        status='OPEN',
        opened_at=now,
        spot_entry_price=spot_price,
        perp_entry_price=perp_price,
        notional_usd=quantity * spot_price,
        quantity=quantity,
        futures_margin_usd=STRESS_CONFIG.futures_margin_usd,
        reserve_usd=(
            250.0 - quantity * spot_price
            - STRESS_CONFIG.futures_margin_usd - initial_entry_fee),
        qualifying_funding_bps=features['prior_month_funding_bps'],
        entry_reason=reason,
        last_funding_accrued_at=now,
        min_futures_equity_usd=initial_equity,
        max_mark_leverage=quantity * perp_price / initial_equity,
    )
    logger.info(
        'SAFE25 paper OPEN: %s qty=%.8f spot=%.4f perp=%.4f (%s)',
        symbol, quantity, spot_price, perp_price, reason)
    return episode


def _close_episode(episode: CarryEpisode, now, reason: str) -> None:
    _book_funding(episode, now)
    spot_price = get_spot_price(episode.symbol)
    perp_price = get_perp_price(episode.symbol)
    spot_pnl = (spot_price - episode.spot_entry_price) * episode.quantity
    perp_pnl = (episode.perp_entry_price - perp_price) * episode.quantity
    raw_pnl = episode.funding_accrued_usd + spot_pnl + perp_pnl
    base_costs = _estimated_costs(episode, spot_price, perp_price, BASE_CONFIG)
    stress_costs = _estimated_costs(
        episode, spot_price, perp_price, STRESS_CONFIG)
    severe_costs = _estimated_costs(
        episode, spot_price, perp_price, SEVERE_CONFIG)

    episode.status = 'CLOSED'
    episode.closed_at = now
    episode.spot_exit_price = spot_price
    episode.perp_exit_price = perp_price
    episode.exit_reason = reason
    episode.estimated_costs_usd = base_costs
    episode.realized_pnl_usd = raw_pnl - base_costs
    episode.stress_costs_usd = stress_costs
    episode.stress_pnl_usd = raw_pnl - stress_costs
    episode.severe_costs_usd = severe_costs
    episode.severe_pnl_usd = raw_pnl - severe_costs
    episode.save()
    logger.info(
        'SAFE25 paper CLOSE: %s stress_pnl=%+.4f (%s)',
        episode.symbol, episode.stress_pnl_usd, reason)


@shared_task(name='carry_monitor.evaluate_monthly_decision')
@transaction.atomic
def evaluate_monthly_decision() -> dict:
    """Run the frozen decision at 01:00 UTC and force a monthly reset."""
    now = timezone.now()
    previous_month_start, month_start = _previous_month_bounds(now)
    prior = CarryDecisionLog.objects.filter(
        strategy=STRATEGY, decision_time=month_start).first()
    if prior is not None:
        return {
            'action': 'already_evaluated',
            'previous': prior.previous_symbol or None,
            'target': prior.target_symbol or None,
            'scores_bps': prior.scores_bps,
        }

    features = {
        symbol: _live_features(symbol, previous_month_start, month_start)
        for symbol in SYMBOLS
    }
    qualified = [
        symbol for symbol in SYMBOLS if features[symbol]['qualified']]
    target = max(
        qualified,
        key=lambda symbol: (features[symbol]['prior_month_funding_bps'], symbol),
        default=None,
    )
    open_episode = CarryEpisode.objects.select_for_update().filter(
        strategy=STRATEGY, status='OPEN').order_by('-opened_at').first()
    current = open_episode.symbol if open_episode else None
    if target is None:
        reason = 'cash_no_qualified_asset'
    elif target == current:
        reason = 'monthly_reset_same_asset'
    elif current is None:
        reason = 'enter_highest_funding'
    else:
        reason = 'switch_highest_funding'

    CarryDecisionLog.objects.create(
        strategy=STRATEGY,
        protocol_sha256=PROTOCOL_SHA256,
        decision_time=month_start,
        previous_symbol=current or '',
        target_symbol=target or '',
        reason=reason,
        scores_bps={
            symbol: row['prior_month_funding_bps']
            for symbol, row in features.items()
        },
        features=features,
    )
    if open_episode is not None:
        _close_episode(open_episode, now, reason)
    if target is not None:
        _open_episode(target, now, features[target], reason)

    logger.info(
        'SAFE25 paper decision: %s (held=%s target=%s)',
        reason, current, target)
    return {
        'action': reason,
        'previous': current,
        'target': target,
        'scores_bps': {
            symbol: row['prior_month_funding_bps']
            for symbol, row in features.items()
        },
    }


@shared_task(name='carry_monitor.accrue_funding')
@transaction.atomic
def accrue_funding() -> dict:
    episode = CarryEpisode.objects.select_for_update().filter(
        strategy=STRATEGY, status='OPEN').order_by('-opened_at').first()
    if episode is None:
        return {'accrued_usd': 0.0, 'settlements': 0}
    payment, settlements = _book_funding(episode, timezone.now())
    if settlements:
        logger.info(
            'SAFE25 paper funding: %s %+.4f (%d settlement(s))',
            episode.symbol, payment, settlements)
    return {'accrued_usd': payment, 'settlements': settlements}


@shared_task(name='carry_monitor.monitor_safety')
@transaction.atomic
def monitor_safety() -> dict:
    """Check the last closed 1m mark high and simulate a causal unwind."""
    episode = CarryEpisode.objects.select_for_update().filter(
        strategy=STRATEGY, status='OPEN').order_by('-opened_at').first()
    if episode is None:
        return {'action': 'flat'}
    now = timezone.now()
    _book_funding(episode, now)
    bar_time, mark_high = get_last_closed_mark_high(episode.symbol, now)
    if (episode.last_safety_checked_at is not None
            and bar_time <= episode.last_safety_checked_at):
        return {'action': 'already_checked', 'bar_time': bar_time.isoformat()}

    entry_fill = episode.perp_entry_price * (
        1 - STRESS_CONFIG.costs.futures_slippage_bps / 10_000)
    entry_fee = (
        episode.quantity * entry_fill
        * STRESS_CONFIG.costs.futures_fee_bps / 10_000)
    exit_fee = (
        episode.quantity * mark_high
        * STRESS_CONFIG.costs.futures_fee_bps / 10_000)
    equity = (
        episode.futures_margin_usd
        + episode.quantity * (entry_fill - mark_high)
        + episode.adverse_funding_usd - entry_fee - exit_fee
    )
    leverage = (
        episode.quantity * mark_high / equity if equity > 0 else float('inf'))
    episode.last_safety_checked_at = bar_time
    episode.min_futures_equity_usd = min(
        episode.min_futures_equity_usd
        if episode.min_futures_equity_usd is not None else equity,
        equity,
    )
    episode.max_mark_leverage = max(
        episode.max_mark_leverage
        if episode.max_mark_leverage is not None else leverage,
        leverage,
    )
    episode.save(update_fields=[
        'last_safety_checked_at', 'min_futures_equity_usd',
        'max_mark_leverage',
    ])

    equity_breach = equity < STRESS_CONFIG.emergency_futures_equity_floor_usd
    leverage_breach = leverage > STRESS_CONFIG.emergency_max_mark_leverage
    if equity_breach or leverage_breach:
        reason = (
            'emergency_both' if equity_breach and leverage_breach
            else 'emergency_equity' if equity_breach
            else 'emergency_leverage')
        _close_episode(episode, now, reason)
        return {
            'action': reason,
            'equity_usd': equity,
            'mark_leverage': leverage,
            'bar_time': bar_time.isoformat(),
        }
    return {
        'action': 'hold',
        'equity_usd': equity,
        'mark_leverage': leverage,
        'bar_time': bar_time.isoformat(),
    }
