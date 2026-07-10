# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CurrentPrice read layer — compatibility with output.py consumers.

Functions return identical data shapes as the legacy PriceList-based functions.
"""

import logging

from django.db.models import QuerySet

from django_pricemanager.models import CurrentPrice

logger = logging.getLogger(__name__)


def get_current_prices(
    channel_idx: str,
    currency: str,
    country: str,
    skus: list[str] | None = None,
    uid: str | None = None,
) -> QuerySet:
    """Return CurrentPrice QuerySet for matrix fill_read_model. Replaces get_price_qs_by_given_pricelist."""
    qs = CurrentPrice.objects.filter(
        channel__idx=channel_idx,
        currency__iso3=currency,
        country__iso2=country,
    ).select_related("product", "tax_rate", "product_parent", "customer_representation")

    if skus:
        qs = qs.filter(product__sku__in=skus)

    if uid:
        # Customer-specific: return customer prices + fallback generic for missing products
        customer_qs = qs.filter(customer_representation__uid=uid)
        customer_skus = set(customer_qs.values_list("product__sku", flat=True))
        generic_qs = qs.filter(customer_representation__isnull=True).exclude(product__sku__in=customer_skus)
        return customer_qs | generic_qs

    return qs.filter(customer_representation__isnull=True)


def get_current_price_for_country_and_currency(
    product_sku: str,
    channel_idx: str,
    country_code: str,
    currency_code: str,
    uid: str | None = None,
    vat_0: bool = False,
) -> dict:
    """Return price dict identical to legacy get_price_for_country_and_currency."""
    filters = {
        "product__sku__iexact": product_sku,
        "channel__idx": channel_idx,
        "country__iso2": country_code,
        "currency__iso3": currency_code,
        "product_parent__isnull": True,
    }

    if uid:
        cp = (
            CurrentPrice.objects.filter(**filters, customer_representation__uid=uid)
            .select_related("product__tax_class", "tax_rate", "customer_representation")
            .first()
        )
        if not cp:
            cp = (
                CurrentPrice.objects.filter(**filters, customer_representation__isnull=True)
                .select_related("product__tax_class", "tax_rate", "customer_representation")
                .first()
            )
    else:
        cp = (
            CurrentPrice.objects.filter(**filters, customer_representation__isnull=True)
            .select_related("product__tax_class", "tax_rate", "customer_representation")
            .first()
        )

    if not cp:
        return {}

    if vat_0:
        return cp.get_0_vat_standard_price()
    return cp.get_standard_price()


def validate_access_current(
    customer,
    channel_idx: str,
    country_code: str,
    currency_code: str,
    message_error: str = "",
    raise_error: bool = True,
) -> bool:
    """Check if customer can access prices in this channel/country/currency."""
    has_verified_only = CurrentPrice.objects.filter(
        channel__idx=channel_idx,
        country__iso2=country_code,
        currency__iso3=currency_code,
        is_only_for_verified_user=True,
    ).exists()

    if has_verified_only and not getattr(customer, "is_verified", False):
        return False
    return True
