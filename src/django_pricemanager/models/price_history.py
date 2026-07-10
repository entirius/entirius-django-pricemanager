# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.conf import settings
from django.db import models
from django.utils import timezone

from django_pricemanager.models.choices import SOURCE_CHOICES


class PriceHistory(models.Model):
    """Append-only log. Every price change = one row. Never UPDATE, only INSERT."""

    product = models.ForeignKey("ProductRepresentation", on_delete=models.CASCADE, related_name="price_history")
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE)
    country = models.ForeignKey("django_regional.Country", on_delete=models.CASCADE)
    currency = models.ForeignKey("django_regional.Currency", on_delete=models.CASCADE)
    customer_representation = models.ForeignKey(
        "CustomerRepresentation", on_delete=models.SET_NULL, null=True, blank=True
    )
    gross_value = models.DecimalField(max_digits=19, decimal_places=4)
    net_value = models.DecimalField(max_digits=19, decimal_places=4)
    special_gross_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    special_net_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    tax_rate = models.ForeignKey("TaxRate", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # default=timezone.now (not auto_now_add) so backfill can set custom timestamps
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "pricemanager_pricehistory"
        verbose_name = "price history"
        verbose_name_plural = "price history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "channel", "country", "currency", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"PriceHistory({self.product_id}, {self.source}, {self.created_at})"
