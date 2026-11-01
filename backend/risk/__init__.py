# Expose update_news_calendar as a Celery task
from celery import shared_task

@shared_task(name='risk.update_news_calendar')
def update_news_calendar():
    from .news_calendar import update_news_calendar as _update
    _update()


@shared_task(name='risk.evaluate_guards')
def evaluate_guards():
    """Independent periodic risk-state evaluation."""
    from .trading_state import evaluate_guards as _evaluate
    state = _evaluate()
    return {'state': state.state, 'reason': state.reason}
