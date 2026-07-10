# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from django_pricemanager.models.choices import SOURCE_CHOICES
from django_pricemanager.settings import APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES


class CurrentPrice(models.Model):
    """One live price per (product, channel, country, currency, customer_tier, parent).

    Updated in-place. Replaces the PriceList snapshot model.
    """

    product = models.ForeignKey("ProductRepresentation", on_delete=models.CASCADE, related_name="current_prices")
    product_parent = models.ForeignKey(
        "ProductRepresentation", on_delete=models.SET_NULL, null=True, blank=True, related_name="current_child_prices"
    )
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="current_prices")
    country = models.ForeignKey("django_regional.Country", on_delete=models.CASCADE)
    currency = models.ForeignKey("django_regional.Currency", on_delete=models.CASCADE)
    customer_representation = models.ForeignKey(
        "CustomerRepresentation", on_delete=models.SET_NULL, null=True, blank=True, related_name="current_prices"
    )
    net_value = models.DecimalField(max_digits=19, decimal_places=4, validators=[MinValueValidator(0)])
    gross_value = models.DecimalField(max_digits=19, decimal_places=4, validators=[MinValueValidator(0)])
    special_net_value = models.DecimalField(
        max_digits=19, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    special_gross_value = models.DecimalField(
        max_digits=19, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    special_from_date = models.DateTimeField(null=True, blank=True, default=None)
    special_to_date = models.DateTimeField(null=True, blank=True, default=None)
    tax_rate = models.ForeignKey("TaxRate", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    is_only_for_verified_user = models.BooleanField(default=False)
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    attrs = models.ManyToManyField(
        "AttributeRepresentation", related_name="current_prices_attrs", blank=True, through="CurrentPriceAttribute"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pricemanager_currentprice"
        verbose_name = "current price"
        verbose_name_plural = "current prices"
        constraints = [
            # General prices, no bundle parent
            models.UniqueConstraint(
                fields=["product", "channel", "country", "currency"],
                condition=models.Q(customer_representation__isnull=True, product_parent__isnull=True),
                name="unique_current_price_general",
            ),
            # General prices, with bundle parent
            models.UniqueConstraint(
                fields=["product", "product_parent", "channel", "country", "currency"],
                condition=models.Q(customer_representation__isnull=True, product_parent__isnull=False),
                name="unique_current_price_general_bundle",
            ),
            # B2B tier prices, no bundle parent
            models.UniqueConstraint(
                fields=["product", "channel", "country", "currency", "customer_representation"],
                condition=models.Q(customer_representation__isnull=False, product_parent__isnull=True),
                name="unique_current_price_customer",
            ),
            # B2B tier prices, with bundle parent
            models.UniqueConstraint(
                fields=["product", "product_parent", "channel", "country", "currency", "customer_representation"],
                condition=models.Q(customer_representation__isnull=False, product_parent__isnull=False),
                name="unique_current_price_customer_bundle",
            ),
        ]
        indexes = [
            models.Index(fields=["channel", "country", "currency"]),
            models.Index(fields=["product", "channel"]),
            models.Index(fields=["product"]),
        ]

    def __str__(self) -> str:
        return f"CurrentPrice({self.product_id}, {self.channel_id}, {self.country_id})"

    def is_eligible_for_special_price(self) -> bool:
        current_date = timezone.now()
        if self.special_from_date and self.special_to_date:
            return self.special_from_date < current_date < self.special_to_date
        if self.special_from_date:
            return self.special_from_date < current_date
        if self.special_to_date:
            return self.special_to_date > current_date
        return APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES

    def _build_price_dict(self, vat_0: bool = False, round_price: int = 2) -> dict:
        product = self.product
        attrs = list(self.attrs.all()) if not product else []
        first_attr = attrs[0] if attrs else None

        if vat_0:
            gross = round(Decimal(self.net_value), round_price) if self.net_value else self.net_value
            net = gross
            sp_gross = round(Decimal(self.special_net_value), round_price) if self.special_net_value else None
            sp_net = sp_gross
            tax_class = "0 VAT"
            tax_rate = Decimal(0.00)
        else:
            gross = round(Decimal(self.gross_value), round_price) if self.gross_value else self.gross_value
            net = round(Decimal(self.net_value), round_price) if self.net_value else self.net_value
            sp_gross = round(Decimal(self.special_gross_value), round_price) if self.special_gross_value else None
            sp_net = round(Decimal(self.special_net_value), round_price) if self.special_net_value else None
            tax_class = product.tax_class.idx if product else first_attr.tax_class.idx
            tax_rate = self.tax_rate.rate if self.tax_rate is not None else None

        return {
            "product": product.sku if product else [attr.idx for attr in attrs],
            "tax_class": tax_class,
            "gross": gross,
            "net": net,
            "special_gross": sp_gross,
            "special_net": sp_net,
            "tax_rate": tax_rate,
            "special_from_date": self.special_from_date,
            "special_to_date": self.special_to_date,
            "is_egible_for_special_price": self.is_eligible_for_special_price(),
            "uid": self.customer_representation.uid if self.customer_representation else None,
        }

    def get_standard_price(self, round_price: int = 2) -> dict:
        """Return price dict identical to legacy Price.get_standard_price()."""
        return self._build_price_dict(vat_0=False, round_price=round_price)

    def get_0_vat_standard_price(self, round_price: int = 2) -> dict:
        """Return price dict with net = gross (0 VAT)."""
        return self._build_price_dict(vat_0=True, round_price=round_price)
