# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for recalculation tasks triggered by tax rate or channel changes."""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PriceHistory
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.tasks import (
    recalculate_prices_for_channel_change,
    recalculate_prices_for_tax_change,
)


@pytest.mark.django_db
class TestRecalculateOnTaxChange:
    def test_recalculate_updates_gross_on_tax_change(self, prices_populated):
        """After changing the PL tax rate, the recalc task updates gross_value."""
        ns = prices_populated
        rate = ns.rates[("standard", "PL")]
        rate.rate = Decimal("0.2400")
        rate.save()

        recalculate_prices_for_tax_change(tax_class_idx="standard", country_iso2="PL")

        cp = CurrentPrice.objects.get(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
        )
        expected_gross = rate.gross_price(cp.net_value)
        assert cp.gross_value == expected_gross

    def test_recalculate_creates_history(self, prices_populated):
        """Recalculation writes a PriceHistory row with source='tax_rate_change'."""
        ns = prices_populated
        rate = ns.rates[("standard", "PL")]
        rate.rate = Decimal("0.2500")
        rate.save()

        before = PriceHistory.objects.filter(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
        ).count()
        recalculate_prices_for_tax_change(tax_class_idx="standard", country_iso2="PL")
        after = PriceHistory.objects.filter(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
        ).count()

        assert after > before
        latest = (
            PriceHistory.objects.filter(
                product=ns.chair,
                channel=ns.channel,
                country=ns.pl,
            )
            .order_by("-created_at")
            .first()
        )
        assert latest.source == "tax_rate_change"

    def test_recalculate_respects_direction_from_gross_to_net(self, prices_populated):
        """When channel direction is FROM_GROSS_TO_NET, recalc updates net not gross."""
        ns = prices_populated
        ns.channel.calculate_direction = CalculateDirectionEnum.FROM_GROSS_TO_NET
        ns.channel.save()

        rate = ns.rates[("standard", "PL")]
        original_gross = CurrentPrice.objects.get(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
        ).gross_value
        rate.rate = Decimal("0.2100")
        rate.save()

        recalculate_prices_for_tax_change(tax_class_idx="standard", country_iso2="PL")

        cp = CurrentPrice.objects.get(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
        )
        expected_net = rate.net_price(original_gross)
        assert cp.net_value == expected_net

    def test_recalculate_skips_missing_tax_rate(self, prices_populated):
        """recalculate_prices_for_tax_change skips rows without a matching TaxRate (no error)."""
        ns = prices_populated
        # Remove the standard/PL rate — the task should skip, not raise
        ns.rates[("standard", "PL")].delete()

        # Create the rate back but for a different tax class so the lookup misses
        from django_regional.models import Country

        xx = Country(iso2="XY", iso3="XYZ", name_en="NoVat", name_pl="NoVat", prefix="")
        Country.objects.bulk_create([xx])
        xx = Country.objects.get(iso2="XY")

        # This should not raise even though no TaxRate exists for (standard, PL)
        # After deletion the prices become orphaned; task should handle gracefully
        count = recalculate_prices_for_tax_change(tax_class_idx="standard", country_iso2="PL")
        # No prices for PL standard now means 0 updates
        assert count == 0


@pytest.mark.django_db
class TestRecalculateOnChannelChange:
    def test_channel_recalculate_updates_all(self, prices_populated):
        """recalculate_prices_for_channel_change updates all CurrentPrices in the channel."""
        ns = prices_populated
        count = recalculate_prices_for_channel_change(channel_idx=ns.channel.idx)
        assert count == CurrentPrice.objects.filter(channel=ns.channel).count()

    def test_recalculate_empty_channel(self, channel_setup):
        """Channel with no prices returns 0 updates without error."""
        ns = channel_setup
        # Create a fresh channel with no prices
        from django_pricemanager.models import Channel

        empty_channel = Channel.objects.create(idx="empty-ch", name="Empty Channel")
        count = recalculate_prices_for_channel_change(channel_idx=empty_channel.idx)
        assert count == 0
