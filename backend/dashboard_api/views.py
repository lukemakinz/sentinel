"""Dashboard REST API views."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response

# analysts/ and consensus/ removed from INSTALLED_APPS — imports disabled
# from analysts.models import AnalystSignalRecord
# from consensus.models import ConsensusSignal
from executor.models import Position, Trade, AccountState
from ingester.models import Candle
from risk.models import RiskState, RiskEvent

from .serializers import (
    PositionSerializer, TradeSerializer, AccountStateSerializer,
    RiskStateSerializer, RiskEventSerializer,
)


@api_view(['GET'])
def system_status(request):
    """System health and status overview."""
    latest_candle = Candle.objects.order_by('-timestamp').first()
    risk_state, _ = RiskState.objects.get_or_create(pk=1)

    return Response({
        'status': 'running',
        'trading_mode': settings.TRADING_MODE,
        'trading_pairs': settings.TRADING_PAIRS,
        'ingester_active': latest_candle is not None and (
            timezone.now() - latest_candle.timestamp < timedelta(minutes=5)
        ) if latest_candle else False,
        'total_candles': Candle.objects.count(),
        'latest_candle_time': latest_candle.timestamp if latest_candle else None,
        'open_positions': Position.objects.filter(status='OPEN').count(),
        'daily_pnl': risk_state.daily_pnl,
    })


@api_view(['GET'])
def conviction_scores(request):
    """Stub — analysts/consensus removed from pipeline. Returns empty."""
    # analysts/ and consensus/ disabled — dead code removed from active pipeline.
    # Real signal quality now tracked via /api/evaluator/stats/
    from ingester.models import WatchedPair
    pairs = WatchedPair.get_active_symbols()
    result = {s: {'symbol': s, 'conviction_score': 0, 'tier': 'NONE', 'bias': 'NEUTRAL'}
              for s in pairs}
    return Response(result)


@api_view(['GET'])
def analyst_signals(request):
    """Stub — analysts removed from pipeline. Returns empty."""
    return Response({})


class PositionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PositionSerializer

    def get_queryset(self):
        qs = Position.objects.all()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TradeSerializer
    queryset = Trade.objects.all()


@api_view(['GET'])
def performance(request):
    """Performance analytics — win rate, Sharpe, equity curve."""
    state = AccountState.objects.order_by('-updated_at').first()
    trades = Trade.objects.all()

    total = trades.count()
    wins = trades.filter(pnl__gt=0).count()
    losses = trades.filter(pnl__lt=0).count()

    avg_win = trades.filter(pnl__gt=0).values_list('pnl_percent', flat=True)
    avg_loss = trades.filter(pnl__lt=0).values_list('pnl_percent', flat=True)

    avg_win_val = sum(avg_win) / len(avg_win) if avg_win else 0
    avg_loss_val = abs(sum(avg_loss) / len(avg_loss)) if avg_loss else 0

    # Equity curve from account states
    equity_curve = list(AccountState.objects.order_by('updated_at').values('updated_at', 'equity', 'balance'))

    return Response({
        'account': AccountStateSerializer(state).data if state else None,
        'total_trades': total,
        'winning_trades': wins,
        'losing_trades': losses,
        'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
        'avg_win': round(avg_win_val, 2),
        'avg_loss': round(avg_loss_val, 2),
        'profit_factor': round(avg_win_val / avg_loss_val, 2) if avg_loss_val > 0 else 0,
        'avg_rr': round(sum(t.risk_reward for t in trades) / total, 2) if total > 0 else 0,
        'max_drawdown': state.max_drawdown if state else 0,
        'equity_curve': equity_curve[-100:],
    })


@api_view(['GET'])
def risk_status(request):
    """Current risk manager state."""
    state, _ = RiskState.objects.get_or_create(pk=1)
    events = RiskEvent.objects.order_by('-timestamp')[:20]
    return Response({
        'state': RiskStateSerializer(state).data,
        'recent_events': RiskEventSerializer(events, many=True).data,
    })


def _get_dd_multiplier():
    try:
        from risk.kill_switches import get_dd_size_multiplier
        return get_dd_size_multiplier()
    except Exception:
        return 1.0


KNOWN_FUTURES_PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'LINKUSDT', 'MATICUSDT', 'UNIUSDT',
    'ATOMUSDT', 'LTCUSDT', 'ETCUSDT', 'NEARUSDT', 'APTUSDT', 'ARBUSDT',
    'OPUSDT', 'INJUSDT', 'SUIUSDT', 'SEIUSDT', 'TIAUSDT', 'FETUSDT',
]


@api_view(['GET', 'POST'])
def watched_pairs(request):
    """GET: list watched pairs. POST: add a pair."""
    from ingester.models import WatchedPair

    if request.method == 'POST':
        symbol = request.data.get('symbol', '').upper().strip()
        if not symbol:
            return Response({'error': 'symbol required'}, status=400)
        if not symbol.endswith('USDT'):
            return Response({'error': 'Only USDT perpetuals supported (e.g. SOLUSDT)'}, status=400)
        pair, created = WatchedPair.objects.get_or_create(symbol=symbol, defaults={'active': True})
        if not created:
            pair.active = True
            pair.save()
        return Response({'symbol': pair.symbol, 'active': pair.active, 'created': created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    pairs = list(WatchedPair.objects.values('symbol', 'active', 'added_at'))
    active = WatchedPair.get_active_symbols()
    return Response({'pairs': pairs, 'active_symbols': active, 'suggestions': KNOWN_FUTURES_PAIRS})


@api_view(['DELETE', 'PATCH'])
def watched_pair_detail(request, symbol):
    """DELETE: remove pair. PATCH: toggle active."""
    from ingester.models import WatchedPair
    symbol = symbol.upper()
    try:
        pair = WatchedPair.objects.get(symbol=symbol)
    except WatchedPair.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)

    if request.method == 'DELETE':
        pair.delete()
        return Response({'deleted': symbol})

    # PATCH — toggle active
    pair.active = not pair.active
    pair.save()
    return Response({'symbol': pair.symbol, 'active': pair.active})


@api_view(['GET'])
def system_stats(request):
    """Live system activity metrics — last sync, scans, AI analyses, signals."""
    from l1_filter.models import L1Result
    from l2_agents.models import L2Decision
    from ingester.models import Candle, WhaleCVD, AggTrade
    from datetime import timedelta

    now    = timezone.now()
    last1h = now - timedelta(hours=1)
    last24 = now - timedelta(hours=24)

    # Last data ingestion
    last_candle   = Candle.objects.order_by('-timestamp').first()
    last_cvd      = WhaleCVD.objects.order_by('-timestamp').first()
    last_aggtrade = AggTrade.objects.order_by('-timestamp').first()

    # L1 scan stats
    scans_1h       = L1Result.objects.filter(timestamp__gte=last1h).count()
    scans_pass_24h = L1Result.objects.filter(timestamp__gte=last24, passed=True).count()
    scans_fail_24h = L1Result.objects.filter(timestamp__gte=last24, passed=False).count()
    last_l1        = L1Result.objects.order_by('-timestamp').first()

    # L2 AI analysis stats
    ai_total_24h   = L2Decision.objects.filter(timestamp__gte=last24).count()
    ai_approve_24h = L2Decision.objects.filter(timestamp__gte=last24, action='APPROVE').count()
    ai_reject_24h  = L2Decision.objects.filter(timestamp__gte=last24, action='REJECT').count()
    last_l2        = L2Decision.objects.order_by('-timestamp').first()

    # Active signals (approved, not dismissed, last 30 min)
    active_signals = L2Decision.objects.filter(
        action='APPROVE', dismissed=False,
        timestamp__gte=now - timedelta(minutes=30)
    ).count()

    # Data freshness check
    data_age_sec = None
    if last_candle:
        data_age_sec = int((now - last_candle.timestamp).total_seconds())

    return Response({
        'now': now,
        'data': {
            'last_candle':      last_candle.timestamp   if last_candle   else None,
            'last_cvd':         last_cvd.timestamp      if last_cvd      else None,
            'last_aggtrade':    last_aggtrade.timestamp if last_aggtrade else None,
            'data_age_seconds': data_age_sec,
            'data_fresh':       data_age_sec is not None and data_age_sec < 120,
        },
        'l1': {
            'scans_last_1h':    scans_1h,
            'pass_last_24h':    scans_pass_24h,
            'fail_last_24h':    scans_fail_24h,
            'last_scan':        last_l1.timestamp  if last_l1  else None,
            'last_symbol':      last_l1.symbol     if last_l1  else None,
            'last_direction':   last_l1.direction  if last_l1  else None,
            'last_passed':      last_l1.passed     if last_l1  else None,
        },
        'l2': {
            'ai_analyses_24h':  ai_total_24h,
            'approved_24h':     ai_approve_24h,
            'rejected_24h':     ai_reject_24h,
            'last_analysis':    last_l2.timestamp  if last_l2  else None,
            'last_action':      last_l2.action     if last_l2  else None,
        },
        'signals': {
            'active_now':       active_signals,
            'generated_24h':    ai_approve_24h,
        },
    })


@api_view(['GET'])
def mtf_analysis(request, symbol):
    """Multi-timeframe trend analysis for a symbol."""
    from l1_filter.mtf import analyze_mtf
    try:
        return Response(analyze_mtf(symbol))
    except Exception as e:
        return Response({'symbol': symbol, 'error': str(e)}, status=500)


@api_view(['GET'])
def latest_scan(request, symbol):
    """Last L1 scan result for a symbol — gates status + trade context."""
    from l1_filter.models import L1Result

    result = L1Result.objects.filter(symbol=symbol).order_by('-timestamp').first()
    if not result:
        return Response({'symbol': symbol, 'no_data': True})

    from l1_filter.strategies import evaluate_strategies, STRATEGIES
    from ingester.models import WhaleCVD
    from datetime import timedelta

    ctx = result.trade_context or {}
    gates_a = result.gates_a or {}
    gates_b = result.gates_b or {}
    gates_c = result.gates_c or {}

    # Check which strategies pass with these gate results
    cutoff = timezone.now() - timedelta(hours=4)
    has_cvd = WhaleCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff).exists()
    passing_strategies = evaluate_strategies(gates_a, gates_b, gates_c, has_whale_cvd=has_cvd, ctx=ctx)

    return Response({
        'symbol':              symbol,
        'timestamp':           result.timestamp,
        'passed':              result.passed,
        'direction':           result.direction,
        'gates_a':             gates_a,
        'gates_b':             gates_b,
        'gates_c':             gates_c,
        'gates_b_count':       result.gates_b_count,
        'gates_c_count':       result.gates_c_count,
        'passing_strategies':  [
            {'id': s, 'name': STRATEGIES[s]['name'], 'desc': STRATEGIES[s]['description']}
            for s in passing_strategies
        ],
        'adx_value':     ctx.get('adx_value'),
        'funding_rate':  ctx.get('funding_rate'),
        'regime':        ctx.get('regime'),
        'atr':           ctx.get('atr'),
        'fvg_zone':      ctx.get('fvg_zone'),
        'swept_level':   ctx.get('swept_level'),
        'btc_trend':     ctx.get('btc_trend'),
        'daily_vwap':    ctx.get('daily_vwap'),
        'has_whale_cvd': has_cvd,
    })


@api_view(['GET'])
def latest_analysis(request, symbol):
    """Last L2 decision for a symbol — AI agents reasoning."""
    from l2_agents.models import L2Decision

    decision = L2Decision.objects.filter(symbol=symbol).order_by('-timestamp').first()
    if not decision:
        return Response({'symbol': symbol, 'no_data': True})

    tp = decision.trade_params or {}
    return Response({
        'symbol':          symbol,
        'timestamp':       decision.timestamp,
        'direction':       decision.direction,
        'action':          decision.action,
        'size_multiplier': decision.size_multiplier,
        'veto_reason':     decision.veto_reason,
        'agents_summary':  decision.agents_summary,
        'entry_price':     tp.get('entry_price'),
        'stop_loss':       tp.get('stop_loss'),
        'take_profit_1':   tp.get('take_profits', [{}])[0].get('level') if tp.get('take_profits') else None,
        'take_profit_2':   tp.get('take_profits', [{}])[1].get('level') if tp.get('take_profits') and len(tp.get('take_profits', [])) > 1 else None,
        'r_value':         tp.get('r_value'),
    })


@api_view(['GET'])
def active_signals(request):
    """Active (un-dismissed APPROVE) signals from last 30 min with L3 trade params."""
    from l2_agents.models import L2Decision
    from datetime import timedelta

    cutoff  = timezone.now() - timedelta(minutes=30)
    signals = L2Decision.objects.filter(
        action='APPROVE', dismissed=False, timestamp__gte=cutoff
    ).order_by('-timestamp')[:10]

    data = []
    for s in signals:
        age_sec = int((timezone.now() - s.timestamp).total_seconds())
        tp = s.trade_params or {}
        data.append({
            'id':             s.id,
            'symbol':         s.symbol,
            'direction':      s.direction,
            'timestamp':      s.timestamp,
            'age_seconds':    age_sec,
            'size_multiplier': s.size_multiplier,
            'agents_summary': s.agents_summary,
            'entry_price':    tp.get('entry_price'),
            'stop_loss':      tp.get('stop_loss'),
            'take_profit_1':  tp.get('take_profits', [{}])[0].get('level') if tp.get('take_profits') else None,
            'take_profit_2':  tp.get('take_profits', [{}])[1].get('level') if tp.get('take_profits') and len(tp.get('take_profits', [])) > 1 else None,
            'r_value':        tp.get('r_value'),
            'strategy':       tp.get('strategy', 'S1'),
        })
    return Response(data)


@api_view(['POST'])
def enter_signal(request, signal_id):
    """User accepts signal — opens position with their actual entry price."""
    from l2_agents.models import L2Decision
    from executor.models import Position
    from executor.views import compute_liquidation_price

    try:
        sig = L2Decision.objects.get(pk=signal_id, action='APPROVE', dismissed=False)
    except L2Decision.DoesNotExist:
        return Response({'error': 'Signal not found or already dismissed'}, status=404)

    actual_entry = float(request.data.get('entry_price', 0))
    if actual_entry <= 0:
        return Response({'error': 'entry_price required'}, status=400)

    tp = sig.trade_params or {}
    orig_sl = tp.get('stop_loss')
    if not orig_sl:
        return Response({'error': 'Signal has no trade params — L3 not calculated yet'}, status=400)

    # Recalculate TPs from actual entry (same R distance)
    r         = abs(actual_entry - orig_sl)
    direction = sig.direction
    tp1 = actual_entry + 1.5 * r if direction == 'LONG' else actual_entry - 1.5 * r
    tp2 = actual_entry + 3.0 * r if direction == 'LONG' else actual_entry - 3.0 * r

    from django.conf import settings
    leverage  = getattr(settings, 'MAX_LEVERAGE', 5)
    balance   = getattr(settings, 'INITIAL_BALANCE', 10000)
    risk_usd  = balance * getattr(settings, 'MAX_RISK_PER_TRADE', 0.005) * sig.size_multiplier
    quantity  = risk_usd / r if r > 0 else 0

    pos = Position.objects.create(
        symbol=sig.symbol, side=direction, status='OPEN',
        entry_price=actual_entry, current_price=actual_entry,
        quantity=quantity, remaining_quantity=quantity,
        position_size_usd=quantity * actual_entry,
        leverage=leverage,
        margin_usd=risk_usd,
        stop_loss=orig_sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        liquidation_price=compute_liquidation_price(direction, actual_entry, leverage),
        source='signal',
        strategy=tp.get('strategy', 'S1'),
    )

    sig.dismissed = True
    sig.save()

    return Response({'position_id': pos.id, 'entry_price': actual_entry,
                     'stop_loss': orig_sl, 'take_profit_1': tp1, 'take_profit_2': tp2},
                    status=status.HTTP_201_CREATED)


@api_view(['POST'])
def dismiss_signal(request, signal_id):
    """User dismisses a signal without entering."""
    from l2_agents.models import L2Decision
    try:
        sig = L2Decision.objects.get(pk=signal_id, action='APPROVE')
        sig.dismissed = True
        sig.save()
        return Response({'dismissed': True})
    except L2Decision.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)


@api_view(['GET'])
def evaluator_stats(request):
    """Signal evaluation stats — win rate per strategy/session/regime + agent calibration."""
    from evaluator.stats import get_stats
    filters = {}
    if request.query_params.get('strategy'):
        filters['strategy'] = request.query_params['strategy']
    if request.query_params.get('symbol'):
        filters['symbol'] = request.query_params['symbol']
    return Response(get_stats(filters))


@api_view(['GET'])
def strategy_health(request):
    """Current strategy health metrics — rolling Sharpe, win rate, halt status."""
    from risk.strategy_monitor import check_strategy_health, compute_rolling_sharpe
    from executor.models import Trade

    ok, reason = check_strategy_health()

    last_30 = list(Trade.objects.order_by('-exit_time').values_list('pnl_percent', flat=True)[:30])
    last_20 = list(Trade.objects.order_by('-exit_time').values_list('pnl_percent', flat=True)[:20])
    total   = Trade.objects.count()
    wins    = Trade.objects.filter(pnl__gt=0).count()

    return Response({
        'strategy_ok':    ok,
        'halt_reason':    reason if not ok else None,
        'total_trades':   total,
        'win_rate':       round(wins / total * 100, 1) if total else 0,
        'rolling_sharpe_30': round(compute_rolling_sharpe(list(reversed(last_30))), 3),
        'rolling_sharpe_20': round(compute_rolling_sharpe(list(reversed(last_20))), 3),
        'dd_size_multiplier': _get_dd_multiplier(),
    })


@api_view(['GET'])
def tax_events(request):
    """Tax event list for PIT-38 export."""
    from executor.models import TaxEvent
    year = request.query_params.get('year')
    qs   = TaxEvent.objects.order_by('-close_date')
    if year:
        qs = qs.filter(close_date__year=year)
    data = list(qs.values('id', 'symbol', 'side', 'entry_price', 'exit_price',
                           'quantity', 'pnl_usd', 'close_date'))
    total_pnl = sum(e['pnl_usd'] for e in data)
    return Response({'events': data, 'total_pnl_usd': round(total_pnl, 2), 'count': len(data)})


@api_view(['POST'])
def backtest_run(request):
    """Start a backtest run asynchronously."""
    from backtest.models import BacktestRun
    from backtest.tasks import run_backtest
    import datetime

    symbol   = request.data.get('symbol', 'BTCUSDT')
    strategy = request.data.get('strategy', 'S1')
    start    = request.data.get('start_date', '2024-01-01')
    end      = request.data.get('end_date', '2025-01-01')
    capital  = float(request.data.get('initial_capital', 10000))
    risk     = float(request.data.get('risk_per_trade', 0.005))

    run = BacktestRun.objects.create(
        symbol=symbol, strategy=strategy,
        start_date=start, end_date=end,
        initial_capital=capital, risk_per_trade=risk,
        status='pending',
    )
    run_backtest.delay(run.id)
    return Response({'id': run.id, 'status': 'pending'}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def backtest_status(request, run_id):
    """Poll status and result of a backtest run."""
    from backtest.models import BacktestRun
    try:
        run = BacktestRun.objects.get(pk=run_id)
    except BacktestRun.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    data = {
        'id': run.id,
        'symbol': run.symbol,
        'strategy': run.strategy,
        'status': run.status,
        'error_message': run.error_message,
        'created_at': run.created_at,
        'completed_at': run.completed_at,
    }
    if run.status == 'done':
        data.update({
            'total_trades':   run.total_trades,
            'winning_trades': run.winning_trades,
            'win_rate':       round(run.win_rate * 100, 1),
            'sharpe_ratio':   run.sharpe_ratio,
            'calmar_ratio':   run.calmar_ratio,
            'max_drawdown':   run.max_drawdown,
            'total_pnl':      run.total_pnl,
            'total_pnl_pct':  run.total_pnl_pct,
            'final_capital':  run.final_capital,
            'initial_capital': run.initial_capital,
            'passes_live':    run.passes_live_threshold(),
            'mc_ruin_probability': run.mc_ruin_probability,
            'mc_worst_5pct_dd':   run.mc_worst_5pct_dd,
            'mc_median_sharpe':   run.mc_median_sharpe,
            'equity_curve':   run.equity_curve,
        })
    return Response(data)


@api_view(['GET'])
def backtest_list(request):
    """List recent backtest runs."""
    from backtest.models import BacktestRun
    runs = BacktestRun.objects.order_by('-created_at')[:20].values(
        'id', 'symbol', 'strategy', 'status', 'created_at',
        'sharpe_ratio', 'max_drawdown', 'win_rate', 'total_trades',
    )
    return Response(list(runs))


@api_view(['GET'])
def consensus_history(request):
    """Stub — consensus removed. Use /api/evaluator/stats/ for signal history."""
    return Response([])
