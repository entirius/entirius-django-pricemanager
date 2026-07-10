# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from django_pricemanager.models.managers import PriceManager
from django_pricemanager.settings import APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES


class PriceAttribute(models.Model):
    price = models.ForeignKey(
        "Price", related_name="price_attributes", null=False, blank=False, on_delete=models.CASCADE
    )
    attr = models.ForeignKey(
        "AttributeRepresentation", related_name="price_attributes", null=False, blank=False, on_delete=models.CASCADE
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["price", "attr"], name="unique_price_attribute")]

    def __str__(self):
        return f"{self.price} - {self.attr}"


class Price(models.Model):
    pricelist = models.ForeignKey("PriceList", related_name="prices", null=False, blank=False, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "ProductRepresentation", related_name="prices", null=True, blank=True, on_delete=models.CASCADE
    )
    # for custom purposes, price can be assigned to set of attributes
    attrs = models.ManyToManyField(
        "AttributeRepresentation", related_name="prices_attrs", blank=True, through="PriceAttribute"
    )
    # for bundle purposes, price can be assigned to simple product that is a part of product bundle
    product_parent = models.ForeignKey(
        "ProductRepresentation", related_name="parent_prices", null=True, blank=True, on_delete=models.CASCADE
    )
    net_value = models.DecimalField(max_digits=19, decimal_places=4)
    gross_value = models.DecimalField(max_digits=19, decimal_places=4)
    special_net_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    special_gross_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    tax_rate = models.ForeignKey("TaxRate", related_name="prices", null=True, blank=True, on_delete=models.SET_NULL)
    special_from_date = models.DateTimeField(blank=True, null=True, default=None)
    special_to_date = models.DateTimeField(blank=True, null=True, default=None)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    objects = PriceManager()

    def clean(self):
        if not self.product and not self.attrs.exists():
            raise ValidationError("Either 'product' or 'attr' must be specified for a Price.")

    @property
    def created_on(self):
        return self.pricelist.created_on

    def is_egible_for_special_price(self) -> bool:
        current_date = timezone.now()
        if self.special_from_date and self.special_to_date:
            return all([self.special_from_date < current_date, self.special_to_date > current_date])
        elif self.special_from_date:
            return self.special_from_date < current_date
        elif self.special_to_date:
            return self.special_to_date > current_date
        else:
            return APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES

    def get_0_vat_standard_price(self, round_price: int = 2):
        product = self.product
        attrs = list(self.attrs.all()) if not product else []
        first_attr = attrs[0] if attrs else None

        item = {
            "product": product.sku if product else [attr.idx for attr in attrs],
            "tax_class": "0 VAT",
            "gross": round(Decimal(self.net_value), round_price) if self.net_value else self.net_value,
            "net": round(Decimal(self.net_value), round_price) if self.net_value else self.net_value,
            "special_gross": (
                round(Decimal(self.special_net_value), round_price)
                if self.special_gross_value
                else self.special_gross_value
            ),
            "special_net": (
                round(Decimal(self.special_net_value), round_price)
                if self.special_net_value
                else self.special_net_value
            ),
            "tax_rate": Decimal(0.00),
            "special_from_date": self.special_from_date,
            "special_to_date": self.special_to_date,
            "is_egible_for_special_price": self.is_egible_for_special_price(),
            "uid": (
                self.pricelist.sale_channel.customer_representation.uid
                if self.pricelist.sale_channel.customer_representation
                else None
            ),
        }
        return item

    def get_standard_price(self, round_price: int = 2):
        product = self.product
        attrs = list(self.attrs.all()) if not product else []
        first_attr = attrs[0] if attrs else None

        item = {
            "product": product.sku if product else [attr.idx for attr in attrs],
            "tax_class": product.tax_class.idx if product else first_attr.tax_class.idx,
            "gross": round(Decimal(self.gross_value), round_price) if self.gross_value else self.gross_value,
            "net": round(Decimal(self.net_value), round_price) if self.net_value else self.net_value,
            "special_gross": (
                round(Decimal(self.special_gross_value), round_price)
                if self.special_gross_value
                else self.special_gross_value
            ),
            "special_net": (
                round(Decimal(self.special_net_value), round_price)
                if self.special_net_value
                else self.special_net_value
            ),
            "tax_rate": self.tax_rate.rate if self.tax_rate is not None else None,
            "special_from_date": self.special_from_date,
            "special_to_date": self.special_to_date,
            "is_egible_for_special_price": self.is_egible_for_special_price(),
            "uid": (
                self.pricelist.sale_channel.customer_representation.uid
                if self.pricelist.sale_channel.customer_representation
                else None
            ),
        }
        return item
