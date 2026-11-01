"""One-off, verified copy of the legacy SQLite database into Postgres.

Usage (ingester and watchdog stopped):
    SQLITE_SOURCE_PATH=/path/db.sqlite3 DB_ENGINE=postgres ... \
        python manage.py copy_sqlite_to_postgres
    ... python manage.py copy_sqlite_to_postgres --verify-only

The target schema must already be migrated.  All target model tables are
truncated and refilled inside ONE transaction with original primary keys, then
sequences are reset and per-table row counts are verified.  Any mismatch or
error rolls everything back.  The SQLite file is only read.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction

SOURCE = 'sqlite_source'
TARGET = 'default'


def _copyable_models():
    source_tables = set(connections[SOURCE].introspection.table_names())
    return [
        model for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy
        and model._meta.db_table in source_tables
    ]


@contextmanager
def _preserve_timestamps(models):
    """bulk_create runs pre_save(add=True), which rewrites auto_now(_add)."""
    saved = []
    for model in models:
        for field in model._meta.concrete_fields:
            if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
                saved.append((field, field.auto_now, field.auto_now_add))
                field.auto_now = field.auto_now_add = False
    try:
        yield
    finally:
        for field, auto_now, auto_now_add in saved:
            field.auto_now, field.auto_now_add = auto_now, auto_now_add


def _counts(models, alias):
    return {model._meta.db_table: model._base_manager.using(alias).count() for model in models}


class Command(BaseCommand):
    help = 'Copy all installed-model rows from SQLITE_SOURCE_PATH into Postgres, verified.'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, default=5000)
        parser.add_argument('--verify-only', action='store_true')

    def handle(self, *args, **options):
        if SOURCE not in connections.databases:
            raise CommandError('Set SQLITE_SOURCE_PATH to the legacy db.sqlite3 file.')
        if connections[TARGET].vendor != 'postgresql':
            raise CommandError('Target "default" is not Postgres; set DB_ENGINE=postgres.')
        if connections[SOURCE].vendor != 'sqlite':
            raise CommandError('Source alias is not SQLite.')

        models = _copyable_models()
        if not options['verify_only']:
            self._copy(models, options['batch'])
        self._verify(models)

    def _copy(self, models, batch_size):
        target = connections[TARGET]
        tables = [model._meta.db_table for model in models]
        started = time.monotonic()
        with transaction.atomic(using=TARGET), _preserve_timestamps(models):
            with target.cursor() as cursor:
                quoted = ', '.join(target.ops.quote_name(t) for t in tables)
                cursor.execute(f'TRUNCATE {quoted} RESTART IDENTITY CASCADE')
                # FKs are DEFERRABLE INITIALLY DEFERRED: insert order is free.
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')
            for model in models:
                copied = 0
                buffer = []
                rows = model._base_manager.using(SOURCE).order_by('pk').iterator(
                    chunk_size=batch_size,
                )
                for obj in rows:
                    obj._state.db = TARGET
                    obj._state.adding = True
                    buffer.append(obj)
                    if len(buffer) >= batch_size:
                        model._base_manager.using(TARGET).bulk_create(buffer)
                        copied += len(buffer)
                        buffer = []
                if buffer:
                    model._base_manager.using(TARGET).bulk_create(buffer)
                    copied += len(buffer)
                if copied:
                    self.stdout.write(f'{model._meta.db_table}: {copied}')
            with target.cursor() as cursor:
                for statement in target.ops.sequence_reset_sql(no_style(), models):
                    cursor.execute(statement)
            mismatches = self._mismatches(models)
            if mismatches:
                raise CommandError(f'Row-count mismatch, rolled back: {mismatches}')
        self.stdout.write(f'Copied {len(models)} tables in {time.monotonic() - started:.1f}s')

    def _mismatches(self, models):
        source, target = _counts(models, SOURCE), _counts(models, TARGET)
        return {t: (source[t], target[t]) for t in source if source[t] != target[t]}

    def _verify(self, models):
        mismatches = self._mismatches(models)
        if mismatches:
            raise CommandError(f'Row-count mismatch: {mismatches}')
        total = sum(_counts(models, TARGET).values())
        self.stdout.write(self.style.SUCCESS(
            f'VERIFIED: {len(models)} tables, {total} rows identical in count.',
        ))
