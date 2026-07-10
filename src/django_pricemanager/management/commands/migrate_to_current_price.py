# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Migrate PriceList snapshots to CurrentPrice + PriceHistory.

Usage:
    python manage.py migrate_to_current_price                       # populate from latest READY snapshots
    python manage.py migrate_to_current_price --backfill-days=90    # backfill PriceHistory
    python manage.py migrate_to_current_price --attrs-only          # migrate attribute pricing M2M
    python manage.py migrate_to_current_price --verify-only         # compare old vs new
    python manage.py migrate_to_current_price --dry-run             # log actions without writing
"""

from django.core.management.base import BaseCommand

from django_pricemanager.services.migration_service import (
    backfill_price_history,
    migrate_price_attributes,
    populate_current_prices,
    verify_migration,
)


class Command(BaseCommand):
    help = "Migrate PriceList snapshots to CurrentPrice + PriceHistory"

    def add_arguments(self, parser):
        parser.add_argument("--backfill-days", type=int, default=0, help="Backfill PriceHistory for N days (0=skip)")
        parser.add_argument("--attrs-only", action="store_true", help="Migrate PriceAttribute M2M only")
        parser.add_argument("--verify-only", action="store_true", help="Verify migration without changes")
        parser.add_argument("--dry-run", action="store_true", help="Log actions without writing to DB")
        parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for bulk operations")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        if options["verify_only"]:
            mismatches = verify_migration()
            if mismatches:
                self.stderr.write(f"FAIL: {len(mismatches)} mismatches found:")
                for m in mismatches[:50]:
                    self.stderr.write(f"  {m}")
            else:
                self.stdout.write(self.style.SUCCESS("OK: 0 mismatches"))
            return

        if options["attrs_only"]:
            count = migrate_price_attributes(batch_size=batch_size, dry_run=dry_run)
            self.stdout.write(self.style.SUCCESS(f"Migrated {count} CurrentPriceAttribute rows (dry_run={dry_run})"))
            return

        # Default: populate CurrentPrice
        count = populate_current_prices(batch_size=batch_size, dry_run=dry_run)
        self.stdout.write(self.style.SUCCESS(f"Populated {count} CurrentPrice rows (dry_run={dry_run})"))

        # Backfill PriceHistory if requested
        if options["backfill_days"] > 0:
            history_count = backfill_price_history(
                days=options["backfill_days"], batch_size=batch_size, dry_run=dry_run
            )
            self.stdout.write(self.style.SUCCESS(f"Backfilled {history_count} PriceHistory rows (dry_run={dry_run})"))
