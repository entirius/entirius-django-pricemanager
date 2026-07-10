# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from django_pricemanager.services.pricelist_service import get_latest_pricelist


# Used by:
# django-matrix
def get_product_bundle_components_price(
    channel_idx: str,
    country_code: str,
    currency_code: str,
    bundle_sku: str,
    components_sku: list = None,
    uid: str | None = None,
) -> tuple[list, bool]:
    prl = get_latest_pricelist(channel_idx=channel_idx, country=country_code, currency=currency_code, uid=uid)
    is_only_for_verified_user = prl.sale_channel.is_only_for_verified_user
    sku_query = {"product__sku__in": components_sku} if components_sku else {}
    if prl:
        prices = prl.prices.filter(**sku_query, attrs__isnull=True, product_parent__sku=bundle_sku)
        if len(prices) == 0:
            if uid:
                return get_product_bundle_components_price(
                    channel_idx=channel_idx,
                    country_code=country_code,
                    currency_code=currency_code,
                    bundle_sku=bundle_sku,
                    components_sku=components_sku,
                )
            else:
                return [], False
        else:
            return prices, is_only_for_verified_user
    else:
        return [], False
