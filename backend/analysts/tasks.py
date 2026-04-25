"""Celery tasks for running analyst modules periodically."""
import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

ALL_ANALYSTS = {
    'momentum': 'analysts.momentum.MomentumAnalyst',
    'volume_flow': 'analysts.volume_flow.VolumeFlowAnalyst',
    'structure': 'analysts.structure.StructureAnalyst',
    'sentiment': 'analysts.sentiment.SentimentAnalyst',
    'llm_narrative': 'analysts.llm_narrative.LLMNarrativeAnalyst',
    'cross_asset': 'analysts.cross_asset.CrossAssetAnalyst',
}


def _get_analyst(name):
    """Dynamically import and instantiate an analyst."""
    module_path = ALL_ANALYSTS[name]
    module_name, class_name = module_path.rsplit('.', 1)
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def _save_signal(signal):
    """Persist an analyst signal to the database."""
    from .models import AnalystSignalRecord
    AnalystSignalRecord.objects.create(
        analyst_name=signal.analyst_name,
        symbol=signal.symbol,
        score=signal.score,
        bias=signal.bias.value if hasattr(signal.bias, 'value') else signal.bias,
        confidence=signal.confidence,
        reasoning=signal.reasoning,
        metadata=signal.metadata,
    )


@shared_task(name='analysts.run_fast_analysts')
def run_fast_analysts():
    """Run momentum and volume analysts — every 1 min."""
    for name in ['momentum', 'volume_flow']:
        _run_single_analyst(name)


@shared_task(name='analysts.run_medium_analysts')
def run_medium_analysts():
    """Run structure, sentiment, cross-asset — every 5 min."""
    for name in ['structure', 'sentiment', 'cross_asset']:
        _run_single_analyst(name)


@shared_task(name='analysts.run_llm_analyst')
def run_llm_analyst():
    """Run LLM narrative analyst — every 1 hour."""
    _run_single_analyst('llm_narrative')


@shared_task(name='analysts.run_all_analysts')
def run_all_analysts():
    """Run all analysts for all pairs — used for manual triggers."""
    for name in ALL_ANALYSTS:
        _run_single_analyst(name)


def _run_single_analyst(name):
    """Run a single analyst for all configured pairs."""
    try:
        analyst = _get_analyst(name)
        for symbol in settings.TRADING_PAIRS:
            try:
                signal = analyst.analyze(symbol)
                _save_signal(signal)
                logger.info(f"{name} | {symbol} | score={signal.score:+.0f} | {signal.bias.value}")
            except Exception as e:
                logger.error(f"Analyst {name} error for {symbol}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to load analyst {name}: {e}")
