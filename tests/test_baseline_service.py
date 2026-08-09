# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for baseline auto-price-from-cost."""

from decimal import Decimal

import pytest

from django_pricemanager.models import (
    BaselineConfig,
    BaselineTombstone,
    CurrentPrice,
    PriceHistory,
    ProductRepresentation,
    PurchaseCost,
)
from django_pricemanager.models.baseline_config import PriceRounding
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_bounds import PriceBoundsConfig
from django_pricemanager.services import price_edit_service
from django_pricemanager.services.baseline_service import recalculate_baseline_bulk, recalculate_baseline_for_product


@pytest.mark.django_db
class TestRecalculateBaselineForProduct:
    def test_noop_when_channel_not_opted_in(self, prices_populated):
        ns = prices_populated
        PurchaseCost.objects.create(
            product=ns.food, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("10.00")
        )
        result = recalculate_baseline_for_product(ns.food, ns.channel)
        assert result == {"applied": [], "skipped": []}

    def test_noop_without_baseline_config(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        PurchaseCost.objects.create(
            product=ns.food, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("10.00")
        )
        result = recalculate_baseline_for_product(ns.food, ns.channel)
        assert result == {"applied": [], "skipped": []}

    def test_noop_without_purchase_cost(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        result = recalculate_baseline_for_product(ns.food, ns.channel)
        assert result == {"applied": [], "skipped": []}

    def test_creates_price_for_new_product_markup_math(self, prices_populated):
        """New SKU without an existing price: baseline = cost x (1+markup), source=BASELINE."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"), rounding=PriceRounding.NONE)
        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        result = recalculate_baseline_for_product(ns.bundle, ns.channel)

        pl_price = next(cp for cp in result["applied"] if cp.country_id == ns.pl.pk)
        rate = ns.rates[("standard", "PL")]
        expected_net = Decimal("100.00") * Decimal("1.20")
        expected_gross = rate.gross_price(expected_net)
        assert pl_price.gross_value == expected_gross
        assert pl_price.source == PriceSource.BASELINE
        assert PriceHistory.objects.filter(product=ns.bundle, channel=ns.channel, source=PriceSource.BASELINE).exists()

    def test_fill_only_does_not_overwrite_existing_row(self, prices_populated):
        """Baseline never touches CHAIR-001/PL — it already has a csv_import price."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("999.00")
        )

        before = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln
        ).gross_value
        result = recalculate_baseline_for_product(ns.chair, ns.channel)
        after = CurrentPrice.objects.get(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln
        ).gross_value

        assert before == after
        assert any(s["country"] == "PL" for s in result["skipped"])

    def test_rounding_applied_to_gross(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"), rounding=PriceRounding.P99)
        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        result = recalculate_baseline_for_product(ns.bundle, ns.channel)
        pl_price = next(cp for cp in result["applied"] if cp.country_id == ns.pl.pk)
        assert pl_price.gross_value % 1 == Decimal("0.99")

    def test_clamps_to_map_bound(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.01"))
        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("10.00")
        )
        PriceBoundsConfig.objects.create(product=ns.bundle, channel=ns.channel, map_value=Decimal("500.00"))

        result = recalculate_baseline_for_product(ns.bundle, ns.channel)
        pl_price = next(cp for cp in result["applied"] if cp.country_id == ns.pl.pk)
        assert pl_price.gross_value == Decimal("500.00")

    def test_tombstoned_pair_is_skipped(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        BaselineTombstone.objects.create(product=ns.bundle, channel=ns.channel)
        # PurchaseCost.save() also triggers the signal — tombstone must already exist to block it
        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        result = recalculate_baseline_for_product(ns.bundle, ns.channel)
        assert result == {"applied": [], "skipped": []}
        assert not CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel).exists()


@pytest.mark.django_db
class TestRecalculateBaselinePreservesSpecial:
    def test_refreshing_own_row_preserves_admin_set_special_price(self, prices_populated):
        """A cost-triggered recalc refreshing baseline's own prior row must not wipe a
        special-price promo an admin layered on top via the special-only bulk-edit branch
        (stored_source stays 'baseline' there) — only a brand-new row gets its specials
        explicitly nulled."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"), rounding=PriceRounding.NONE)
        cost = PurchaseCost.objects.create(
            product=ns.bundle,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            net_cost=Decimal("100.00"),
        )
        recalculate_baseline_for_product(ns.bundle, ns.channel)
        cp = CurrentPrice.objects.get(product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.BASELINE
        assert cp.special_gross_value is None

        # Admin layers a promotional special price on top — stored_source stays "baseline".
        price_edit_service.bulk_edit_prices(
            channel=ns.channel,
            currency_code="PLN",
            items=[{"sku": "BUNDLE-001", "special_value": Decimal("90.00")}],
        )
        cp.refresh_from_db()
        assert cp.source == PriceSource.BASELINE
        assert cp.special_gross_value is not None
        special_gross_before = cp.special_gross_value
        gross_before_cost_change = cp.gross_value

        # Cost changes — baseline recalc refreshes its own row.
        cost.net_cost = Decimal("110.00")
        cost.save()
        recalculate_baseline_for_product(ns.bundle, ns.channel)

        cp.refresh_from_db()
        assert cp.gross_value != gross_before_cost_change  # base amount recalculated
        assert cp.special_gross_value == special_gross_before  # promo untouched

    def test_overwriting_foreign_row_preserves_its_special_price(self, prices_populated):
        """Baseline overwriting a recalc_overwritable foreign row (csv_import with a live
        promo) must update the base net/gross only — silently nulling special_net/gross
        would kill an operator's promotion on every cost change (plan-03 review follow-up:
        the old condition `existing_source != BASELINE` also matched this overwrite path)."""
        from django_pricemanager.models.price_write_policy import PriceSourcePolicy

        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"), rounding=PriceRounding.NONE)
        PriceSourcePolicy.objects.create(source=PriceSource.CSV_IMPORT, recalc_overwritable=True)
        PurchaseCost.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            net_cost=Decimal("999.00"),
        )
        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.CSV_IMPORT
        cp.special_net_value = Decimal("80.00")
        cp.special_gross_value = Decimal("98.40")
        cp.save(update_fields=["special_net_value", "special_gross_value"])

        result = recalculate_baseline_for_product(ns.chair, ns.channel)

        cp.refresh_from_db()
        assert any(a.country_id == ns.pl.pk for a in result["applied"])
        assert cp.source == PriceSource.BASELINE  # overwrite happened (policy allows it)
        assert cp.special_net_value == Decimal("80.00")  # promo preserved
        assert cp.special_gross_value == Decimal("98.40")


@pytest.mark.django_db
class TestRecalculateBaselineBulk:
    def test_recalculates_each_pair_and_dedupes(self, prices_populated):
        """PurchaseCost.bulk_create() bypasses the signal — callers must use this entrypoint."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        PurchaseCost.objects.bulk_create(
            [
                PurchaseCost(
                    product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
                ),
            ]
        )
        assert not CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel).exists()

        result = recalculate_baseline_bulk([(ns.bundle, ns.channel), (ns.bundle, ns.channel)])

        assert len(result["applied"]) == 3  # PL/DE/FR, counted once despite the duplicate pair
        assert CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel, source=PriceSource.BASELINE).exists()

    def test_write_query_count_independent_of_pair_count(self, prices_populated):
        """CurrentPrice writes must go through bulk_create/bulk_update, not a per-row
        update_or_create loop — otherwise write query count scales with (product x country)
        count instead of staying constant like the read side already does."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))

        def _new_product_with_cost(sku: str) -> ProductRepresentation:
            product = ProductRepresentation.objects.create(sku=sku, tax_class=ns.standard)
            PurchaseCost.objects.create(
                product=product,
                channel=ns.channel,
                country=ns.pl,
                currency=ns.pln,
                net_cost=Decimal("100.00"),
            )
            return product

        one = _new_product_with_cost("BASE-QCOUNT-001")
        with CaptureQueriesContext(connection) as ctx_one:
            recalculate_baseline_bulk([(one, ns.channel)])
        count_one = len(ctx_one.captured_queries)

        many = [_new_product_with_cost(f"BASE-QCOUNT-{i:03d}") for i in range(2, 7)]
        with CaptureQueriesContext(connection) as ctx_many:
            recalculate_baseline_bulk([(p, ns.channel) for p in many])
        count_many = len(ctx_many.captured_queries)

        assert count_many == count_one


@pytest.mark.django_db
class TestReadFromCurrentWarning:
    def test_warns_when_read_from_current_disabled(self, prices_populated, caplog):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        recalculate_baseline_for_product(ns.bundle, ns.channel)

        assert any("PRICEMANAGER_READ_FROM_CURRENT off" in r.message for r in caplog.records)

    def test_no_warning_when_read_from_current_enabled(self, prices_populated, caplog):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        from django_pricemanager.models import PriceManagerSettings

        settings_row = PriceManagerSettings.load()
        settings_row.read_from_current = True
        settings_row.save()

        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )
        caplog.clear()
        recalculate_baseline_for_product(ns.bundle, ns.channel)

        assert not any("PRICEMANAGER_READ_FROM_CURRENT off" in r.message for r in caplog.records)


@pytest.mark.django_db
class TestPurchaseCostTriggersBaseline:
    def test_saving_purchase_cost_recalculates_baseline(self, prices_populated, django_capture_on_commit_callbacks):
        """post_save(PurchaseCost) fires the baseline recalc automatically, on commit."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))

        assert not CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel).exists()
        with django_capture_on_commit_callbacks(execute=True):
            PurchaseCost.objects.create(
                product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
            )

        assert CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel, source=PriceSource.BASELINE).exists()

    def test_multiple_saves_in_one_transaction_batch_into_one_recalc_call(
        self, prices_populated, django_capture_on_commit_callbacks, mocker
    ):
        """N PurchaseCost saves inside one transaction must trigger exactly one
        recalculate_baseline_bulk call covering all of them, not N single-pair calls — the
        atlas cost stream saves one PurchaseCost per product, often many per sync transaction."""
        from django.db import transaction

        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))

        spy = mocker.patch(
            "django_pricemanager.services.baseline_service.recalculate_baseline_bulk", wraps=recalculate_baseline_bulk
        )
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                PurchaseCost.objects.create(
                    product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
                )
                PurchaseCost.objects.create(
                    product=ns.food, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("10.00")
                )

        assert spy.call_count == 1
        pairs = spy.call_args[0][0]
        assert {(p.pk, c.pk) for p, c in pairs} == {(ns.bundle.pk, ns.channel.pk), (ns.food.pk, ns.channel.pk)}

    def test_rolled_back_transaction_does_not_starve_the_next_transactions_flush(
        self, prices_populated, django_capture_on_commit_callbacks
    ):
        """A PurchaseCost save whose transaction rolls back must not leave stale pending state
        that prevents a later, unrelated transaction's flush from being scheduled."""
        from django.db import IntegrityError, transaction

        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        # A product prices_populated already gave a csv_import price to — irrelevant here since
        # this save is rolled back, but distinct from ns.bundle (the one that must still work).
        rolled_back_product = ns.food

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PurchaseCost.objects.create(
                    product=rolled_back_product,
                    channel=ns.channel,
                    country=ns.pl,
                    currency=ns.pln,
                    net_cost=Decimal("100.00"),
                )
                raise IntegrityError("simulated failure — forces a rollback")

        with django_capture_on_commit_callbacks(execute=True):
            PurchaseCost.objects.create(
                product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("10.00")
            )

        assert CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel, source=PriceSource.BASELINE).exists()


@pytest.mark.django_db(transaction=True)
class TestPurchaseCostSignalRealAutocommit:
    def test_saving_purchase_cost_outside_atomic_recalculates_baseline(self, prices_populated):
        """Real autocommit (no surrounding atomic block — bare shell/management-command/task
        save): Django runs the on_commit callback synchronously and immediately as part of the
        on_commit() call itself. The (product, channel) pair must be added to the pending dict
        BEFORE transaction.on_commit(_flush_pending) is registered, or _flush_pending reads an
        empty dict and the pair is added afterward to an already-orphaned one, silently dropping
        the recalc. Regular `@pytest.mark.django_db` tests wrap the test body in an outer atomic
        block and can't reproduce this — they defer on_commit regardless of ordering."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))

        PurchaseCost.objects.create(
            product=ns.bundle, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        assert CurrentPrice.objects.filter(product=ns.bundle, channel=ns.channel, source=PriceSource.BASELINE).exists()


@pytest.mark.django_db
class TestDeletePricesTombstone:
    def test_delete_on_baseline_channel_creates_tombstone(self, prices_populated):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()

        price_edit_service.delete_prices(ns.channel, "CHAIR-001")

        assert BaselineTombstone.objects.filter(product=ns.chair, channel=ns.channel).exists()

    def test_delete_on_non_baseline_channel_does_not_create_tombstone(self, prices_populated):
        ns = prices_populated
        price_edit_service.delete_prices(ns.channel, "CHAIR-001")
        assert not BaselineTombstone.objects.filter(product=ns.chair, channel=ns.channel).exists()

    def test_currency_scoped_delete_does_not_create_tombstone(self, prices_populated):
        """BaselineTombstone has no currency dimension — a delete scoped to one currency must
        not exclude the whole (product, channel) pair from recalc on other markets."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()

        price_edit_service.delete_prices(ns.channel, "CHAIR-001", currency_code=ns.pln.iso3)

        assert not BaselineTombstone.objects.filter(product=ns.chair, channel=ns.channel).exists()

    def test_deleted_price_not_resurrected_by_later_cost_save(
        self, prices_populated, django_capture_on_commit_callbacks
    ):
        """Full cycle: delete_prices() writes a tombstone, then a real PurchaseCost.save() fires
        the post_save signal — proves the tombstone keys delete_prices() writes are exactly the
        keys recalculate_baseline_for_product() filters on, not just that some row exists."""
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))

        price_edit_service.delete_prices(ns.channel, "CHAIR-001")
        assert not CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel).exists()

        with django_capture_on_commit_callbacks(execute=True):
            PurchaseCost.objects.create(
                product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("50.00")
            )

        assert not CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel).exists()

    def test_removing_tombstone_lets_baseline_resurrect_price(
        self, prices_populated, django_capture_on_commit_callbacks
    ):
        ns = prices_populated
        ns.channel.baseline_enabled = True
        ns.channel.save()
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        price_edit_service.delete_prices(ns.channel, "CHAIR-001")
        BaselineTombstone.objects.filter(product=ns.chair, channel=ns.channel).delete()

        with django_capture_on_commit_callbacks(execute=True):
            PurchaseCost.objects.create(
                product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("50.00")
            )

        assert CurrentPrice.objects.filter(
            product=ns.chair, channel=ns.channel, country=ns.pl, source=PriceSource.BASELINE
        ).exists()
