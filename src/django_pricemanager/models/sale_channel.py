# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_regional.models import Country
from idx_normalizator import normalize_idx, validate_idx

from django_pricemanager.models.managers.country import CountryAwareManager


class SaleChannel(models.Model):
    idx = models.CharField(max_length=128)
    name = models.CharField(max_length=128)

    channel = models.ForeignKey(
        "Channel", related_name="sale_channels", null=False, blank=False, on_delete=models.CASCADE
    )
    is_only_for_verified_user = models.BooleanField(default=False, null=True, blank=True)
    PRICE_SOURCE_FAKE = "fake"
    PRICE_SOURCE_CSV = "csv"
    PRICE_SOURCE_GENERATED = "generated"
    PRICE_SOURCE_API = "api"
    PRICE_MANAGERS = [
        (PRICE_SOURCE_FAKE, "Fake"),
        (PRICE_SOURCE_CSV, "CSV"),
        (PRICE_SOURCE_GENERATED, "Generated"),
        (PRICE_SOURCE_API, "API"),
    ]
    price_source = models.CharField(max_length=32, choices=PRICE_MANAGERS, default=PRICE_SOURCE_FAKE)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    customer_representation = models.ForeignKey(
        "CustomerRepresentation", related_name="sale_channels", null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = CountryAwareManager()

    class Meta:
        ordering = ["idx"]
        verbose_name_plural = "sale channels"

    def __str__(self):
        return self.idx

    @staticmethod
    def name_by_channel_and_country(name, country):
        country_code = ""
        if isinstance(country, Country):
            country_code = country.iso2
        elif isinstance(country, str):
            country_code = country
        return " ".join([name, country_code])

    def save(self, *args, **kwargs):
        if self.idx is None:
            self.idx = normalize_idx(str(self.name))
        validate_idx(self.idx)
        super().save(*args, **kwargs)
