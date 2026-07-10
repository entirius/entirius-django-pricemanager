# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the D1 FULL VATOSS price edit service."""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PriceHistory
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.services.price_edit_service import edit_price, preview_price


@pytest.mark.django_db
class TestEditPriceCountryPropagation:
    def test_edit_net_propagates_to_all_countries(self, prices_populated):
        """Editing net=100 for a channel with 3 countries creates/updates 3 CurrentPrices."""
        ns = prices_populated
        before = CurrentPrice.objects.filter(
            product=ns.chair, channel=ns.channel, customer_representation__isnull=True, product_parent__isnull=True
        ).count()
        assert before == 3  # PL, DE, FR already seeded

        updated = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("120.00"))
        assert len(updated) == 3
        after = CurrentPrice.objects.filter(
            product=ns.chair, channel=ns.channel, customer_representation__isnull=True, product_parent__isnull=True
        ).count()
        assert after == 3  # same 3 rows, updated in-place

    def test_edit_gross_propagates_when_direction_is_gross_to_net(self, products):
        """When channel direction is FROM_GROSS_TO_NET, editing recalculates net from gross."""
        ns = products
        ns.channel.calculate_direction = CalculateDirectionEnum.FROM_GROSS_TO_NET
        ns.channel.save()

        # Seed one price to drive the update_or_create path
        rate_pl = ns.rates[("standard", "PL")]
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=rate_pl,
            net_value=Decimal("100.00"),
            gross_value=Decimal("123.00"),
            source="csv_import",
        )

        updated = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("123.00"))
        pl_price = next(cp for cp in updated if cp.country_id == ns.pl.pk)
        expected_net = rate_pl.net_price(Decimal("123.00"))
        assert pl_price.net_value == expected_net

    def test_edit_creates_price_history_per_country(self, prices_populated):
        """edit_price creates one PriceHistory row per country touched."""
        ns = prices_populated
        before = PriceHistory.objects.filter(product=ns.chair, channel=ns.channel).count()
        edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("110.00"))
        after = PriceHistory.objects.filter(product=ns.chair, channel=ns.channel).count()
        assert after == before + 3  # PL, DE, FR

    def test_edit_recalculates_gross_via_tax_rate(self, prices_populated):
        """net=100 with PL standard rate 23% → gross=123.00."""
        ns = prices_populated
        updated = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"))
        pl_price = next(cp for cp in updated if cp.country_id == ns.pl.pk)
        assert pl_price.net_value == Decimal("100.00")
        assert pl_price.gross_value == Decimal("123.00")

    def test_edit_handles_missing_tax_rate(self, products):
        """Countries without a TaxRate are silently skipped — no exception raised."""
        ns = products
        # Seed a price only for PL; DE and FR have rates but we assign a 4th country without one
        from django_regional.models import Country

        xx = Country(iso2="XX", iso3="XXX", name_en="Testland", name_pl="Testland", prefix="")
        Country.objects.bulk_create([xx])
        xx = Country.objects.get(iso2="XX")
        ns.channel.calculate_countries.add(xx)

        rate_pl = ns.rates[("standard", "PL")]
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=rate_pl,
            net_value=Decimal("100.00"),
            gross_value=Decimal("123.00"),
            source="csv_import",
        )

        # Should not raise even though XX has no TaxRate
        updated = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"))
        country_iso2s = [cp.country.iso2 for cp in updated]
        assert "XX" not in country_iso2s
        assert "PL" in country_iso2s

    def test_edit_special_price_with_dates(self, prices_populated):
        """special_value + date bounds populate special fields on the CurrentPrice."""
        ns = prices_populated
        from django.utils import timezone

        from_dt = timezone.now()
        to_dt = timezone.now() + timezone.timedelta(days=30)

        updated = edit_price(
            channel=ns.channel,
            sku="CHAIR-001",
            value=Decimal("100.00"),
            special_value=Decimal("80.00"),
            special_from=from_dt,
            special_to=to_dt,
        )
        for cp in updated:
            assert cp.special_net_value is not None
            assert cp.special_gross_value is not None
            assert cp.special_from_date is not None
            assert cp.special_to_date is not None


@pytest.mark.django_db
class TestPreviewPrice:
    def test_preview_returns_breakdown_without_saving(self, prices_populated):
        """preview_price returns a list of per-country dicts without persisting any data."""
        ns = prices_populated
        history_before = PriceHistory.objects.count()
        prices_before = CurrentPrice.objects.count()

        result = preview_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"))

        assert isinstance(result, list)
        assert len(result) >= 1
        assert PriceHistory.objects.count() == history_before
        assert CurrentPrice.objects.count() == prices_before

        first = result[0]
        assert "country" in first
        assert "tax_rate" in first
        assert "net" in first
        assert "gross" in first
