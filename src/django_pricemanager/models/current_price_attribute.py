# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class CurrentPriceAttribute(models.Model):
    """Through table for CurrentPrice M2M to AttributeRepresentation."""

    current_price = models.ForeignKey("CurrentPrice", on_delete=models.CASCADE, related_name="price_attrs")
    attr = models.ForeignKey("AttributeRepresentation", on_delete=models.CASCADE, related_name="current_price_attrs")

    class Meta:
        db_table = "pricemanager_currentpriceattribute"
        unique_together = ("current_price", "attr")

    def __str__(self) -> str:
        return f"CurrentPriceAttribute({self.current_price_id}, {self.attr_id})"
