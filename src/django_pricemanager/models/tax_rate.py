# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django.db import models
from django_regional.models import Country

from django_pricemanager.models.managers.country import CountryAwareManager


class TaxRate(models.Model):
    tax_class = models.ForeignKey(
        "TaxClass", related_name="tax_rates", null=False, blank=False, on_delete=models.CASCADE
    )
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    rate = models.DecimalField(max_digits=5, decimal_places=4)

    objects = CountryAwareManager()

    # NOTE: gross_price(net_price(x)) != x

    @property
    def percent_rate(self) -> Decimal:
        return self.rate * Decimal("100")

    def net_price(self, price_gross: Decimal):
        return round(Decimal(price_gross) / (1 + Decimal(self.rate)), 2)

    def gross_price(self, price_net: Decimal):
        return round(Decimal(price_net) * (1 + Decimal(self.rate)), 2)

    def __str__(self):
        return f"[{self.country.iso2}] {self.rate} - {self.tax_class}"

    class Meta:
        unique_together = ("tax_class", "country")
