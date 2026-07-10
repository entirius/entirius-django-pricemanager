# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for migration_service.populate_current_prices() and backfill_price_history().

Actual CSV import goes through legacy code (import-pricelist-from-csv command).
These tests exercise the service layer that reads completed PriceLists and
produces CurrentPrice + PriceHistory rows.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from django_pricemanager.models import (
    CurrentPrice,
    PriceHistory,
    PriceList,
    SaleChannel,
)
from django_pricemanager.models.pricelist import PriceListStatusEnum
from django_pricemanager.services.migration_service import (
    backfill_price_history,
    populate_current_prices,
)


def _make_pricelist(ns, channel, country, currency, net, gross, sku_product):
    """Helper: create a READY PriceList with one Price row."""
    from django_pricemanager.models import Price

    sale_channel, _ = SaleChannel.objects.get_or_create(
        idx=f"sc-{channel.idx}-{country.iso2.lower()}",
        defaults={
            "name": f"SC {channel.idx} {country.iso2}",
            "channel": channel,
            "country": country,
            "price_source": SaleChannel.PRICE_SOURCE_CSV,
        },
    )
    pl = PriceList.objects.create(
        sale_channel=sale_channel,
        currency=currency,
        country=country,
        status=PriceListStatusEnum.READY,
    )
    Price.objects.create(
        pricelist=pl,
        product=sku_product,
        net_value=net,
        gross_value=gross,
        tax_rate=ns.rates.get((sku_product.tax_class.idx, country.iso2)),
    )
    return pl


@pytest.mark.django_db
class TestPopulateCurrentPrices:
    def test_populate_creates_current_prices(self, products):
        """populate_current_prices() creates CurrentPrice rows from READY PriceLists."""
        ns = products
        _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        before = CurrentPrice.objects.count()
        count = populate_current_prices()
        assert count > 0
        assert CurrentPrice.objects.count() > before

    def test_populate_updates_existing(self, products):
        """Running populate twice updates existing rows rather than creating duplicates."""
        ns = products
        _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        populate_current_prices()
        first_count = CurrentPrice.objects.count()

        # Run again — count should not increase
        populate_current_prices()
        assert CurrentPrice.objects.count() == first_count

    def test_populate_respects_batch_size(self, products):
        """Using a small batch_size still processes all rows without data loss."""
        ns = products
        _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        count = populate_current_prices(batch_size=1)
        assert count >= 1

    def test_populate_handles_no_ready_pricelists(self, channel_setup):
        """Empty DB (no READY PriceLists) returns 0 without raising."""
        count = populate_current_prices()
        assert count == 0

    def test_populate_dry_run_no_writes(self, products):
        """dry_run=True reports the count but writes no rows to the DB."""
        ns = products
        _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        before = CurrentPrice.objects.count()
        count = populate_current_prices(dry_run=True)
        assert count > 0
        assert CurrentPrice.objects.count() == before


@pytest.mark.django_db
class TestBackfillPriceHistory:
    def test_backfill_creates_price_history(self, products):
        """backfill_price_history() creates PriceHistory rows from READY PriceLists."""
        ns = products
        _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        before = PriceHistory.objects.count()
        count = backfill_price_history(days=365)
        assert count > 0
        assert PriceHistory.objects.count() > before

    def test_backfill_preserves_original_timestamps(self, products):
        """PriceHistory.created_at is set to the PriceList.created_on timestamp."""
        ns = products
        pl = _make_pricelist(ns, ns.channel, ns.pl, ns.pln, Decimal("100.00"), Decimal("123.00"), ns.chair)
        # PriceList.created_on is auto_now_add; set it to a known value via update
        known_ts = timezone.now() - timezone.timedelta(days=10)
        PriceList.objects.filter(pk=pl.pk).update(created_on=known_ts)
        pl.refresh_from_db()

        backfill_price_history(days=365)
        entries = PriceHistory.objects.filter(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
        )
        assert entries.exists()
        for entry in entries:
            # Allow 1-second tolerance for auto_now_add vs explicit assignment
            delta = abs((entry.created_at - pl.created_on).total_seconds())
            assert delta < 2
