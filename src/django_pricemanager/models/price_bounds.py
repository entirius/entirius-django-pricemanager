# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.validators import MinValueValidator
from django.db import models
from django_utils.models.base_model import BaseModel


class PriceBoundsConfig(BaseModel):
    """Price floor config: MAP (absolute, GROSS) + min_margin (%), scoped global -> channel -> sku.

    Most-specific-wins is resolved in services.price_bounds_service, not here — a row with
    both product and channel set beats a row with only one set, which beats a fully-global row
    (product=None, channel=None). Values apply to both the regular and special price.
    """

    product = models.ForeignKey(
        "ProductRepresentation", on_delete=models.CASCADE, null=True, blank=True, related_name="price_bounds"
    )
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, null=True, blank=True, related_name="price_bounds")
    map_value = models.DecimalField(
        max_digits=19,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum Advertised Price, GROSS, absolute amount in the market's currency.",
    )
    min_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum margin over PurchaseCost.net_cost, e.g. 0.05 = 5%.",
    )

    class Meta:
        db_table = "pricemanager_priceboundsconfig"
        verbose_name = "price bounds config"
        verbose_name_plural = "price bounds configs"
        indexes = [models.Index(fields=["product", "channel"])]
        constraints = [
            # nulls_distinct=False: two rows both scoped (product=NULL, channel=NULL) would
            # otherwise be allowed (Postgres treats NULLs as distinct by default), letting
            # get_price_bounds_bulk's most-specific-wins dict silently pick one nondeterministically.
            models.UniqueConstraint(
                fields=["product", "channel"], name="pricebounds_unique_scope", nulls_distinct=False
            ),
        ]

    def __str__(self) -> str:
        scope = self.product.sku if self.product_id else (self.channel.idx if self.channel_id else "global")
        return f"PriceBoundsConfig({scope}: map={self.map_value}, min_margin={self.min_margin_percent})"
