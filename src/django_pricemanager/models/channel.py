# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from enum import IntEnum

from django.db import models
from django_regional.models import Country
from idx_normalizator import normalize_idx, validate_idx
from int_enum_choices import IntEnumChoices


class CalculateDirectionEnum(IntEnum):
    FROM_NET_TO_GROSS = 0
    FROM_GROSS_TO_NET = 1


class CalculateDirection(IntEnumChoices):
    enumClass = CalculateDirectionEnum

    labels = {
        CalculateDirectionEnum.FROM_NET_TO_GROSS: "Calculate prices from netto to gross",
        CalculateDirectionEnum.FROM_GROSS_TO_NET: "Calculate prices from gross to netto",
    }


class Channel(models.Model):
    idx = models.CharField(max_length=128)
    name = models.CharField(max_length=128)
    calculate_direction = models.PositiveSmallIntegerField(
        choices=CalculateDirection.choices(), blank=False, null=False, default=CalculateDirectionEnum.FROM_NET_TO_GROSS
    )
    # Calculate countries is to narrow down the countries from the general tax class. If empty, all countries from tax_class are used.
    calculate_countries = models.ManyToManyField(Country, blank=True, related_name="calculate_countries_channels")
    # Default country = the reference country for price editing. Others are derived via tax rates.
    default_country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    objects = models.Manager()

    class Meta:
        ordering = ["idx"]
        verbose_name_plural = "channels"

    def __str__(self):
        return self.idx

    def save(self, *args, **kwargs):
        if self.idx is None:
            self.idx = normalize_idx(self.name)
        validate_idx(self.idx)
        super().save(*args, **kwargs)
