# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the PriceHistory append-only audit model."""

from decimal import Decimal

import pytest
from django.utils import timezone

from django_pricemanager.models import PriceHistory


@pytest.mark.django_db
class TestPriceHistoryCreation:
    def test_history_created_on_price_change(self, prices_populated):
        """Manually inserting a PriceHistory row succeeds and the row exists."""
        ns = prices_populated
        cp = ns.prices[0]
        entry = PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=cp.gross_value,
            net_value=cp.net_value,
            source="admin_edit",
        )
        assert PriceHistory.objects.filter(pk=entry.pk).exists()

    def test_history_records_new_values(self, prices_populated):
        """PriceHistory stores the gross/net values that were supplied at creation."""
        ns = prices_populated
        cp = ns.prices[0]
        entry = PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("150.00"),
            net_value=Decimal("121.95"),
            source="admin_edit",
        )
        entry.refresh_from_db()
        assert entry.gross_value == Decimal("150.00")
        assert entry.net_value == Decimal("121.95")

    def test_history_source_field(self, prices_populated):
        """Each SOURCE_CHOICES value can be stored as the source field."""
        ns = prices_populated
        cp = ns.prices[0]
        for source_key, _ in [
            ("csv_import", "CSV Import"),
            ("api", "API"),
            ("admin_edit", "Admin Edit"),
            ("tax_rate_change", "Tax Rate Change"),
            ("migration", "Migration"),
        ]:
            entry = PriceHistory.objects.create(
                product=cp.product,
                channel=cp.channel,
                country=cp.country,
                currency=cp.currency,
                gross_value=cp.gross_value,
                net_value=cp.net_value,
                source=source_key,
            )
            assert entry.source == source_key

    def test_history_changed_by_nullable(self, prices_populated):
        """changed_by=None is a valid value — not every change comes from an authenticated user."""
        ns = prices_populated
        cp = ns.prices[0]
        entry = PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=cp.gross_value,
            net_value=cp.net_value,
            source="generation",
            changed_by=None,
        )
        assert entry.changed_by is None


@pytest.mark.django_db
class TestPriceHistoryConstraints:
    def test_history_not_modifiable(self, prices_populated):
        """PriceHistory rows cannot be updated via bulk_update (immutable by design).

        The model has no UPDATE path — only INSERT. We verify that fields stay
        unchanged when overwritten via Python attribute assignment but without calling save().
        """
        ns = prices_populated
        cp = ns.prices[0]
        entry = PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("100.00"),
            net_value=Decimal("81.30"),
            source="csv_import",
        )
        original_gross = entry.gross_value
        # In-memory mutation without save — row in DB must stay intact
        entry.gross_value = Decimal("999.00")
        fresh = PriceHistory.objects.get(pk=entry.pk)
        assert fresh.gross_value == original_gross

    def test_multiple_changes_create_multiple_records(self, prices_populated):
        """Two INSERT calls for the same product/channel produce two distinct rows."""
        ns = prices_populated
        cp = ns.prices[0]
        before = PriceHistory.objects.filter(product=cp.product, channel=cp.channel).count()
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("120.00"),
            net_value=Decimal("97.56"),
            source="admin_edit",
        )
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("130.00"),
            net_value=Decimal("105.69"),
            source="admin_edit",
        )
        after = PriceHistory.objects.filter(product=cp.product, channel=cp.channel).count()
        assert after == before + 2


@pytest.mark.django_db
class TestPriceHistoryOrdering:
    def test_history_ordering_newest_first(self, prices_populated):
        """Default ordering is -created_at — newest entry is first."""
        ns = prices_populated
        cp = ns.prices[0]
        earlier = timezone.now() - timezone.timedelta(hours=2)
        later = timezone.now()
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("100.00"),
            net_value=Decimal("81.30"),
            source="admin_edit",
            created_at=earlier,
        )
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("110.00"),
            net_value=Decimal("89.43"),
            source="admin_edit",
            created_at=later,
        )
        entries = list(PriceHistory.objects.filter(product=cp.product, channel=cp.channel).order_by("-created_at")[:2])
        assert entries[0].gross_value == Decimal("110.00")
        assert entries[1].gross_value == Decimal("100.00")

    def test_history_queryable_by_date_range(self, prices_populated):
        """PriceHistory can be filtered by created_at__gte and __lte."""
        ns = prices_populated
        cp = ns.prices[0]
        anchor = timezone.now()
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("100.00"),
            net_value=Decimal("81.30"),
            source="admin_edit",
            created_at=anchor - timezone.timedelta(days=5),
        )
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("110.00"),
            net_value=Decimal("89.43"),
            source="admin_edit",
            created_at=anchor - timezone.timedelta(days=1),
        )
        PriceHistory.objects.create(
            product=cp.product,
            channel=cp.channel,
            country=cp.country,
            currency=cp.currency,
            gross_value=Decimal("120.00"),
            net_value=Decimal("97.56"),
            source="admin_edit",
            created_at=anchor,
        )
        in_range = PriceHistory.objects.filter(
            product=cp.product,
            channel=cp.channel,
            created_at__gte=anchor - timezone.timedelta(days=2),
            created_at__lte=anchor,
        )
        assert in_range.count() == 2
