# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from idx_normalizator import normalize_idx


class AttributeRepresentation(models.Model):
    tax_class = models.ForeignKey(
        "TaxClass", related_name="attr_representations", null=False, blank=False, on_delete=models.CASCADE
    )
    idx = models.CharField(max_length=128, null=False)
    objects = models.Manager()

    def save(self, *args, **kwargs):
        normalize_idx(self.idx)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.idx

    class Meta:
        ordering = ["idx"]
        verbose_name_plural = "attr representations"
        constraints = [UniqueConstraint(Lower("idx"), name="unique_pricemanager_product_idx")]
