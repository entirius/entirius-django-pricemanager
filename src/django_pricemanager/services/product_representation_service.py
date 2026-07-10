# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from django.core.exceptions import ObjectDoesNotExist
from django_utils.api.exceptions import Unauthorized

from django_pricemanager.models import PriceList, PriceListStatusEnum
from django_pricemanager.services.pricelist_service import get_latest_pricelist


def get_price(product_sku: str, channel_idx: str) -> list[dict]:
    """
    Zwraca liste cen produktu dla danego Channel
    Zawiera ceny z najnowszego cennika dla kazdego z krajow
    """
    pricelists = PriceList.objects.filter(
        prices__product__sku=product_sku, sale_channel__channel__idx=channel_idx, status=PriceListStatusEnum.READY
    )
    latest_pricelists = []
    countries = []
    for country in pricelists.values("country"):
        ctr = country["country"]
        if ctr not in countries:
            countries.append(ctr)
    for ctr in countries:
        lt_pricelist = pricelists.filter(country=ctr).latest()
        latest_pricelists.append(lt_pricelist)
    prices = []
    for prl in latest_pricelists:
        price = prl.prices.get(product__sku=product_sku, attrs__isnull=True, product_parent__isnull=True)
        prices.append(
            {"country_code": prl.country.iso2, "currency_code": prl.currency.iso3, "prices": price.get_standard_price()}
        )
    return prices


# Used by:
# django-checkout
# django-matrix
def get_price_for_country_and_currency(
    product_sku: str,
    channel_idx: str,
    country_code: str,
    currency_code: str,
    uid: str | None = None,
    vat_0: bool = False,
) -> dict:
    """
    Zwraca cene produktu dla danego Channel, Country i Currency
    """
    empty_data = {"country_code": country_code, "currency_code": currency_code, "price": None}
    prl = get_latest_pricelist(channel_idx=channel_idx, country=country_code, currency=currency_code, uid=uid)

    if prl:
        try:
            price = prl.prices.get(product__sku=product_sku, attrs__isnull=True, product_parent__isnull=True)
            return {
                "country_code": prl.country.iso2,
                "currency_code": prl.currency.iso3,
                "price": price.get_standard_price() if not vat_0 else price.get_0_vat_standard_price(),
            }
        except ObjectDoesNotExist:
            if uid:
                return get_price_for_country_and_currency(
                    product_sku=product_sku,
                    channel_idx=channel_idx,
                    country_code=country_code,
                    currency_code=currency_code,
                )
            return empty_data
    else:
        return empty_data


# Used by:
# django-cynthia
def validate_access_to_price_list(
    customer, channel_idx: str, country_code: str, currency_code: str, message_error: str = "", raise_error: bool = True
) -> bool:
    uid = customer.uid if customer else None
    prl = get_latest_pricelist(channel_idx, country_code, currency_code, uid)
    price_list_is_only_for_verified_user = prl.sale_channel.is_only_for_verified_user if prl else False
    have_access = True
    if price_list_is_only_for_verified_user:
        if customer:
            if not customer.is_verified:
                have_access = False
        else:
            have_access = False
    if not have_access and raise_error:
        raise Unauthorized(message_error)
    return have_access
