# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for CurrentPrice and TaxRate model behaviour."""

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from django_pricemanager.models import CurrentPrice, CustomerRepresentation


@pytest.mark.django_db
class TestCurrentPriceUniqueConstraints:
    def test_unique_constraint_product_channel_country_currency(self, prices_populated):
        """Creating a second general CurrentPrice for the same combo raises IntegrityError."""
        ns = prices_populated
        first = ns.prices[0]  # CHAIR-001 / b2c-europe / PL / PLN
        with pytest.raises(IntegrityError):
            CurrentPrice.objects.create(
                product=first.product,
                channel=first.channel,
                country=first.country,
                currency=first.currency,
                tax_rate=first.tax_rate,
                net_value=Decimal("200.00"),
                gross_value=Decimal("246.00"),
                source="csv_import",
                customer_representation=None,
                product_parent=None,
            )

    def test_unique_constraint_allows_different_customers(self, prices_populated):
        """General price and B2B-tier price can coexist for the same product/channel/country/currency."""
        ns = prices_populated
        base = ns.prices[0]  # already has customer_representation=None
        customer = CustomerRepresentation.objects.create(uid="b2b-tier-1", user_email="b2b@example.com")
        customer_price = CurrentPrice.objects.create(
            product=base.product,
            channel=base.channel,
            country=base.country,
            currency=base.currency,
            tax_rate=base.tax_rate,
            net_value=Decimal("90.00"),
            gross_value=Decimal("110.70"),
            source="csv_import",
            customer_representation=customer,
            product_parent=None,
        )
        assert customer_price.pk is not None
        assert CurrentPrice.objects.filter(product=base.product, channel=base.channel).count() >= 2


@pytest.mark.django_db
class TestCurrentPriceFields:
    def test_create_with_special_price_and_dates(self, products):
        """CurrentPrice stores special values and date bounds correctly."""
        ns = products
        from_dt = timezone.now()
        to_dt = timezone.now() + timezone.timedelta(days=30)
        cp = CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=ns.rates[("standard", "PL")],
            net_value=Decimal("100.00"),
            gross_value=Decimal("123.00"),
            special_net_value=Decimal("80.00"),
            special_gross_value=Decimal("98.40"),
            special_from_date=from_dt,
            special_to_date=to_dt,
            source="admin_edit",
        )
        cp.refresh_from_db()
        assert cp.special_net_value == Decimal("80.00")
        assert cp.special_gross_value == Decimal("98.40")
        assert cp.special_from_date is not None
        assert cp.special_to_date is not None

    def test_create_without_special_price(self, products):
        """Special price fields default to None when not supplied."""
        ns = products
        cp = CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=ns.rates[("standard", "PL")],
            net_value=Decimal("100.00"),
            gross_value=Decimal("123.00"),
            source="csv_import",
        )
        assert cp.special_net_value is None
        assert cp.special_gross_value is None
        assert cp.special_from_date is None
        assert cp.special_to_date is None


@pytest.mark.django_db
class TestTaxRateCalculations:
    def test_tax_rate_calculation_net_to_gross(self, tax_setup):
        """gross_price(100, rate=0.23) == 123.00."""
        rate = tax_setup.rates[("standard", "PL")]  # 23%
        result = rate.gross_price(Decimal("100.00"))
        assert result == Decimal("123.00")

    def test_tax_rate_calculation_gross_to_net(self, tax_setup):
        """net_price(119, rate=0.19) rounds to 2dp and is < gross."""
        rate = tax_setup.rates[("standard", "DE")]  # 19%
        gross = Decimal("119.00")
        net = rate.net_price(gross)
        assert net < gross
        # 119 / 1.19 = 100.00 exactly for this case
        assert net == Decimal("100.00")


@pytest.mark.django_db
class TestCurrentPriceSpecialEligibility:
    def test_is_eligible_for_special_price_within_range(self, products):
        """is_eligible_for_special_price() returns True when now is between from/to."""
        ns = products
        now = timezone.now()
        cp = CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=ns.rates[("standard", "PL")],
            net_value=Decimal("100.00"),
            gross_value=Decimal("123.00"),
            special_net_value=Decimal("80.00"),
            special_gross_value=Decimal("98.40"),
            special_from_date=now - timezone.timedelta(days=1),
            special_to_date=now + timezone.timedelta(days=1),
            source="admin_edit",
        )
        assert cp.is_eligible_for_special_price() is True

    def test_get_standard_price_returns_correct_dict(self, prices_populated):
        """get_standard_price() dict contains all keys matching the legacy Price format."""
        cp = prices_populated.prices[0]
        result = cp.get_standard_price()
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
        assert result["product"] == cp.product.sku
        assert result["uid"] is None
