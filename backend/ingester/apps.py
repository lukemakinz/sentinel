from django.apps import AppConfig


class IngesterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ingester'
    verbose_name = 'Data Ingester'
