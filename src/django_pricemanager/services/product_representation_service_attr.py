# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from django.core.exceptions import ObjectDoesNotExist

from django_pricemanager.models import PriceList, PriceListStatusEnum
from django_pricemanager.services.pricelist_service import get_latest_pricelist


def get_price_attr(
    attr,
    channel_idx: str,
) -> list[dict]:
    """
    Zwraca liste cen attrybutów dla danego Channel
    Zawiera ceny z najnowszego cennika dla kazdego z krajow
    """
    pricelists = PriceList.objects.filter(
        prices__attr=attr, sale_channel__channel__idx=channel_idx, status=PriceListStatusEnum.READY
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
        price = prl.prices.get(attr__idx=attr.idx)
        prices.append(
            {"country_code": prl.country.iso2, "currency_code": prl.currency.iso3, "prices": price.get_standard_price()}
        )
    return prices


def get_price_for_country_and_currency_attr(
    attr, channel_idx: str, country_code: str, currency_code: str, uid: str | None = None
):
    """
    Zwraca cene produktu dla danego Channel, Country i Currency
    """
    empty_data = {"country_code": country_code, "currency_code": currency_code, "price": None}
    prl = get_latest_pricelist(channel_idx=channel_idx, country=country_code, currency=currency_code, uid=uid)
    if prl:
        try:
            price = prl.prices.get(attr__idx=attr)
            return {
                "country_code": prl.country.iso2,
                "currency_code": prl.currency.iso3,
                "price": price.get_standard_price(),
            }
        except ObjectDoesNotExist:
            return empty_data
    else:
        return empty_data
