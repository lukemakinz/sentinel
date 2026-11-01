import os
from pathlib import Path

from decouple import Config, RepositoryEnv

BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_from_environment_or_project_env(name: str, default: str = '') -> str:
    """Read secrets locally without importing Docker-oriented .env settings.

    The repository .env contains values such as ``DB_PATH=/app/...`` which are
    correct in Docker but invalid for a local management command.  Only callers
    that explicitly opt in (API secrets below) use this fallback.
    """
    if name in os.environ:
        return os.environ[name]
    project_env_path = BASE_DIR.parent / '.env'
    if project_env_path.exists():
        return Config(RepositoryEnv(str(project_env_path)))(name, default=default)
    return default

# --- Core ---
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-key')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# --- Apps ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'django_celery_beat',
    # Sentinel apps
    'ingester',
    'l1_filter',
    'l2_agents',
    'backtest',
    'evaluator',
    # analysts/ and consensus/ DISABLED — dead code, not in decision path.
    # Models kept for historical data, apps removed from pipeline.
    # 'analysts',
    # 'consensus',
    'risk',
    'executor',
    'dashboard_api',
    'carry_monitor',
    'scalp_monitor',
    'telegram_bot',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sentinel.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sentinel.wsgi.application'

# --- Database ---
# SQLite by default. On Pi: DB_PATH=/app/db/db.sqlite3 persists in Docker volume.
# Postgres is opt-in via DB_ENGINE=postgres, read from the process environment
# or the gitignored backend/.env.local.  The Docker-oriented repository .env
# (POSTGRES_HOST=db) is deliberately NOT consulted here.
def _local_db_setting(name: str, default: str = '') -> str:
    if name in os.environ:
        return os.environ[name]
    local_env_path = BASE_DIR / '.env.local'
    if local_env_path.exists():
        return Config(RepositoryEnv(str(local_env_path)))(name, default=default)
    return default


_db_path = os.environ.get('DB_PATH', str(BASE_DIR / 'db.sqlite3'))
_sqlite_database = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': _db_path,
    'OPTIONS': {'timeout': 30},
}
DB_ENGINE = _local_db_setting('DB_ENGINE', 'sqlite').strip().lower()
if DB_ENGINE in ('postgres', 'postgresql'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _local_db_setting('POSTGRES_DB', 'sentinel'),
            'USER': _local_db_setting('POSTGRES_USER', 'sentinel'),
            'PASSWORD': _local_db_setting('POSTGRES_PASSWORD', ''),
            'HOST': _local_db_setting('POSTGRES_HOST', 'localhost'),
            'PORT': _local_db_setting('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    DATABASES = {'default': _sqlite_database}

# One-off migration source: SQLITE_SOURCE_PATH=/path/db.sqlite3 exposes the old
# file as the read-only-by-convention 'sqlite_source' alias.
if os.environ.get('SQLITE_SOURCE_PATH'):
    DATABASES['sqlite_source'] = {
        **_sqlite_database, 'NAME': os.environ['SQLITE_SOURCE_PATH'],
    }

# --- Cache ---
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    }
}

# --- Auth ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- i18n ---
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# --- Static ---
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- CORS ---
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]

# --- REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',
}

# --- Celery ---
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# --- Sentinel Config ---
TRADING_PAIRS = os.environ.get('TRADING_PAIRS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')
GLOBAL_CONTEXT_PAIRS = os.environ.get('GLOBAL_CONTEXT_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
# Frozen alt-breadth universe for global_context (M3) only.  Rule: Binance USDT
# perpetuals listed >= 730 days, no 'Alpha' tag, no stablecoins/BTC/ETH, top 20
# by 30-day median daily quote volume as of 2026-11-01.  Changing the list
# requires a new version.  Collected as closed 15m/1h/4h candles only: no
# aggTrade/depth, never traded, never part of the frozen M0 global_regime.
BREADTH_UNIVERSE_VERSION = os.environ.get(
    'BREADTH_UNIVERSE_VERSION', 'breadth-universe-v1-2026-11-01',
)
BREADTH_PAIRS = [s for s in os.environ.get(
    'BREADTH_PAIRS',
    'ZECUSDT,SOLUSDT,NEARUSDT,XRPUSDT,DOGEUSDT,BNBUSDT,ENAUSDT,WLDUSDT,'
    '1000PEPEUSDT,SUIUSDT,UNIUSDT,ADAUSDT,FILUSDT,AVAXUSDT,TAOUSDT,LINKUSDT,'
    'QNTUSDT,AAVEUSDT,STRKUSDT,INJUSDT',
).split(',') if s]
BREADTH_INTERVALS = ['15m', '1h', '4h']
TRADING_MODE = os.environ.get('TRADING_MODE', 'paper')  # paper, signal_only, semi_auto, full_auto
BINANCE_TESTNET = os.environ.get('BINANCE_TESTNET', 'True').lower() in ('true', '1')
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')
ANTHROPIC_API_KEY = _secret_from_environment_or_project_env('ANTHROPIC_API_KEY')
OPENAI_API_KEY = _secret_from_environment_or_project_env('OPENAI_API_KEY')
TELEGRAM_BOT_TOKEN = _secret_from_environment_or_project_env('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = _secret_from_environment_or_project_env('TELEGRAM_CHAT_ID')
TELEGRAM_ALERT_STATUSES = set(filter(None, os.environ.get(
    'TELEGRAM_ALERT_STATUSES', 'WAIT_RETEST,WAIT_MSS').split(',')))
TELEGRAM_DAILY_SUMMARY_HOUR_UTC = int(os.environ.get('TELEGRAM_DAILY_SUMMARY_HOUR_UTC', '7'))
FEED_STALE_SECONDS = int(os.environ.get('FEED_STALE_SECONDS', '300'))
SETUP_SEARCH_ENABLED = os.environ.get('SETUP_SEARCH_ENABLED', 'True').lower() in ('true', '1')
SETUP_SEARCH_MAX_SYMBOLS = int(os.environ.get('SETUP_SEARCH_MAX_SYMBOLS', '60'))
AI_ADJUDICATOR_SHADOW_ENABLED = os.environ.get(
    'AI_ADJUDICATOR_SHADOW_ENABLED', 'False').lower() in ('true', '1')
AI_ADJUDICATOR_EXECUTION_ENABLED = False  # safety invariant; S12AI is research-only
AI_CANDIDATE_MIN_CRITERIA = int(os.environ.get('AI_CANDIDATE_MIN_CRITERIA', '7'))
AI_CANDIDATE_MIN_STRUCTURAL = int(os.environ.get('AI_CANDIDATE_MIN_STRUCTURAL', '2'))

# Risk params.  Defaults match the conservative research protocol; operators
# can still override them explicitly through the environment.
MAX_RISK_PER_TRADE = float(os.environ.get('MAX_RISK_PER_TRADE', '0.002'))
MAX_DAILY_DRAWDOWN = float(os.environ.get('MAX_DAILY_DRAWDOWN', '0.006'))
MAX_DAILY_PORTFOLIO_DRAWDOWN = float(os.environ.get('MAX_DAILY_PORTFOLIO_DRAWDOWN', '0.006'))
MAX_WEEKLY_DRAWDOWN = float(os.environ.get('MAX_WEEKLY_DRAWDOWN', '0.018'))
MAX_OPEN_POSITIONS = int(os.environ.get('MAX_OPEN_POSITIONS', '2'))
PROFIT_TO_SPOT_RATIO = float(os.environ.get('PROFIT_TO_SPOT_RATIO', '0.10'))
DEFAULT_MARGIN_MODE = os.environ.get('DEFAULT_MARGIN_MODE', 'isolated')
MAX_LEVERAGE = int(os.environ.get('MAX_LEVERAGE', '5'))
MAX_HIGH_CONVICTION_LEVERAGE = int(os.environ.get('MAX_HIGH_CONVICTION_LEVERAGE', '5'))
MAX_MARGIN_PER_TRADE_PCT = float(os.environ.get('MAX_MARGIN_PER_TRADE_PCT', '0.15'))
MIN_LIQUIDATION_BUFFER_R = float(os.environ.get('MIN_LIQUIDATION_BUFFER_R', '3.0'))
MAINTENANCE_MARGIN_RATE = float(os.environ.get('MAINTENANCE_MARGIN_RATE', '0.005'))
INITIAL_BALANCE = float(os.environ.get('INITIAL_BALANCE', '10000'))
LIVE_CAPITAL_BASELINE_USD = float(os.environ.get(
    'LIVE_CAPITAL_BASELINE_USD', str(INITIAL_BALANCE),
))

# Paper execution assumptions (basis points).  Stop management is deliberately
# frozen to the initial invalidation by default; alternatives must be promoted
# by a named, replayed experiment rather than silently changing live behaviour.
PAPER_MARKET_SLIPPAGE_BPS = float(os.environ.get('PAPER_MARKET_SLIPPAGE_BPS', '5'))
PAPER_ALT_SLIPPAGE_BPS = float(os.environ.get('PAPER_ALT_SLIPPAGE_BPS', '15'))
PAPER_TAKER_FEE_BPS = float(os.environ.get('PAPER_TAKER_FEE_BPS', '5'))
PAPER_MAKER_FEE_BPS = float(os.environ.get('PAPER_MAKER_FEE_BPS', '2'))
PAPER_STOP_MANAGEMENT_POLICY = os.environ.get(
    'PAPER_STOP_MANAGEMENT_POLICY', 'INITIAL_STOP_ONLY').upper()
ORDER_BOOK_STREAM_ENABLED = os.environ.get(
    'ORDER_BOOK_STREAM_ENABLED', 'True').lower() in ('true', '1')
ORDER_BOOK_SNAPSHOT_INTERVAL_SECONDS = float(os.environ.get(
    'ORDER_BOOK_SNAPSHOT_INTERVAL_SECONDS', '5'))
ORDER_BOOK_RETENTION_DAYS = int(os.environ.get('ORDER_BOOK_RETENTION_DAYS', '14'))
AGGTRADE_RETENTION_DAYS = int(os.environ.get('AGGTRADE_RETENTION_DAYS', '14'))
# Long-term Parquet copy of order book / aggTrades; pruning waits for it.
PAPER_FORWARD_DIR = Path(os.environ.get('PAPER_FORWARD_DIR', str(BASE_DIR.parent / 'data' / 'paper_forward')))
PAPER_FORWARD_CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
PAPER_FORWARD_ENABLED = os.environ.get('PAPER_FORWARD_ENABLED', 'True').lower() in ('true', '1')
MARKET_ARCHIVE_DIR = Path(os.environ.get('MARKET_ARCHIVE_DIR', str(BASE_DIR.parent / 'data' / 'archive')))
OPEN_INTEREST_POLL_SECONDS = int(os.environ.get('OPEN_INTEREST_POLL_SECONDS', '300'))
AGGTRADE_FLUSH_SECONDS = float(os.environ.get('AGGTRADE_FLUSH_SECONDS', '1'))
AUCTION_SHADOW_ENABLED = os.environ.get(
    'AUCTION_SHADOW_ENABLED', 'True').lower() in ('true', '1')
AUCTION_ENABLED_STRATEGIES = tuple(
    item.strip() for item in os.environ.get(
        'AUCTION_ENABLED_STRATEGIES',
        'SAI1_FAILED_AUCTION,SAI1_IFVG_FLIP,SAI1_TREND_RETEST',
    ).split(',') if item.strip()
)
AUCTION_AI_PROVIDER = os.environ.get('AUCTION_AI_PROVIDER', 'openai').strip().lower()
AUCTION_OPENAI_MODEL = os.environ.get('AUCTION_OPENAI_MODEL', 'gpt-6.1-sol').strip()
AUCTION_OPENAI_REASONING_EFFORT = os.environ.get(
    'AUCTION_OPENAI_REASONING_EFFORT', 'high',
).strip().lower()
# Standard, short-context prices per 1M tokens as of 2026-10-26. Keep these
# operator-configurable so a pricing change never requires a code release.
AUCTION_OPENAI_INPUT_USD_PER_MILLION = float(os.environ.get(
    'AUCTION_OPENAI_INPUT_USD_PER_MILLION', '2.0'))
AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION = float(os.environ.get(
    'AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION', '0.10'))
AUCTION_OPENAI_OUTPUT_USD_PER_MILLION = float(os.environ.get(
    'AUCTION_OPENAI_OUTPUT_USD_PER_MILLION', '10.0'))
AUCTION_OPENAI_PRICING_AS_OF = os.environ.get(
    'AUCTION_OPENAI_PRICING_AS_OF', '2026-10-26')
# Hard cap on persisted AI spend per UTC day; once reached, analyses fail
# closed to PASS without calling the provider. 0 blocks all AI calls.
AUCTION_AI_DAILY_BUDGET_USD = float(os.environ.get('AUCTION_AI_DAILY_BUDGET_USD', '1.0'))
_auction_ai_default = (
    'True' if AUCTION_AI_PROVIDER == 'openai' and OPENAI_API_KEY else 'False'
)
AUCTION_SHADOW_AI_ENABLED = os.environ.get(
    'AUCTION_SHADOW_AI_ENABLED',
    os.environ.get('AI_ADJUDICATOR_SHADOW_ENABLED', _auction_ai_default),
).lower() in ('true', '1')
AUCTION_SHADOW_TARGET_R = float(os.environ.get('AUCTION_SHADOW_TARGET_R', '1.5'))
AUCTION_SHADOW_MAX_HOLD_MINUTES = int(os.environ.get('AUCTION_SHADOW_MAX_HOLD_MINUTES', '240'))
AUCTION_SHADOW_CYCLE_SECONDS = int(os.environ.get('AUCTION_SHADOW_CYCLE_SECONDS', '300'))
AUCTION_SHADOW_RESOLVE_SECONDS = int(os.environ.get('AUCTION_SHADOW_RESOLVE_SECONDS', '60'))
EXCHANGE_NAME = os.environ.get('EXCHANGE_NAME', 'kucoin').lower()
LIVE_TRADING_ENABLED = os.environ.get('LIVE_TRADING_ENABLED', 'False').lower() in ('true', '1')
# Not an operator switch. The adapter now builds atomic entry+stop orders, but
# this remains False until the payloads and stop-order reconciliation have been
# verified against a KuCoin test subaccount. Live entries stay hard-blocked.
EXCHANGE_SIDE_STOPS_IMPLEMENTED = False
PORTFOLIO_MAX_OPEN_RISK_PCT = float(os.environ.get('PORTFOLIO_MAX_OPEN_RISK_PCT', '0.5'))
PORTFOLIO_MAX_NET_BETA_X = float(os.environ.get('PORTFOLIO_MAX_NET_BETA_X', '1.5'))
PORTFOLIO_MAX_GROSS_X = float(os.environ.get('PORTFOLIO_MAX_GROSS_X', '3.0'))
TRADING_STATE_HALT_DRAWDOWN_PCT = float(os.environ.get('TRADING_STATE_HALT_DRAWDOWN_PCT', '10'))
KUCOIN_API_KEY = os.environ.get('KUCOIN_API_KEY', '')
KUCOIN_API_SECRET = os.environ.get('KUCOIN_API_SECRET', '')
KUCOIN_API_PASSPHRASE = os.environ.get('KUCOIN_API_PASSPHRASE', '')
KUCOIN_FUTURES_REST_URL = os.environ.get('KUCOIN_FUTURES_REST_URL', 'https://api-futures.kucoin.com')
KUCOIN_FUTURES_WS_URL = os.environ.get('KUCOIN_FUTURES_WS_URL', 'wss://wsapi-futures.kucoin.com')
KUCOIN_STOP_PRICE_TYPE = os.environ.get('KUCOIN_STOP_PRICE_TYPE', 'TP').upper()

# Consensus weights
CONSENSUS_WEIGHTS = {
    'momentum': 0.20,
    'volume_flow': 0.25,
    'structure': 0.20,
    'sentiment': 0.10,
    'llm_narrative': 0.10,
    'cross_asset': 0.15,
}
CONSENSUS_THRESHOLD = 65
CONSENSUS_MIN_AGREEMENT = 4  # out of 6 analysts

# Binance WebSocket
BINANCE_WS_URL = os.environ.get('BINANCE_WS_URL', 'wss://fstream.binance.com')
BINANCE_REST_URL = os.environ.get('BINANCE_REST_URL', 'https://fapi.binance.com')

# Celery Beat Schedule
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # analysts/ and consensus/ DISABLED — dead code removed from pipeline
    # 'run-fast-analysts': {'task': 'analysts.run_fast_analysts', 'schedule': 60.0},
    # 'run-medium-analysts': {'task': 'analysts.run_medium_analysts', 'schedule': 300.0},
    # 'run-llm-analyst': {'task': 'analysts.run_llm_analyst', 'schedule': 3600.0},
    # 'run-consensus': {'task': 'consensus.run_consensus', 'schedule': 60.0},
    # Position monitoring
    'monitor-positions': {
        'task': 'executor.monitor_positions',
        'schedule': 30.0,  # every 30 sec
    },
    'evaluate-risk-guards': {
        'task': 'risk.evaluate_guards',
        'schedule': 60.0,
    },
    # Data collection (REST)
    'fetch-open-interest': {
        'task': 'ingester.fetch_open_interest',
        'schedule': 300.0,  # every 5 min
    },
    'fetch-long-short-ratio': {
        'task': 'ingester.fetch_long_short_ratio',
        'schedule': 900.0,  # every 15 min
    },
    'fetch-top-trader-positions': {
        'task': 'ingester.fetch_top_trader_positions',
        'schedule': 900.0,  # every 15 min
    },
    'fetch-24h-tickers': {
        'task': 'ingester.fetch_24h_tickers',
        'schedule': 300.0,  # every 5 min
    },
    'recalculate-whale-threshold': {
        'task': 'ingester.recalculate_whale_threshold',
        'schedule': 3600.0,  # every 1 hour
    },
    'check-data-freshness': {
        'task': 'ingester.check_data_freshness',
        'schedule': 120.0,   # every 2 minutes — catches stale data fast
    },
    'prune-order-book-snapshots': {
        'task': 'ingester.prune_order_book_snapshots',
        'schedule': crontab(hour=2, minute=30),
    },
    'prune-agg-trades': {
        'task': 'ingester.prune_agg_trades',
        'schedule': crontab(hour=2, minute=40),
    },
    'update-news-calendar': {
        'task': 'risk.update_news_calendar',
        'schedule': 21600.0,  # every 6 hours
    },
    'l1-scan-all-symbols': {
        'task': 'l1_filter.scan_all_symbols',
        'schedule': 60.0,   # every 1 min
    },
    'resolve-s12ai-shadow': {
        'task': 'evaluator.resolve_s12ai_shadow',
        'schedule': 3600.0,
    },
    'run-auction-shadow-cycle': {
        'task': 'l2_agents.run_auction_shadow_cycle',
        'schedule': 300.0,
    },
    'resolve-auction-shadow-plans': {
        'task': 'l2_agents.resolve_auction_shadow_plans',
        'schedule': 60.0,
    },
    'setup-search-cycle': {
        'task': 'l1_filter.run_setup_search_cycle',
        # At each 15m close; journal keys make overlaps with the local loop harmless.
        'schedule': crontab(minute='0,15,30,45'),
    },
    # Risk resets
    'daily-risk-reset': {
        'task': 'executor.daily_reset',
        'schedule': crontab(hour=0, minute=0),
    },
    'weekly-risk-reset': {
        'task': 'executor.weekly_reset',
        'schedule': crontab(hour=0, minute=0, day_of_week=1),
    },
    # EOD discipline
    'eod-soft-block': {
        'task': 'executor.block_new_entries_eod',
        'schedule': crontab(hour=18, minute=0),  # 18:00 UTC — no new entries
    },
    'eod-force-close': {
        'task': 'executor.force_close_all',
        'schedule': crontab(hour=22, minute=0),  # 22:00 UTC — close all positions
    },
    # FCM_SAFE25 paper-forward monitor — public data, zero order placement.
    'carry-monitor-monthly-decision': {
        'task': 'carry_monitor.evaluate_monthly_decision',
        'schedule': crontab(hour=1, minute=0, day_of_month=1),
    },
    'carry-monitor-accrue-funding': {
        'task': 'carry_monitor.accrue_funding',
        'schedule': 3600.0,  # every hour — Binance settles every 8h
    },
    'carry-monitor-safety': {
        'task': 'carry_monitor.monitor_safety',
        'schedule': crontab(minute='*'),
    },
    # S20 paper scalp monitor — real prices, zero orders ever placed.
    'scalp-monitor-evaluate-signal': {
        'task': 'scalp_monitor.evaluate_signal',
        'schedule': crontab(minute='1,16,31,46'),  # shortly after each 15m close
    },
    'scalp-monitor-manage-position': {
        'task': 'scalp_monitor.manage_open_position',
        'schedule': 120.0,  # every 2 minutes
    },
}
