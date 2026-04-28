from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import auth_views
from executor import views as executor_views

router = DefaultRouter()
router.register(r'positions', views.PositionViewSet, basename='position')
router.register(r'trades', views.TradeViewSet, basename='trade')
router.register(r'exchange-orders', views.ExchangeOpenOrderViewSet, basename='exchange-order')

urlpatterns = [
    path('auth/token/', auth_views.obtain_token, name='auth-token'),
    path('auth/token/rotate/', auth_views.rotate_token, name='auth-token-rotate'),
    path('auth/token/revoke/', auth_views.revoke_token, name='auth-token-revoke'),
    path('status/', views.system_status, name='system-status'),
    path('exchange/state/', views.exchange_live_state, name='exchange-live-state'),
    path('exchange/integration/', views.exchange_integration_status, name='exchange-integration-status'),
    path('exchange/sync/', views.exchange_sync_now, name='exchange-sync-now'),
    path('exchange/transfer-profit/', views.exchange_transfer_profit, name='exchange-transfer-profit'),
    path('conviction/', views.conviction_scores, name='conviction-scores'),
    path('analysts/', views.analyst_signals, name='analyst-signals'),
    path('performance/', views.performance, name='performance'),
    path('risk/', views.risk_status, name='risk-status'),
    path('consensus/history/', views.consensus_history, name='consensus-history'),
    path('positions/manual/', executor_views.manual_position_open, name='manual-position'),
    path('positions/<int:position_id>/live/', executor_views.position_live, name='position-live'),
    path('positions/<int:position_id>/evaluate/', executor_views.position_evaluate, name='position-evaluate'),
    path('system/stats/', views.system_stats, name='system-stats'),
    path('mtf/<str:symbol>/', views.mtf_analysis, name='mtf-analysis'),
    path('scan/<str:symbol>/', views.latest_scan, name='latest-scan'),
    path('analysis/<str:symbol>/', views.latest_analysis, name='latest-analysis'),
    path('pairs/', views.watched_pairs, name='watched-pairs'),
    path('pairs/<str:symbol>/', views.watched_pair_detail, name='watched-pair-detail'),
    path('signals/', views.active_signals, name='signals'),
    path('signals/<int:signal_id>/enter/', views.enter_signal, name='signal-enter'),
    path('signals/<int:signal_id>/dismiss/', views.dismiss_signal, name='signal-dismiss'),
    path('evaluator/stats/', views.evaluator_stats, name='evaluator-stats'),
    path('strategy/health/', views.strategy_health, name='strategy-health'),
    path('tax/', views.tax_events, name='tax-events'),
    path('backtest/run/', views.backtest_run, name='backtest-run'),
    path('backtest/<int:run_id>/', views.backtest_status, name='backtest-status'),
    path('backtest/', views.backtest_list, name='backtest-list'),
    path('', include(router.urls)),
]
