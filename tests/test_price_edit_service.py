# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the D1 FULL VATOSS price edit service."""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PriceHistory, ProductRepresentation
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_bounds import PriceBoundsConfig
from django_pricemanager.services.price_edit_service import bulk_edit_prices, edit_price, preview_price


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
class TestEditPriceSourceAndCountryScope:
    def test_default_source_is_admin_edit(self, prices_populated):
        ns = prices_populated
        report = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("110.00"))
        assert all(cp.source == PriceSource.ADMIN_EDIT for cp in report.applied)

    def test_country_scope_writes_only_that_market(self, prices_populated):
        """With `country`, only that market is written — the others stay untouched."""
        ns = prices_populated
        before_de = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de).gross_value

        report = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("150.00"), country=ns.pl)

        assert len(report.applied) == 1
        assert report.applied[0].country_id == ns.pl.pk
        after_de = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de).gross_value
        assert after_de == before_de

    def test_no_country_propagates_to_all_countries(self, prices_populated):
        """Regression: omitting `country` keeps legacy propagate-to-all-countries behavior."""
        ns = prices_populated
        report = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("140.00"))
        assert len(report.applied) == 3

    def test_pricefighter_cannot_overwrite_admin_edit(self, prices_populated):
        """writer=pricefighter is skipped on a row locked by admin_edit; other countries still apply."""
        ns = prices_populated
        edit_price(
            channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"), country=ns.pl, source=PriceSource.ADMIN_EDIT
        )

        report = edit_price(
            channel=ns.channel, sku="CHAIR-001", value=Decimal("999.00"), source=PriceSource.PRICEFIGHTER
        )

        pl_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl)
        assert pl_price.gross_value == Decimal("123.00")  # untouched — admin_edit lock survives
        assert any(s["country"] == "PL" for s in report.skipped)
        # DE/FR had no admin_edit lock — pricefighter applies there
        assert any(cp.country_id == ns.de.pk for cp in report.applied)

    def test_b2b_tier_row_does_not_shadow_general_row_source(self, prices_populated):
        """existing_rows must filter customer_representation__isnull=True — a B2B tier row for
        the same (country, currency) must not clobber the dict key the general-row write
        checks precedence against."""
        from django_pricemanager.models import CustomerRepresentation

        ns = prices_populated
        cp_general = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, customer_representation__isnull=True
        )
        assert cp_general.source == "csv_import"
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            customer_representation=CustomerRepresentation.objects.create(uid="b2b-1", user_email="b2b@example.com"),
            tax_rate=cp_general.tax_rate,
            net_value=Decimal("40.00"),
            gross_value=Decimal("49.20"),
            source=PriceSource.ADMIN_EDIT,
        )

        # If the guard read the B2B row's admin_edit source instead of the general row's
        # csv_import source, pricefighter would be (wrongly) skipped here.
        report = edit_price(
            channel=ns.channel,
            sku="CHAIR-001",
            value=Decimal("200.00"),
            currency_code="PLN",
            source=PriceSource.PRICEFIGHTER,
            country=ns.pl,
        )

        assert report.applied
        cp_general.refresh_from_db()
        assert cp_general.source == PriceSource.PRICEFIGHTER

    def test_strict_mode_raises_on_unknown_sku_for_automated_writer(self, channel_setup):
        with pytest.raises(ValueError):
            edit_price(
                channel=channel_setup.channel, sku="GHOST-SKU", value=Decimal("10.00"), source=PriceSource.PRICEFIGHTER
            )
        assert not ProductRepresentation.objects.filter(sku="GHOST-SKU").exists()

    def test_strict_mode_raises_for_baseline_writer_too(self, channel_setup):
        with pytest.raises(ValueError):
            edit_price(
                channel=channel_setup.channel, sku="GHOST-SKU-2", value=Decimal("10.00"), source=PriceSource.BASELINE
            )
        assert not ProductRepresentation.objects.filter(sku="GHOST-SKU-2").exists()

    def test_manual_source_still_auto_creates_product(self, channel_setup):
        """Non-automated sources keep today's auto-create behavior."""
        report = edit_price(channel=channel_setup.channel, sku="NEW-SKU", value=Decimal("10.00"), currency_code="PLN")
        assert ProductRepresentation.objects.filter(sku="NEW-SKU").exists()
        assert len(report.applied) >= 1

    def test_stored_source_overrides_label_written(self, prices_populated):
        """pricefighter revert-to-baseline: writer=pricefighter (may overwrite its own prior
        row) but the label persisted is stored_source=baseline — precedence and the stored
        label are independent knobs."""
        ns = prices_populated
        edit_price(
            channel=ns.channel, sku="CHAIR-001", value=Decimal("90.00"), country=ns.pl, source=PriceSource.PRICEFIGHTER
        )

        report = edit_price(
            channel=ns.channel,
            sku="CHAIR-001",
            value=Decimal("123.00"),
            country=ns.pl,
            source=PriceSource.PRICEFIGHTER,
            stored_source=PriceSource.BASELINE,
        )

        assert report.applied
        cp = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, customer_representation__isnull=True
        )
        assert cp.source == PriceSource.BASELINE
        history = (
            PriceHistory.objects.filter(product=ns.chair, channel=ns.channel, country=ns.pl)
            .order_by("-created_at")
            .first()
        )
        assert history.source == PriceSource.BASELINE


@pytest.mark.django_db
class TestEditPriceBounds:
    def test_admin_edit_below_map_is_rejected(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("200.00"))

        report = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("50.00"), country=ns.pl)

        assert report.applied == []
        assert any(s["country"] == "PL" and "below floor" in s["reason"] for s in report.skipped)
        pl_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl)
        assert pl_price.gross_value == Decimal("123.00")  # untouched

    def test_admin_edit_partial_skip_across_countries_without_country_param(self, prices_populated):
        """No `country` -> propagate to all 3 (PL/DE/FR, rates 23%/19%/20%). A MAP of 131.00
        against value=110.00 rejects only DE (gross=130.90 < floor); PL (135.30) and FR
        (132.00) clear it — the report must reflect the split, not an all-or-nothing outcome."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("131.00"))

        report = edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("110.00"))

        assert {cp.country_id for cp in report.applied} == {ns.pl.pk, ns.fr.pk}
        assert len(report.skipped) == 1
        assert report.skipped[0]["country"] == "DE"
        assert "below floor" in report.skipped[0]["reason"]
        de_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de)
        assert de_price.gross_value == Decimal("119.00")  # untouched — the reject never wrote it

    def test_baseline_below_map_clamps(self, prices_populated):
        """Baseline fill-only: clear the existing row first so there's a gap for it to fill."""
        ns = prices_populated
        CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel, country=ns.pl).delete()
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("200.00"))

        report = edit_price(
            channel=ns.channel,
            sku="CHAIR-001",
            value=Decimal("50.00"),
            country=ns.pl,
            currency_code=ns.pln.iso3,
            source=PriceSource.BASELINE,
        )

        assert len(report.applied) == 1
        assert report.applied[0].gross_value == Decimal("200.00")
        # The clamp must be traceable in the report, not indistinguishable from a plain apply.
        assert report.clamped == [{"country": "PL", "currency_id": ns.pln.pk, "reason": report.clamped[0]["reason"]}]
        assert "clamped to floor 200.00" in report.clamped[0]["reason"]


@pytest.mark.django_db
class TestBulkEditPricesSpecialOnly:
    def test_special_only_branch_updates_existing_rows(self, prices_populated):
        """items without `value` (only `special_value`) hit the special-only branch."""
        ns = prices_populated
        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("80.00")}],
        )
        assert result["updated"] == 1
        assert result["changes_logged"] == 3  # PL/DE/FR all have an existing row
        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.special_gross_value is not None

    def test_special_only_edit_does_not_seize_ownership_of_automated_row(self, prices_populated):
        """A special-only edit (no `value`) must not relabel a pricefighter/baseline-owned row to
        admin_edit — that would permanently lock the base price out of automated recalcs after a
        CMS operator merely touched the promotional special price."""
        ns = prices_populated
        CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel).update(source=PriceSource.PRICEFIGHTER)

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("80.00")}],
        )

        assert result["updated"] == 1
        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.PRICEFIGHTER
        assert cp.special_gross_value is not None

    def test_special_only_all_rows_rejected_lands_in_errors_not_silent_success(self, prices_populated):
        """Guard rejects every row (MAP) — must not count as updated/synced, reason must surface."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("100.00"))
        before = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln
        ).special_gross_value

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("80.00")}],  # special_gross ~98.40 < MAP 100
        )

        assert result["updated"] == 0
        assert result["changes_logged"] == 0
        assert len(result["errors"]) == 1
        assert result["errors"][0]["sku"] == "CHAIR-001"
        assert "below floor" in result["errors"][0]["error"]
        after = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln
        ).special_gross_value
        assert after == before


@pytest.mark.django_db
class TestBulkEditPricesCaseInsensitiveSku:
    def test_differently_cased_sku_still_gets_bounds_enforced(self, prices_populated):
        """A differently-cased SKU in the value branch must still be resolved against the same
        bounds row as the canonical casing — a case-sensitive `sku__in` lookup would silently
        drop it from the prefetch (floor=None) and let it write below MAP unclamped/unrejected."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("200.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "chair-001", "value": Decimal("50.00")}],
        )

        assert result["updated"] == 0
        assert len(result["errors"]) == 1
        assert "below floor" in result["errors"][0]["error"]

    def test_differently_cased_sku_special_only_still_updates(self, prices_populated):
        ns = prices_populated
        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "chair-001", "special_value": Decimal("80.00")}],
        )
        assert result["updated"] == 1
        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.special_gross_value is not None

    def test_differently_cased_sku_special_only_gets_bounds_enforced(self, prices_populated):
        """The special-only branch prefetches bounds keyed by the resolved product's canonical
        sku (see _prefetch_special_only_context) — a lookup keyed by the request's raw casing
        would silently miss the entry (floor=None) and let a below-MAP special through
        unclamped/unrejected. Regression for a real bug: bounds dict built with
        cp.product.sku, looked up with item["sku"]."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("100.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "chair-001", "special_value": Decimal("80.00")}],  # special_gross ~98.40 < MAP 100
        )

        assert result["updated"] == 0
        assert len(result["errors"]) == 1
        assert "below floor" in result["errors"][0]["error"]

    def test_differently_cased_sku_value_branch_gets_bounds_enforced(self, prices_populated):
        """Same family of bug, value branch: _prefetch_value_branch_context/edit_price must key
        bounds by the resolved canonical sku so a mismatched request casing still hits the MAP row."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("200.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "Chair-001", "value": Decimal("50.00")}],
        )

        assert result["updated"] == 0
        assert len(result["errors"]) == 1
        assert "below floor" in result["errors"][0]["error"]


@pytest.mark.django_db
class TestBulkEditPricesBadCurrency:
    def test_unknown_currency_lands_per_item_error_not_500(self, prices_populated):
        """An unknown currency_code must be reported as a per-item error, same contract as any
        other rejected item — not raise Currency.DoesNotExist and blow up the whole batch."""
        ns = prices_populated
        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="XXX",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("80.00")}],
        )
        assert result["updated"] == 0
        assert len(result["errors"]) == 1
        assert "XXX" in result["errors"][0]["error"]

    def test_unknown_currency_value_branch_lands_per_item_error_not_500(self, prices_populated):
        ns = prices_populated
        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="XXX",
            items=[{"sku": "CHAIR-001", "value": Decimal("50.00")}],
        )
        assert result["updated"] == 0
        assert len(result["errors"]) == 1
        assert "XXX" in result["errors"][0]["error"]


@pytest.mark.django_db
class TestBulkEditPricesQueryCount:
    def test_value_branch_prefetch_query_count_is_constant(self, channel_setup, django_assert_max_num_queries):
        """_prefetch_value_branch_context() replaces what used to be ~5 queries per SKU inside
        edit_price() (product lookup, countries, tax rates, existing rows, currency) with a
        handful of queries for the whole batch — isolated here from the per-row write/savepoint
        cost of bulk_edit_prices itself (inherent to update_or_create, unrelated to this fix),
        which would otherwise dominate and mask the prefetch behavior being tested."""
        from django_pricemanager.services.price_edit_service import _prefetch_value_branch_context

        small_skus = [f"SMALL-{i:03d}" for i in range(5)]
        large_skus = [f"LARGE-{i:03d}" for i in range(30)]
        for sku in small_skus + large_skus:
            ProductRepresentation.objects.create(sku=sku, tax_class=channel_setup.standard)

        with django_assert_max_num_queries(10):
            small_prefetch = _prefetch_value_branch_context(channel_setup.channel, small_skus, "PLN")
        with django_assert_max_num_queries(10):
            large_prefetch = _prefetch_value_branch_context(channel_setup.channel, large_skus, "PLN")

        assert len(small_prefetch.products_by_sku_lower) == 5
        assert len(large_prefetch.products_by_sku_lower) == 30

    def test_value_branch_writes_still_succeed_using_the_prefetch(self, channel_setup):
        """End-to-end sanity check that bulk_edit_prices actually applies all items when using
        the batched prefetch (not just that the prefetch function alone is cheap)."""
        skus = [f"BULKW-{i:03d}" for i in range(10)]
        for sku in skus:
            ProductRepresentation.objects.create(sku=sku, tax_class=channel_setup.standard)
        items = [{"sku": sku, "value": Decimal("99.00")} for sku in skus]

        result = bulk_edit_prices(channel=channel_setup.channel, currency_code="PLN", items=items)

        assert result["updated"] == 10
        assert result["errors"] == []


@pytest.mark.django_db
class TestBulkEditPricesGuardSkipAll:
    def test_value_branch_all_countries_rejected_lands_in_errors(self, prices_populated):
        """Value branch: every country rejected by the guard must not count as a success."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("200.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "value": Decimal("50.00")}],
        )

        assert result["updated"] == 0
        assert result["changes_logged"] == 0
        assert len(result["errors"]) == 1
        assert "below floor" in result["errors"][0]["error"]
        pl_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl)
        assert pl_price.gross_value == Decimal("123.00")  # untouched


@pytest.mark.django_db
class TestBulkEditPricesGuardPartialSkip:
    def test_value_branch_partial_skip_is_reported_not_swallowed(self, prices_populated):
        """Value branch: when the guard rejects only SOME of an item's countries (others apply
        fine), the item still counts as updated — but the rejected country must surface in the
        bulk response's skipped list, not vanish. {updated, changes_logged, errors} alone can't
        represent this; a caller relying on `errors == []` would otherwise believe every country
        was written."""
        ns = prices_populated
        # PL rate 23%, DE 19%, FR 20% — net=100 gives PL gross=123.00, DE=119.00, FR=120.00.
        # A floor of 120.00 rejects only DE (admin_edit enforce_mode defaults to reject).
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("120.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "value": Decimal("100.00")}],
        )

        assert result["updated"] == 1
        assert result["errors"] == []
        assert len(result["skipped"]) == 1
        skipped = result["skipped"][0]
        assert skipped["sku"] == "CHAIR-001"
        assert skipped["country"] == "DE"
        assert "below floor" in skipped["reason"]

        de_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de)
        assert de_price.source == "csv_import"  # rejected write left the row untouched
        pl_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl)
        assert pl_price.source == "admin_edit"  # applied


@pytest.mark.django_db
class TestBulkEditPricesSpecialOnlyPartialSkip:
    def test_special_only_partial_skip_is_reported_not_swallowed(self, prices_populated):
        """Special-only branch: guard rejects only SOME countries (others apply fine) — the
        rejected country must surface in the bulk response's skipped list, mirroring the value
        branch. Before this fix, the special-only branch only surfaced a reason when EVERY
        country was rejected — a partial reject silently vanished."""
        ns = prices_populated
        # PL rate 23%, DE 19%, FR 20% — special net=100 gives PL gross=123.00, DE=119.00, FR=120.00.
        # A floor of 120.00 rejects only DE (admin_edit enforce_mode defaults to reject).
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("120.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("100.00")}],
        )

        assert result["updated"] == 1
        assert result["errors"] == []
        assert len(result["skipped"]) == 1
        skipped = result["skipped"][0]
        assert skipped["sku"] == "CHAIR-001"
        assert skipped["country"] == "DE"
        assert "below floor" in skipped["reason"]

        de_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de)
        assert de_price.special_gross_value is None  # rejected write left the row untouched
        pl_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl)
        assert pl_price.special_gross_value == Decimal("123.00")  # applied

    def test_special_only_clamp_is_reported_and_persisted_via_bulk_update(self, prices_populated):
        """Special-only branch writes via CurrentPrice.bulk_update() now (not per-row .save()) —
        a clamped row must both surface in the bulk response's clamped list AND actually persist
        the clamped value to the database."""
        from django_pricemanager.models.price_write_policy import PriceSourcePolicy, PriceWriteEnforceMode

        ns = prices_populated
        PriceSourcePolicy.objects.create(source=PriceSource.ADMIN_EDIT, enforce_mode=PriceWriteEnforceMode.CLAMP)
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("120.00"))

        result = bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "CHAIR-001", "special_value": Decimal("100.00")}],
        )

        assert result["updated"] == 1
        assert len(result["clamped"]) == 1
        clamped = result["clamped"][0]
        assert clamped["sku"] == "CHAIR-001"
        assert clamped["country"] == "DE"
        assert "clamped to floor 120.00" in clamped["reason"]

        de_price = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.de)
        assert de_price.special_gross_value == Decimal("120.00")  # clamped, not skipped


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

    def test_preview_predicts_reject_below_floor(self, prices_populated):
        """Preview must run the same guard/bounds decision the save will (plan-03 review
        follow-up: preview showed a clean amount, then the PATCH rejected it). PL rate 23%,
        DE 19%, FR 20% — net=100 gives DE gross=119.00, below a 120.00 floor; admin_edit
        enforce_mode defaults to reject."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("120.00"))
        prices_before = CurrentPrice.objects.count()

        result = preview_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"))
        by_country = {entry["country"]: entry for entry in result}

        de = by_country["DE"]
        assert de["would_be"] == "skipped"
        assert "below floor 120.00" in de["reason"]
        assert Decimal(de["floor"]) == Decimal("120.00")
        assert Decimal(de["gross"]) == Decimal("119.00")  # the requested amount the guard rejected

        pl = by_country["PL"]
        assert pl["would_be"] == "applied"
        assert pl["reason"] is None
        assert CurrentPrice.objects.count() == prices_before  # still read-only

    def test_preview_predicts_clamp_with_clamp_policy(self, prices_populated):
        """With enforce_mode=clamp the preview shows the clamped values that WILL be
        persisted, not the requested ones."""
        from django_pricemanager.models.price_write_policy import PriceSourcePolicy, PriceWriteEnforceMode

        ns = prices_populated
        PriceSourcePolicy.objects.create(source=PriceSource.ADMIN_EDIT, enforce_mode=PriceWriteEnforceMode.CLAMP)
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("120.00"))

        result = preview_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("100.00"))
        by_country = {entry["country"]: entry for entry in result}

        de = by_country["DE"]
        assert de["would_be"] == "clamped"
        assert "clamped to floor 120.00" in de["reason"]
        assert Decimal(de["gross"]) == Decimal("120.00")  # the clamped value edit_price would save

        pl = by_country["PL"]
        assert pl["would_be"] == "applied"
        assert Decimal(pl["gross"]) == Decimal("123.00")
