# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from django.db.models import Subquery

from django_pricemanager.models import Price


def read_from_current() -> bool:
    """Check DB toggle with 60s cache. Falls back to Django setting for backward compat."""
    from django.core.cache import cache

    from django_pricemanager.settings import CACHE_KEY_READ_FROM_CURRENT

    cached = cache.get(CACHE_KEY_READ_FROM_CURRENT)
    if cached is not None:
        return cached
    try:
        from django_pricemanager.models.pm_settings import PriceManagerSettings

        enabled = PriceManagerSettings.load().read_from_current
    except Exception:
        from django_pricemanager.settings import PRICEMANAGER_READ_FROM_CURRENT

        enabled = PRICEMANAGER_READ_FROM_CURRENT
    cache.set(CACHE_KEY_READ_FROM_CURRENT, enabled, 60)
    return enabled


# Used by:
# django-matrix
# New CurrentPrice read layer
from django_pricemanager.services.price_output_service import get_current_prices  # noqa: F401
from django_pricemanager.services.pricelist_service import get_latest_pricelist

# Don't remove this imports, it's used as output in modules
from django_pricemanager.services.product_representation_service import (
    get_price,
    get_price_for_country_and_currency,  # django_cynthia, django-checkout
)


# Used by:
# django-cynthia
def get_price_qs_by_latest_pricelist(channel_idx, currency, country, skus, uid: str | None = None):
    def filter_by(lp, skus_list):
        if len(skus_list) > 0:
            query = {"product__sku__in": skus_list}
        else:
            query = {}
        return Price.objects.filter(pricelist=lp, **query).only_products().with_eligibility_for_special_price()

    if not uid:
        # If no UID just search pricelist that are for anyone
        latest_pricelist = get_latest_pricelist(channel_idx=channel_idx, currency=currency, country=country, uid=uid)
        return filter_by(latest_pricelist, skus)
    else:
        # IF UID find pricelist for specific customer
        latest_pricelist = get_latest_pricelist(channel_idx=channel_idx, currency=currency, country=country, uid=uid)
        if not latest_pricelist.sale_channel.customer_representation:
            # If user pricelist does not exist, return prices
            return filter_by(latest_pricelist, skus)
        else:
            # If user pricelist exists get both his pricelist and for anyone and combine them
            user_pricelist = latest_pricelist
            latest_pricelist = get_latest_pricelist(channel_idx=channel_idx, currency=currency, country=country)

            # Step 1: Get prices from the latest pricelist where the product SKU does not exist in the user pricelist
            if len(skus) > 0:
                product_query = {"product__sku__in": skus}
            else:
                product_query = {}
            latest_prices_excluding_user_skus = filter_by(latest_pricelist, skus).exclude(
                product__sku__in=Subquery(
                    Price.objects.filter(pricelist=user_pricelist, **product_query).values("product__sku")
                )
            )

            # Step 2: Get all prices from the user pricelist
            user_prices = filter_by(user_pricelist, skus)

            # Step 3: Combine both querysets
            return latest_prices_excluding_user_skus.union(user_prices)


# Used by:
# django-matrix
def get_price_qs_by_given_pricelist(pricelist, sku: str = None):
    if sku:
        return (
            Price.objects.filter(pricelist=pricelist, product__sku=sku)
            .only_products()
            .with_eligibility_for_special_price()
        )
    else:
        return Price.objects.filter(pricelist=pricelist).only_products().with_eligibility_for_special_price()


# Used by:
# django-checkout
def get_product_price(channel_idx, product_sku):
    return get_price(product_sku, channel_idx)


# Used by:
# django_checkout
def get_product_price_for_country_and_currency(
    channel_idx, product_sku, country_code, currency_code, uid: str | None = None, vat_0: bool = False
):
    if read_from_current():
        from django_pricemanager.services.price_output_service import get_current_price_for_country_and_currency

        return get_current_price_for_country_and_currency(
            product_sku=product_sku,
            channel_idx=channel_idx,
            country_code=country_code,
            currency_code=currency_code,
            uid=uid,
            vat_0=vat_0,
        )
    return get_price_for_country_and_currency(
        product_sku=product_sku,
        channel_idx=channel_idx,
        country_code=country_code,
        currency_code=currency_code,
        uid=uid,
        vat_0=vat_0,
    )
