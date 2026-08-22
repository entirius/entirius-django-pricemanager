# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django_utils.models.base_model import BaseModel


class PriceRounding(models.TextChoices):
    NONE = "none", "No rounding"
    P99 = ".99", "Round to .99"
    P95 = ".95", "Round to .95"
    INT = "int", "Round to integer"


def apply_rounding(value: Decimal, rounding: str) -> Decimal:
    """Round a GROSS (displayed) price per P-13. NONE is the identity — used by the dev seed."""
    if rounding == PriceRounding.INT:
        return Decimal(int(value.to_integral_value(rounding="ROUND_HALF_UP")))
    if rounding == PriceRounding.P99:
        return Decimal(int(value)) + Decimal("0.99")
    if rounding == PriceRounding.P95:
        return Decimal(int(value)) + Decimal("0.95")
    return value


class BaselineConfig(BaseModel):
    """Per-channel auto-price-from-cost config: CurrentPrice = PurchaseCost.net_cost x (1+markup), rounded."""

    channel = models.OneToOneField("Channel", on_delete=models.CASCADE, related_name="baseline_config")
    markup_percent = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0.2000"),
        validators=[MinValueValidator(0)],
        help_text="e.g. 0.2000 = 20% markup over PurchaseCost.net_cost.",
    )
    rounding = models.CharField(max_length=8, choices=PriceRounding.choices, default=PriceRounding.NONE)

    class Meta:
        db_table = "pricemanager_baselineconfig"
        verbose_name = "baseline config"
        verbose_name_plural = "baseline configs"

    def __str__(self) -> str:
        return f"BaselineConfig({self.channel.idx}: markup={self.markup_percent}, rounding={self.rounding})"
