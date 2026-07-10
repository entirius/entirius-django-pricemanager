# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.http import Http404, JsonResponse

from .models import PriceList

###########
#    _    #
#  ('v')  #
# //-=-\\ #   Code old and not tested, use for your own sake
# (\_=_/) #
#  ^^ ^^  #
###########


def get_pricelist_for_channel(request, channel_name):
    pricelist = PriceList.objects.filter(sale_channel_shop__name=channel_name).latest()
    data = pricelist.get_pricelist()
    return JsonResponse(data)


def get_product_price(request, product, channel_name):
    pricelists = PriceList.objects.filter(sale_channel_shop__name=channel_name)
    latest_pricelists = []
    for country in pricelists.values("country").distinct():
        ctr = country["country"]
        lt_pricelist = pricelists.filter(country=ctr).latest()
        latest_pricelists.append(lt_pricelist)
    prices = []
    for prl in latest_pricelists:
        price = prl.price_set.get(product__sku=product)
        prices.append({"channel": prl.channel.code, "country": prl.country, "prices": price.get_standard_price()})
    return JsonResponse(prices)


def get_product_price_for_country(request, product, channel_name, country):
    pricelists = PriceList.objects.filter(sale_channel_shop__name=channel_name, country=country)
    if len(pricelists) > 0:
        pricelist = pricelists.latest()
    else:
        raise Http404("No pricelist found")

    price = pricelist.price_set.get(product__sku=product)
    return JsonResponse(price.get_standard_price())


def get_allowed_countries(request):
    pass


def get_available_pricelists(request):
    ids = PriceList.objects.all().values("country", "channel__name")
    latest_pricelists = []
    response = []
    for item in ids.distinct():
        pricelists = PriceList.objects.get_for_channel(
            sale_channel_shop__name=item["channel__name"], country=item["country"]
        )
        lp = pricelists.latest()
        latest_pricelists.append(lp)
    for p in latest_pricelists:
        response.append({"id": p.get_pricelist_id(), "name": p.name, "country": p.country, "channel": p.channel.name})
    return JsonResponse(response)
