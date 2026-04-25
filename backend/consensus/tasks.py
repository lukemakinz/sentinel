"""Celery tasks for consensus engine."""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(name='consensus.run_consensus')
def run_consensus():
    """Run consensus evaluation for all pairs — every 1 min."""
    from .engine import ConsensusEngine
    engine = ConsensusEngine()
    results = engine.evaluate_all()

    for symbol, signal in results.items():
        if signal.tier in ('SIGNAL', 'HIGH_CONVICTION'):
            # Trigger risk check and potential execution
            from executor.tasks import process_signal
            process_signal.delay(signal.id)
