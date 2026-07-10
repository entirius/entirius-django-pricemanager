# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django_pricemanager.models import PriceList, SaleChannel


def get_latest_pricelist_by_source(channel, price_source) -> PriceList:
    sale_channel = get_sale_channel_by_source(channel, price_source)
    return PriceList.objects.filter(sale_channel=sale_channel, country=sale_channel.country).latest("modified_on")


def get_sale_channel_by_source(channel, price_source) -> SaleChannel:
    return SaleChannel.objects.get(channel=channel, price_source=price_source, customer_representation=None)
