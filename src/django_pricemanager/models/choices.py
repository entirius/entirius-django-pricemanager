# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class PriceSource(models.TextChoices):
    CSV_IMPORT = "csv_import", "CSV Import"
    API = "api", "API"
    GENERATION = "generation", "Generation"
    ADMIN_EDIT = "admin_edit", "Admin Edit"
    TAX_RATE_CHANGE = "tax_rate_change", "Tax Rate Change"
    MIGRATION = "migration", "Migration"
    MIGRATION_BACKFILL = "migration_backfill", "Migration Backfill"
    SUPPLIER_COST = "supplier_cost", "Supplier Cost"


# Backward compat alias — used in models CharField(choices=...)
SOURCE_CHOICES = PriceSource.choices
