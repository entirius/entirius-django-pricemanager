# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for price_output_service — the CurrentPrice read layer.

These verify that the functions return data shapes identical to the legacy
PriceList-based output.py consumers (matrix, checkout).
"""

import pytest

from django_pricemanager.models import CurrentPrice
from django_pricemanager.services.price_output_service import (
    get_current_price_for_country_and_currency,
    get_current_prices,
    validate_access_current,
)


@pytest.mark.django_db
class TestGetCurrentPrices:
    def test_get_current_prices_returns_queryset(self, prices_populated):
        """Returns a QuerySet filtered to the given channel/currency/country."""
        ns = prices_populated
        qs = get_current_prices(
            channel_idx=ns.channel.idx,
            currency="PLN",
            country="PL",
        )
        assert qs.exists()
        for cp in qs:
            assert cp.channel_id == ns.channel.pk
            assert cp.currency.iso3 == "PLN"
            assert cp.country.iso2 == "PL"

    def test_get_current_prices_filters_by_skus(self, prices_populated):
        """Passing skus parameter returns only the matching subset."""
        ns = prices_populated
        qs = get_current_prices(
            channel_idx=ns.channel.idx,
            currency="PLN",
            country="PL",
            skus=["CHAIR-001"],
        )
        skus_returned = list(qs.values_list("product__sku", flat=True))
        assert all(s == "CHAIR-001" for s in skus_returned)
        assert "FOOD-001" not in skus_returned


@pytest.mark.django_db
class TestGetCurrentPriceForCountryAndCurrency:
    def test_get_current_price_returns_dict_with_correct_keys(self, prices_populated):
        """Returned dict has all keys matching the legacy Price.get_standard_price() format."""
        result = get_current_price_for_country_and_currency(
            product_sku="CHAIR-001",
            channel_idx="b2c-europe",
            country_code="PL",
            currency_code="PLN",
        )
        expected_keys = {
            "product",
            "tax_class",
            "gross",
            "net",
            "special_gross",
            "special_net",
            "tax_rate",
            "special_from_date",
            "special_to_date",
            "is_egible_for_special_price",
            "uid",
        }
        assert set(result.keys()) == expected_keys
        assert result["product"] == "CHAIR-001"
        assert result["uid"] is None

    def test_get_current_price_b2b_fallback(self, prices_populated):
        """When uid is provided but no customer-specific price exists, falls back to general price."""
        result = get_current_price_for_country_and_currency(
            product_sku="CHAIR-001",
            channel_idx="b2c-europe",
            country_code="PL",
            currency_code="PLN",
            uid="nonexistent-uid-999",
        )
        # Falls back to general — result is not empty
        assert result != {}
        assert result["product"] == "CHAIR-001"

    def test_get_current_price_returns_empty_for_missing(self, prices_populated):
        """Unknown SKU returns an empty dict, not an exception."""
        result = get_current_price_for_country_and_currency(
            product_sku="NO-SUCH-SKU",
            channel_idx="b2c-europe",
            country_code="PL",
            currency_code="PLN",
        )
        assert result == {}


@pytest.mark.django_db
class TestValidateAccessCurrent:
    def test_validate_access_allows_normal(self, prices_populated):
        """Returns True when no is_only_for_verified_user prices exist in the scope."""
        ns = prices_populated

        class FakeCustomer:
            is_verified = False

        result = validate_access_current(
            customer=FakeCustomer(),
            channel_idx=ns.channel.idx,
            country_code="PL",
            currency_code="PLN",
            raise_error=False,
        )
        assert result is True

    def test_validate_access_blocks_unverified(self, prices_populated):
        """PermissionDenied raised when is_only_for_verified_user=True and customer is not verified."""
        ns = prices_populated
        # Mark one price as verified-only
        cp = CurrentPrice.objects.filter(channel=ns.channel, country=ns.pl).first()
        cp.is_only_for_verified_user = True
        cp.save()

        class UnverifiedCustomer:
            is_verified = False

        result = validate_access_current(
            customer=UnverifiedCustomer(),
            channel_idx=ns.channel.idx,
            country_code="PL",
            currency_code="PLN",
        )
        assert result is False
