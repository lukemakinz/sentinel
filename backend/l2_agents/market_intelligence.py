"""Deterministic market snapshot for the shadow auction-intelligence agent."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import statistics

from django.utils import timezone


SNAPSHOT_VERSION = 'auction-snapshot-v1'


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(float(value), high))


def _iso(value):
    return value.isoformat() if value is not None else None


def _pct_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return (current / previous - 1.0) * 100.0


def _timeframe_summary(symbol: str, interval: str, limit: int = 240) -> dict:
    from ingester.models import Candle

    rows = list(Candle.objects.filter(
        symbol=symbol, interval=interval, is_closed=True,
    ).order_by('-timestamp').values(
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
    )[:limit])
    rows.reverse()
    if not rows:
        return {'available': False, 'interval': interval}

    closes = [float(row['close']) for row in rows]
    highs = [float(row['high']) for row in rows]
    lows = [float(row['low']) for row in rows]
    volumes = [float(row['volume']) for row in rows]
    current = closes[-1]

    def sma(period):
        return sum(closes[-period:]) / period if len(closes) >= period else None

    sma20, sma50, sma200 = sma(20), sma(50), sma(200)
    slope20 = _pct_change(current, closes[-21]) if len(closes) >= 21 else None
    return20 = _pct_change(current, closes[-21]) if len(closes) >= 21 else None

    true_ranges = []
    for index in range(1, len(rows)):
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))
    atr14 = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else None
    atr_pct = atr14 / current * 100 if atr14 and current else None

    signed_volume = []
    for index in range(1, len(rows)):
        sign = 1 if closes[index] > closes[index - 1] else -1 if closes[index] < closes[index - 1] else 0
        signed_volume.append(sign * volumes[index])
    obv_change_20 = sum(signed_volume[-20:]) if signed_volume else None
    volume_median_20 = statistics.median(volumes[-21:-1]) if len(volumes) >= 21 else None
    volume_ratio = volumes[-1] / volume_median_20 if volume_median_20 else None

    trend = 'RANGE'
    if sma20 is not None and sma50 is not None and slope20 is not None:
        if current > sma20 > sma50 and slope20 > 0:
            trend = 'UP'
        elif current < sma20 < sma50 and slope20 < 0:
            trend = 'DOWN'

    return {
        'available': True,
        'interval': interval,
        'bars': len(rows),
        'last_timestamp': _iso(rows[-1]['timestamp']),
        'close': current,
        'sma20': sma20,
        'sma50': sma50,
        'sma200': sma200,
        'trend': trend,
        'return_20_pct': return20,
        'atr14': atr14,
        'atr_pct': atr_pct,
        'obv_change_20': obv_change_20,
        'volume_ratio_to_median20': volume_ratio,
        '_recent_rows': rows[-96:],
    }


def _zones(tf15: dict) -> list[dict]:
    rows = tf15.get('_recent_rows') or []
    if len(rows) < 20:
        return []
    recent = rows[-20:]
    return [
        {
            'kind': 'RECENT_SUPPORT',
            'low': min(float(row['low']) for row in recent),
            'high': min(float(row['low']) for row in recent),
            'source': '15m_20bar_extreme',
        },
        {
            'kind': 'RECENT_RESISTANCE',
            'low': max(float(row['high']) for row in recent),
            'high': max(float(row['high']) for row in recent),
            'source': '15m_20bar_extreme',
        },
    ]


def _depth_snapshot(symbol: str, now) -> dict:
    from ingester.models import OrderBookSnapshot

    row = OrderBookSnapshot.objects.filter(symbol=symbol).order_by('-timestamp').first()
    if row is None:
        return {'available': False}
    recent = OrderBookSnapshot.objects.filter(
        symbol=symbol, timestamp__gte=now - timedelta(minutes=5),
    )
    imbalances = [float(value) for value in recent.values_list('imbalance_20', flat=True)]
    return {
        'available': True,
        'timestamp': _iso(row.timestamp),
        'age_seconds': max((now - row.timestamp).total_seconds(), 0.0),
        'best_bid': float(row.best_bid),
        'best_ask': float(row.best_ask),
        'mid_price': float(row.mid_price),
        'spread_bps': float(row.spread_bps),
        'bid_depth_20_usd': float(row.bid_depth_20_usd),
        'ask_depth_20_usd': float(row.ask_depth_20_usd),
        'imbalance_5': float(row.imbalance_5),
        'imbalance_20': float(row.imbalance_20),
        'imbalance_20_mean_5m': sum(imbalances) / len(imbalances) if imbalances else None,
        'samples_5m': len(imbalances),
    }


def _flow_snapshot(symbol: str, now) -> dict:
    from ingester.models import FundingRate, Liquidation, OpenInterest, WhaleCVD, RetailCVD

    oi = list(OpenInterest.objects.filter(symbol=symbol).order_by('-timestamp')[:2])
    funding = FundingRate.objects.filter(symbol=symbol).order_by('-timestamp').first()

    def cvd_change(model):
        latest = model.objects.filter(symbol=symbol).order_by('-timestamp').first()
        if latest is None:
            return None, None, None
        cutoff = now - timedelta(minutes=5)
        baseline = model.objects.filter(
            symbol=symbol,
            timestamp__lte=cutoff,
            timestamp__gte=now - timedelta(minutes=10),
        ).order_by('-timestamp').first()
        if baseline is None:
            return None, _iso(latest.timestamp), None
        coverage = (latest.timestamp - baseline.timestamp).total_seconds()
        return (
            float(latest.cumulative_delta - baseline.cumulative_delta),
            _iso(latest.timestamp),
            coverage,
        )

    whale_change, whale_ts, whale_coverage = cvd_change(WhaleCVD)
    retail_change, retail_ts, retail_coverage = cvd_change(RetailCVD)
    liquidations = Liquidation.objects.filter(
        symbol=symbol, timestamp__gte=now - timedelta(minutes=15))
    buy_liq = sum(float(value) for value in liquidations.filter(side='BUY').values_list('usd_value', flat=True))
    sell_liq = sum(float(value) for value in liquidations.filter(side='SELL').values_list('usd_value', flat=True))

    oi_change = None
    oi_ts = None
    oi_previous_ts = None
    oi_gap_seconds = None
    if oi:
        oi_ts = _iso(oi[0].timestamp)
        if len(oi) >= 2:
            oi_previous_ts = _iso(oi[1].timestamp)
            oi_gap_seconds = (oi[0].timestamp - oi[1].timestamp).total_seconds()
            if 4 * 60 <= oi_gap_seconds <= 15 * 60:
                oi_change = _pct_change(
                    float(oi[0].open_interest), float(oi[1].open_interest),
                )
    return {
        'open_interest_change_pct': oi_change,
        'open_interest_timestamp': oi_ts,
        'open_interest_previous_timestamp': oi_previous_ts,
        'open_interest_sample_gap_seconds': oi_gap_seconds,
        'funding_rate': float(funding.funding_rate) if funding else None,
        'funding_timestamp': _iso(funding.timestamp) if funding else None,
        'whale_cvd_change': whale_change,
        'whale_cvd_timestamp': whale_ts,
        'whale_cvd_window_seconds': whale_coverage,
        'retail_cvd_change': retail_change,
        'retail_cvd_timestamp': retail_ts,
        'retail_cvd_window_seconds': retail_coverage,
        'liquidations_15m': {
            'buy_usd': buy_liq,
            'sell_usd': sell_liq,
            'total_usd': buy_liq + sell_liq,
        },
    }


def _latest_structural_context(symbol: str, now) -> dict:
    from .models import L2Decision

    row = L2Decision.objects.filter(
        symbol=symbol, timestamp__gte=now - timedelta(hours=2),
    ).order_by('-timestamp').first()
    if row is None or not row.trade_context:
        return {'available': False}
    context = row.trade_context
    allowed = (
        'strategy', 'direction', 'structure_type', 'swept_level', 'fvg_zone',
        'order_block', 'nearest_liquidity', 'entry_ote', 'session', 'atr',
    )
    return {
        'available': True,
        'timestamp': _iso(row.timestamp),
        **{key: context.get(key) for key in allowed if context.get(key) is not None},
    }


def _age_seconds(iso_value: str | None, now) -> float | None:
    if not iso_value:
        return None
    try:
        value = datetime.fromisoformat(iso_value.replace('Z', '+00:00'))
        return max((now - value).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


def _data_quality(timeframes: dict, depth: dict, flow: dict,
                  global_regime: dict, now) -> dict:
    age15 = _age_seconds(timeframes['15m'].get('last_timestamp'), now)
    age1h = _age_seconds(timeframes['1h'].get('last_timestamp'), now)
    age4h = _age_seconds(timeframes['4h'].get('last_timestamp'), now)
    age_oi = _age_seconds(flow.get('open_interest_timestamp'), now)
    age_funding = _age_seconds(flow.get('funding_timestamp'), now)
    age_whale_cvd = _age_seconds(flow.get('whale_cvd_timestamp'), now)
    age_btc_4h = _age_seconds(global_regime.get('btc_4h_last_timestamp'), now)
    age_eth_4h = _age_seconds(global_regime.get('eth_4h_last_timestamp'), now)
    checks = {
        'candles_15m_fresh': age15 is not None and age15 <= 30 * 60,
        'candles_1h_fresh': age1h is not None and age1h <= 2 * 3600,
        'candles_4h_fresh': age4h is not None and age4h <= 8 * 3600,
        'candles_15m_sufficient': int(timeframes['15m'].get('bars') or 0) >= 50,
        'candles_1h_sufficient': int(timeframes['1h'].get('bars') or 0) >= 50,
        'candles_4h_sufficient': int(timeframes['4h'].get('bars') or 0) >= 200,
        'order_book_fresh': depth.get('available', False) and depth.get('age_seconds', math.inf) <= 30,
        'open_interest_fresh': (
            flow.get('open_interest_change_pct') is not None
            and age_oi is not None and age_oi <= 20 * 60
            and 4 * 60 <= float(flow.get('open_interest_sample_gap_seconds') or 0) <= 15 * 60
        ),
        'funding_fresh': (
            flow.get('funding_rate') is not None
            and age_funding is not None and age_funding <= 12 * 3600
        ),
        'whale_cvd_fresh': (
            flow.get('whale_cvd_change') is not None
            and age_whale_cvd is not None and age_whale_cvd <= 5 * 60
            and float(flow.get('whale_cvd_window_seconds') or 0) >= 4 * 60
        ),
        'global_btc_4h_fresh': age_btc_4h is not None and age_btc_4h <= 8 * 3600,
        'global_eth_4h_fresh': age_eth_4h is not None and age_eth_4h <= 8 * 3600,
    }
    required = (
        'candles_15m_fresh', 'candles_1h_fresh', 'candles_4h_fresh',
        'candles_15m_sufficient', 'candles_1h_sufficient', 'candles_4h_sufficient',
        'order_book_fresh', 'open_interest_fresh', 'whale_cvd_fresh',
        'global_btc_4h_fresh', 'global_eth_4h_fresh',
    )
    hard_failures = [name for name in required if not checks[name]]
    score = sum(checks.values()) / len(checks)
    return {
        'score': round(score, 4),
        'checks': checks,
        'hard_failures': hard_failures,
        'tradable': not hard_failures and score >= 0.75,
    }


def _attention_score(tf15: dict, depth: dict, flow: dict) -> dict:
    volume_ratio = tf15.get('volume_ratio_to_median20')
    oi_change = flow.get('open_interest_change_pct')
    imbalance = depth.get('imbalance_20') if depth.get('available') else None
    liq_total = flow.get('liquidations_15m', {}).get('total_usd', 0.0)
    depth_total = depth.get('bid_depth_20_usd', 0.0) + depth.get('ask_depth_20_usd', 0.0)
    components = {
        'volume_surprise': _clip(((volume_ratio or 1.0) - 1.0) / 2.0) if volume_ratio is not None else None,
        'oi_activity': _clip(abs(oi_change or 0.0) / 1.0) if oi_change is not None else None,
        'book_imbalance': _clip(abs(imbalance or 0.0) / 0.5) if imbalance is not None else None,
        'liquidation_pressure': _clip(liq_total / max(depth_total, 1.0)) if depth_total else None,
    }
    weights = {
        'volume_surprise': 0.35,
        'oi_activity': 0.25,
        'book_imbalance': 0.20,
        'liquidation_pressure': 0.20,
    }
    available_weight = sum(weights[key] for key, value in components.items() if value is not None)
    score = sum(
        weights[key] * value for key, value in components.items() if value is not None
    ) / available_weight if available_weight else 0.0
    return {
        'version': 'aio-v1',
        'score_0_100': round(score * 100, 2),
        'components_0_1': components,
        'directional_signal': False,
    }


def _global_regime(symbol_summaries: dict) -> dict:
    btc_summary = symbol_summaries.get('BTCUSDT', {}).get('4h', {})
    eth_summary = symbol_summaries.get('ETHUSDT', {}).get('4h', {})
    btc = btc_summary.get('trend')
    eth = eth_summary.get('trend')
    alt_trends = [
        frames.get('1h', {}).get('trend')
        for symbol, frames in symbol_summaries.items()
        if symbol not in {'BTCUSDT', 'ETHUSDT'} and frames.get('1h', {}).get('available')
    ]
    breadth_up = sum(value == 'UP' for value in alt_trends) / len(alt_trends) if alt_trends else None
    if btc == eth == 'UP' and (breadth_up is None or breadth_up >= 0.5):
        regime = 'TREND_UP'
    elif btc == eth == 'DOWN' and (breadth_up is None or breadth_up <= 0.5):
        regime = 'TREND_DOWN'
    elif btc == eth == 'RANGE':
        regime = 'RANGE'
    else:
        regime = 'TRANSITION'
    return {
        'state': regime,
        'btc_4h': btc,
        'eth_4h': eth,
        'btc_4h_last_timestamp': btc_summary.get('last_timestamp'),
        'eth_4h_last_timestamp': eth_summary.get('last_timestamp'),
        'alt_breadth_up': breadth_up,
        'source': 'internal_replayable_breadth_v1',
    }


class MarketSnapshotBuilder:
    """Builds a factual, serializable snapshot; it makes no trade decision."""

    def build(self, symbol: str, now=None) -> dict:
        from ingester.models import WatchedPair

        now = now or timezone.now()
        symbol = symbol.upper()
        universe = list(dict.fromkeys(['BTCUSDT', 'ETHUSDT', symbol, *WatchedPair.get_active_symbols()]))
        summaries = {
            item: {
                '15m': _timeframe_summary(item, '15m', 100),
                '1h': _timeframe_summary(item, '1h', 220),
                '4h': _timeframe_summary(item, '4h', 220),
            }
            for item in universe
        }
        instrument = summaries[symbol]
        depth = _depth_snapshot(symbol, now)
        flow = _flow_snapshot(symbol, now)
        global_regime = _global_regime(summaries)
        quality = _data_quality(instrument, depth, flow, global_regime, now)
        zones = _zones(instrument['15m'])
        structural = _latest_structural_context(symbol, now)
        if structural.get('fvg_zone'):
            zone = structural['fvg_zone']
            if isinstance(zone, (list, tuple)) and len(zone) >= 2:
                zones.append({
                    'kind': 'FVG', 'low': float(min(zone)), 'high': float(max(zone)),
                    'source': 'latest_l1_candidate',
                })
        snapshot = {
            'version': SNAPSHOT_VERSION,
            'as_of': _iso(now),
            'symbol': symbol,
            'global_regime': global_regime,
            'instrument': {
                key: {k: v for k, v in value.items() if k != '_recent_rows'}
                for key, value in instrument.items()
            },
            'zones': zones,
            'structural_context': structural,
            'order_book': depth,
            'flow': flow,
            'attention_interest': _attention_score(instrument['15m'], depth, flow),
            'data_quality': quality,
            'strategy_registry': {
                'SAI1_FAILED_AUCTION': 'SHADOW_ONLY',
                'SAI1_IFVG_FLIP': 'SHADOW_ONLY',
                'SAI1_TREND_RETEST': 'SHADOW_ONLY',
            },
            # The shadow resolver only simulates a fixed initial stop. P1/P2
            # stay out of the registry until the resolver implements them,
            # otherwise outcomes would be attributed to a policy never applied.
            'allowed_management_policies': ['P0_INITIAL_STOP'],
            'execution_authorized': False,
        }
        snapshot['snapshot_hash'] = sha256(json.dumps(
            snapshot, sort_keys=True, default=str).encode()).hexdigest()[:24]
        return snapshot


def deterministic_preflight(snapshot: dict) -> dict:
    """Fail closed before an LLM call and provide a no-AI CLI decision."""
    quality = snapshot.get('data_quality') or {}
    if not quality.get('tradable'):
        return {
            'action': 'PASS', 'direction': 'NONE', 'strategy_id': 'NONE',
            'confidence': 1.0, 'data_quality': float(quality.get('score') or 0.0),
            'thesis': [], 'counter_thesis': ['Required market data is missing or stale.'],
            'entry_zone': None, 'trigger_conditions': [],
            'invalidation_conditions': [], 'management_policy': 'NONE',
            'ttl_minutes': 0, 'recheck_condition': 'Wait for all hard data-quality checks to pass.',
            'risk_notes': list(quality.get('hard_failures') or []),
        }
    return {
        'action': 'WAIT', 'direction': 'NONE', 'strategy_id': 'NONE',
        'confidence': 1.0, 'data_quality': float(quality.get('score') or 0.0),
        'thesis': ['Market snapshot is complete enough for structured adjudication.'],
        'counter_thesis': [], 'entry_zone': None, 'trigger_conditions': [],
        'invalidation_conditions': [], 'management_policy': 'NONE',
        'ttl_minutes': 5, 'recheck_condition': 'Run the shadow AI adjudicator or wait for a mechanical trigger.',
        'risk_notes': ['No execution is authorized by preflight.'],
    }
