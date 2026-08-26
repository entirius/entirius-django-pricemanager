# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_utils.models.base_model import BaseModel

from django_pricemanager.models.choices import PriceSource


class PriceWriteEnforceMode(models.TextChoices):
    CLAMP = "clamp", "Clamp to bounds"
    REJECT = "reject", "Reject write"


class PriceSourcePolicy(BaseModel):
    """Per-source write policy consumed by services.price_write_guard.

    recalc_overwritable: whether a BASELINE recalc may overwrite CurrentPrice rows
    currently stamped with this source (default False = fill-only).
    enforce_mode: how bounds violations are handled for writes performed BY this source.
    Missing rows fall back to guard defaults (automatons clamp, admin_edit rejects) —
    seeding this table is optional.
    """

    source = models.CharField(max_length=32, choices=PriceSource.choices, unique=True)
    recalc_overwritable = models.BooleanField(default=False)
    enforce_mode = models.CharField(
        max_length=16, choices=PriceWriteEnforceMode.choices, default=PriceWriteEnforceMode.CLAMP
    )

    class Meta:
        db_table = "pricemanager_pricesourcepolicy"
        verbose_name = "price source policy"
        verbose_name_plural = "price source policies"

    def __str__(self) -> str:
        return f"{self.source} (recalc_overwritable={self.recalc_overwritable}, enforce_mode={self.enforce_mode})"
