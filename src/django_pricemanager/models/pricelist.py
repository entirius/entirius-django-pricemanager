# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from enum import IntEnum

from django.db import models
from django_regional.models import Country
from int_enum_choices import IntEnumChoices

from django_pricemanager.models.managers.country import CountryAwareManager


class PriceListStatusEnum(IntEnum):
    ERROR = 0
    READY = 1
    IN_PROGRESS = 2


class PriceListStatus(IntEnumChoices):
    enumClass = PriceListStatusEnum
    labels = {
        PriceListStatusEnum.ERROR: "Error",
        PriceListStatusEnum.READY: "Ready",
        PriceListStatusEnum.IN_PROGRESS: "In progress",
    }


class PriceList(models.Model):
    sale_channel = models.ForeignKey(
        "SaleChannel", related_name="price_lists", null=False, blank=False, on_delete=models.CASCADE
    )
    currency = models.ForeignKey(
        "django_regional.Currency",
        related_name="pricelists_currency_ref",
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    name = models.CharField(max_length=128, null=False, blank=True, default="")
    source_file = models.FileField(upload_to="pricelists", blank=True)
    status = models.SmallIntegerField(
        choices=PriceListStatus.choices(),
        db_index=True,
        blank=False,
        null=False,
        default=PriceListStatusEnum.IN_PROGRESS,
    )
    created_on = models.DateTimeField(auto_now_add=True)
    modified_on = models.DateTimeField(auto_now=True)

    objects = CountryAwareManager()

    class Meta:
        get_latest_by = "created_on"

    def __str__(self):
        partial = self.name if self.name else str(self.channel)
        return f"{partial} {self.created_on}"

    def get_pricelist_id(self):
        return f"{self.country.iso2}_{self.channel.name}_{self.id}"

    def get_as_csv(self):
        headers = ["product", "gross", "net", "special_gross", "special_net", "tax_class_idx"]
        datalist = []
        for item in self.get_dataset():
            datalist.append(item)
        return headers, datalist

    def get_dataset(self):
        return_list = []
        for price in self.prices.all():
            item = {
                "product": price.product.sku,
                "tax_class_idx": price.product.tax_class.idx,
                "gross": price.gross_value,
                "net": price.net_value,
                "special_gross": price.special_gross_value,
                "special_net": price.special_net_value,
            }
            return_list.append(item)
        return return_list
