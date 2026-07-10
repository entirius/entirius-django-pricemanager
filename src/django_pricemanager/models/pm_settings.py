# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class PriceManagerSettings(models.Model):
    """Singleton settings for PriceManager behavior. Managed via Django admin."""

    matrix_signals_enabled = models.BooleanField(
        default=False, help_text="Enable automatic Matrix read model sync on price changes"
    )
    read_from_current = models.BooleanField(
        default=False, help_text="Read prices from CurrentPrice instead of legacy PriceList"
    )

    class Meta:
        verbose_name = "PriceManager Settings"
        verbose_name_plural = "PriceManager Settings"

    def __str__(self) -> str:
        return "PriceManager Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        # Invalidate cached toggles so changes take effect immediately
        from django.core.cache import cache

        from django_pricemanager.settings import CACHE_KEY_MATRIX_SIGNALS_ENABLED, CACHE_KEY_READ_FROM_CURRENT

        cache.delete(CACHE_KEY_MATRIX_SIGNALS_ENABLED)
        cache.delete(CACHE_KEY_READ_FROM_CURRENT)

    @classmethod
    def load(cls) -> "PriceManagerSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
