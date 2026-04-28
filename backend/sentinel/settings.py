import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

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
_db_path = os.environ.get('DB_PATH', str(BASE_DIR / 'db.sqlite3'))
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _db_path,
    }
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
TRADING_MODE = os.environ.get('TRADING_MODE', 'paper')  # paper, signal_only, semi_auto, full_auto
BINANCE_TESTNET = os.environ.get('BINANCE_TESTNET', 'True').lower() in ('true', '1')
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY', '')

# Risk params
MAX_RISK_PER_TRADE = float(os.environ.get('MAX_RISK_PER_TRADE', '0.005'))
MAX_DAILY_DRAWDOWN = float(os.environ.get('MAX_DAILY_DRAWDOWN', '0.20'))
MAX_DAILY_PORTFOLIO_DRAWDOWN = float(os.environ.get('MAX_DAILY_PORTFOLIO_DRAWDOWN', '0.20'))
MAX_WEEKLY_DRAWDOWN = float(os.environ.get('MAX_WEEKLY_DRAWDOWN', '0.07'))
MAX_OPEN_POSITIONS = int(os.environ.get('MAX_OPEN_POSITIONS', '3'))
PROFIT_TO_SPOT_RATIO = float(os.environ.get('PROFIT_TO_SPOT_RATIO', '0.10'))
DEFAULT_MARGIN_MODE = os.environ.get('DEFAULT_MARGIN_MODE', 'isolated')
MAX_LEVERAGE = int(os.environ.get('MAX_LEVERAGE', '10'))
MAX_HIGH_CONVICTION_LEVERAGE = int(os.environ.get('MAX_HIGH_CONVICTION_LEVERAGE', '20'))
MAX_MARGIN_PER_TRADE_PCT = float(os.environ.get('MAX_MARGIN_PER_TRADE_PCT', '0.15'))
MIN_LIQUIDATION_BUFFER_R = float(os.environ.get('MIN_LIQUIDATION_BUFFER_R', '3.0'))
MAINTENANCE_MARGIN_RATE = float(os.environ.get('MAINTENANCE_MARGIN_RATE', '0.005'))
INITIAL_BALANCE = float(os.environ.get('INITIAL_BALANCE', '10000'))
EXCHANGE_NAME = os.environ.get('EXCHANGE_NAME', 'kucoin').lower()
LIVE_TRADING_ENABLED = os.environ.get('LIVE_TRADING_ENABLED', 'False').lower() in ('true', '1')
KUCOIN_API_KEY = os.environ.get('KUCOIN_API_KEY', '')
KUCOIN_API_SECRET = os.environ.get('KUCOIN_API_SECRET', '')
KUCOIN_API_PASSPHRASE = os.environ.get('KUCOIN_API_PASSPHRASE', '')
KUCOIN_FUTURES_REST_URL = os.environ.get('KUCOIN_FUTURES_REST_URL', 'https://api-futures.kucoin.com')
KUCOIN_FUTURES_WS_URL = os.environ.get('KUCOIN_FUTURES_WS_URL', 'wss://wsapi-futures.kucoin.com')

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
BINANCE_WS_URL = 'wss://fstream.binance.com'
BINANCE_REST_URL = 'https://fapi.binance.com'

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
    'update-news-calendar': {
        'task': 'risk.update_news_calendar',
        'schedule': 21600.0,  # every 6 hours
    },
    'l1-scan-all-symbols': {
        'task': 'l1_filter.scan_all_symbols',
        'schedule': 60.0,   # every 1 min
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
}
