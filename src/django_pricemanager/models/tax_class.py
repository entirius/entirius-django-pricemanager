# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from idx_normalizator import normalize_idx, validate_idx


class TaxClass(models.Model):
    idx = models.CharField(max_length=64, editable=True, blank=False, null=False, unique=True)
    name = models.CharField(max_length=64)
    source_file = models.FileField(blank=True, null=True, upload_to="pricelists")
    objects = models.Manager()

    class Meta:
        ordering = []
        verbose_name_plural = "tax classes"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.idx is None:
            self.idx = normalize_idx(self.name)
        validate_idx(self.idx)
        return super().save(*args, **kwargs)
