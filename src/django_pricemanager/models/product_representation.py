# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from idx_normalizator import validate_sku


class ProductRepresentation(models.Model):
    tax_class = models.ForeignKey(
        "TaxClass", related_name="product_representations", null=False, blank=False, on_delete=models.CASCADE
    )
    sku = models.CharField(max_length=128, null=False)
    objects = models.Manager()

    def save(self, *args, **kwargs):
        validate_sku(self.sku)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.sku

    class Meta:
        ordering = ["sku"]
        verbose_name_plural = "products representations"
        constraints = [UniqueConstraint(Lower("sku"), name="unique_pricemanager_product_sku")]
