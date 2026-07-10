# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Backfill synthetic PriceHistory rows for omnibus demo seed.

For every CurrentPrice with `special_gross_value IS NOT NULL`, insert one
PriceHistory row at `gross_value * 1.5`, dated 10 days ago. This gives the
omnibus calculator (EU 30-day lowest price) something to find, so the
storefront has meaningful "lowest price" data to display on promo SKUs.

NOT an audit log entry — these rows are demo/seed data. Idempotent: deletes
existing rows with `source='demo_seed_backfill'` first, then re-inserts.

Usage:
    python manage.py backfill_demo_price_history
    python manage.py backfill_demo_price_history --multiplier 2.0 --days 14
    python manage.py backfill_demo_price_history --dry-run
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from django_pricemanager.models import CurrentPrice, PriceHistory

DEMO_SOURCE = "demo_seed_backfill"


class Command(BaseCommand):
    help = "Backfill demo PriceHistory rows so omnibus calc has 30-day price data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--multiplier",
            type=float,
            default=1.5,
            help="Multiplier applied to current gross/net (default: 1.5)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=10,
            help="Backdate inserted rows by N days (default: 10)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="bulk_create batch size (default: 1000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log counts without writing",
        )

    def handle(self, *args, **options):
        multiplier = Decimal(str(options["multiplier"]))
        backdate = timezone.now() - timedelta(days=options["days"])
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        eligible = CurrentPrice.objects.filter(special_gross_value__isnull=False)
        existing = PriceHistory.objects.filter(source=DEMO_SOURCE)

        self.stdout.write(f"Eligible CurrentPrice rows: {eligible.count()} | Existing demo PH rows: {existing.count()}")

        if dry_run:
            self.stdout.write("Dry run — no changes.")
            return

        with transaction.atomic():
            deleted, _ = existing.delete()
            rows = [
                PriceHistory(
                    product_id=cp.product_id,
                    channel_id=cp.channel_id,
                    country_id=cp.country_id,
                    currency_id=cp.currency_id,
                    gross_value=cp.gross_value * multiplier,
                    net_value=cp.net_value * multiplier,
                    tax_rate_id=cp.tax_rate_id,
                    source=DEMO_SOURCE,
                    created_at=backdate,
                )
                for cp in eligible.iterator(chunk_size=batch_size)
            ]
            PriceHistory.objects.bulk_create(rows, batch_size=batch_size)

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} stale demo rows, inserted {len(rows)} fresh rows "
                f"(multiplier={multiplier}, backdated to {backdate.date()})."
            )
        )
