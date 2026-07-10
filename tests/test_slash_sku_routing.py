# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Slash-containing SKU routing (e.g. "1C01/N") for price endpoints.

<path:sku> matches slashes; the price sub-routes MUST resolve before the bare detail.
"""

import pytest
from django.urls import resolve

PREFIX = "/api/pricemanager/v2/admin/default/prices"
SKUS = ["1C01/N", "2R04/NR", "PLAIN-001"]


@pytest.mark.parametrize("sku", SKUS)
def test_price_detail(sku):
    match = resolve(f"{PREFIX}/{sku}/")
    assert match.url_name == "pricemanager-price-detail"
    assert match.kwargs["sku"] == sku


@pytest.mark.parametrize("sku", SKUS)
@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("preview/", "pricemanager-price-preview"),
        ("history/", "pricemanager-price-history"),
        ("flush-special/", "pricemanager-price-flush-special"),
    ],
)
def test_price_subroutes(sku, suffix, expected):
    match = resolve(f"{PREFIX}/{sku}/{suffix}")
    assert match.url_name == expected
    assert match.kwargs["sku"] == sku
