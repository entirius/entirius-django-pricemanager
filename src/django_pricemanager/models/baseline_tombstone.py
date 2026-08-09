# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_utils.models.base_model import BaseModel


class BaselineTombstone(BaseModel):
    """Exclusion marker: baseline recalc skips this (product, channel) until an admin removes it.

    Written by price_edit_service.delete_prices() when the channel has baseline auto-pricing
    enabled — without it, the next PurchaseCost save would silently resurrect the deleted price.
    """

    product = models.ForeignKey("ProductRepresentation", on_delete=models.CASCADE, related_name="baseline_tombstones")
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="baseline_tombstones")
    # created_at / modified_at provided by BaseModel.

    class Meta:
        db_table = "pricemanager_baselinetombstone"
        verbose_name = "baseline tombstone"
        verbose_name_plural = "baseline tombstones"
        constraints = [
            models.UniqueConstraint(fields=["product", "channel"], name="unique_baseline_tombstone"),
        ]

    def __str__(self) -> str:
        return f"BaselineTombstone({self.product.sku}, {self.channel.idx})"
