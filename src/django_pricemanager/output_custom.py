# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import logging
from itertools import groupby
from operator import itemgetter

from django.db.models import Count, Q
from django_utils.api.exceptions import NotFound

from django_pricemanager.services.product_representation_service import (
    get_latest_pricelist,
    get_price_for_country_and_currency,
)
from django_pricemanager.services.product_representation_service_attr import (
    get_price_for_country_and_currency_attr,
)

from .models import (
    AttributeRepresentation,
    Price,
    PriceAttribute,
)

logger = logging.getLogger(__name__)


# Used by:
# only inside pricemanager
def get_attr_price_for_country_and_currency(channel_idx, attr_idx, country_code, currency_code):
    attr = AttributeRepresentation.objects.get(idx=attr_idx)
    return get_price_for_country_and_currency_attr(attr, channel_idx, country_code, currency_code)


def check_can_add_attr_special_price(product_price, attr_price, key_with_price):
    today = datetime.date.today()
    if product_price["price"][key_with_price] and attr_price[key_with_price]:
        if not attr_price["special_from_date"] and not attr_price["special_to_date"]:
            return True
        elif attr_price["special_from_date"] <= today <= attr_price["special_to_date"]:
            return True
        else:
            return False
    else:
        return False


def is_subset(check_list, main_list):
    for sublist in main_list:
        if sorted(check_list) == sorted(sublist):
            return True
    return False


def is_price_allowed(attr_ids, attr_idx_list, already_used_attrs):
    allowed_attr_idx_list = []

    for attr_id in attr_ids:
        attr_id = attr_id["attr__idx"]
        allowed_attr_idx_list.append(attr_id)
        if attr_id not in attr_idx_list:
            return False, already_used_attrs

    if len(allowed_attr_idx_list) != len(attr_ids):
        return False, already_used_attrs

    if is_subset(allowed_attr_idx_list, already_used_attrs):
        return False, already_used_attrs
    already_used_attrs.append(allowed_attr_idx_list)

    return True, already_used_attrs


# Used by:
# django_checkout
# django_matrix
def get_product_custom_price_for_country_and_currency(
    product_sku, attr_idx_list, channel_idx, country_code, currency_code, vat_0=False
):
    product_price = get_price_for_country_and_currency(product_sku, channel_idx, country_code, currency_code)
    if not product_price["price"]:
        raise NotFound("Product price not found")

    base_gross = product_price["price"].get("gross")
    base_net = product_price["price"].get("net")
    price_components = []

    prl = get_latest_pricelist(channel_idx=channel_idx, country=country_code, currency=currency_code)
    prices_attr = (
        PriceAttribute.objects.filter(
            Q(price__product__sku=product_sku) | Q(price__product__sku__isnull=True),
            price__product_parent__isnull=True,
            price__pricelist=prl,
        )
        .select_related("price", "price__product")
        .values("price_id", "attr__idx", "price__product")
        .annotate(attr_count=Count("price__attrs"))
        .order_by("-price__product")
    )

    prices_allowed = []
    already_used_attrs = []
    prices_attr = sorted(prices_attr, key=itemgetter("price_id"))
    prices_attr_grouped = groupby(prices_attr, key=itemgetter("price_id"))
    for price_id, attr_ids in prices_attr_grouped:
        attr_ids = list(attr_ids)
        len_attr_ids = len(attr_ids)
        price_q = attr_ids[0]["attr_count"]
        if len_attr_ids != price_q:
            continue

        is_allowed, already_used_attrs = is_price_allowed(attr_ids, attr_idx_list, already_used_attrs)
        if is_allowed:
            prices_allowed.append(price_id)

    for attr_p in Price.objects.filter(id__in=prices_allowed):
        if vat_0:
            attr_price = attr_p.get_0_vat_standard_price()
        else:
            attr_price = attr_p.get_standard_price()
        if not attr_price:
            continue

        price_components.append(
            {
                "attrs": attr_price.get("product", "unknown"),
                "gross": attr_price.get("gross"),
                "net": attr_price.get("net"),
            }
        )

        if "net" in product_price["price"] and "net" in attr_price:
            product_price["price"]["net"] = round(product_price["price"]["net"], 2) + round(attr_price["net"], 2)
        if "gross" in product_price["price"] and "gross" in attr_price:
            product_price["price"]["gross"] = round(product_price["price"]["gross"], 2) + round(attr_price["gross"], 2)

        if check_can_add_attr_special_price(product_price, attr_price, "special_gross"):
            product_price["price"]["special_gross"] = round(product_price["price"]["special_gross"], 2) + round(
                attr_price["special_gross"], 2
            )
        else:
            if product_price["price"]["special_gross"]:
                product_price["price"]["special_gross"] = round(product_price["price"]["special_gross"], 2) + round(
                    attr_price["gross"], 2
                )
            else:
                product_price["price"]["special_gross"] = None

        if check_can_add_attr_special_price(product_price, attr_price, "special_net"):
            product_price["price"]["special_net"] = round(product_price["price"]["special_net"], 2) + round(
                attr_price["special_net"], 2
            )
        else:
            if product_price["price"]["special_net"]:
                product_price["price"]["special_net"] = round(product_price["price"]["special_net"], 2) + round(
                    attr_price["net"], 2
                )
            else:
                product_price["price"]["special_net"] = None

    product_price["_price_components"] = {
        "base_gross": base_gross,
        "base_net": base_net,
        "attributes": price_components,
    }

    return product_price
