# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.validators import MinValueValidator
from django.db import models
from django_utils.models.base_model import BaseModel


class PurchaseCost(BaseModel):
    """Buy-side cost per (product, channel, country, currency).

    Kept SEPARATE from CurrentPrice on purpose: a supplier cost is what we PAY,
    not what we SELL for. Writing it here (instead of into CurrentPrice.net_value)
    means an incoming supplier cost never creates a sellable price — the product
    stays unpriced until an operator sets a CurrentPrice. Margin is then
    CurrentPrice.net_value vs PurchaseCost.net_cost.
    """

    product = models.ForeignKey("ProductRepresentation", on_delete=models.CASCADE, related_name="purchase_costs")
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="purchase_costs")
    country = models.ForeignKey("django_regional.Country", on_delete=models.CASCADE)
    currency = models.ForeignKey("django_regional.Currency", on_delete=models.CASCADE)
    net_cost = models.DecimalField(max_digits=19, decimal_places=4, validators=[MinValueValidator(0)])
    # Which supplier this cost came from (preferred supplier at write time).
    supplier_idx = models.CharField(max_length=64, null=True, blank=True, db_index=True)  # noqa: DJ001 — FK-string ref to Supplier.idx
    # created_at / modified_at provided by BaseModel.

    class Meta:
        db_table = "pricemanager_purchasecost"
        verbose_name = "purchase cost"
        verbose_name_plural = "purchase costs"
        constraints = [
            models.UniqueConstraint(fields=["product", "channel", "country", "currency"], name="unique_purchase_cost")
        ]
        indexes = [models.Index(fields=["product", "channel"]), models.Index(fields=["product"])]

    def __str__(self) -> str:
        return f"PurchaseCost({self.product_id}, {self.channel_id}, {self.net_cost})"
