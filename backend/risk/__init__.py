# Expose update_news_calendar as a Celery task
from celery import shared_task

@shared_task(name='risk.update_news_calendar')
def update_news_calendar():
    from .news_calendar import update_news_calendar as _update
    _update()
