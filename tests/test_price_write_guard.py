# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the CurrentPrice write guard — precedence matrix and bounds."""

from decimal import Decimal

import pytest

from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_write_policy import PriceSourcePolicy, PriceWriteEnforceMode
from django_pricemanager.services.price_write_guard import PriceBounds, guard_price_write

_VALUES = {"net_value": Decimal("100.00"), "gross_value": Decimal("123.00"), "tax_rate": None}


class _FakeTaxRate:
    """Minimal stand-in — only net_price() is exercised by the clamp path."""

    def __init__(self, ratio: Decimal):
        self.ratio = ratio

    def net_price(self, gross: Decimal) -> Decimal:
        return gross / self.ratio


@pytest.mark.django_db
class TestPrecedenceMatrix:
    @pytest.mark.parametrize(
        "existing_source",
        [
            None,
            PriceSource.CSV_IMPORT,
            PriceSource.GENERATION,
            PriceSource.MIGRATION,
            PriceSource.ADMIN_EDIT,
            PriceSource.BASELINE,
            PriceSource.PRICEFIGHTER,
        ],
    )
    def test_admin_edit_overwrites_everything(self, existing_source):
        decision = guard_price_write(
            existing_source=existing_source, new_values=dict(_VALUES), writer=PriceSource.ADMIN_EDIT
        )
        assert decision.status == "applied"
        assert decision.source == PriceSource.ADMIN_EDIT

    @pytest.mark.parametrize(
        "existing_source",
        [
            None,
            PriceSource.CSV_IMPORT,
            PriceSource.GENERATION,
            PriceSource.BASELINE,
            PriceSource.PRICEFIGHTER,
            PriceSource.ADMIN_EDIT,
            PriceSource.MIGRATION,
        ],
    )
    def test_csv_import_overwrites_everything_except_nothing(self, existing_source):
        """Includes admin_edit/migration explicitly — csv_import is unconditional, same as admin."""
        decision = guard_price_write(
            existing_source=existing_source, new_values=dict(_VALUES), writer=PriceSource.CSV_IMPORT
        )
        assert decision.status == "applied"

    @pytest.mark.parametrize(
        "writer",
        [PriceSource.GENERATION, PriceSource.MIGRATION],
    )
    @pytest.mark.parametrize(
        "existing_source",
        [
            None,
            PriceSource.CSV_IMPORT,
            PriceSource.GENERATION,
            PriceSource.BASELINE,
            PriceSource.PRICEFIGHTER,
            PriceSource.ADMIN_EDIT,
            PriceSource.MIGRATION,
        ],
    )
    def test_generation_and_migration_overwrite_everything(self, writer, existing_source):
        """Catch-all precedence branch — same unconditional-overwrite guarantee as csv_import,
        explicitly exercised against pricefighter/baseline rows so a future change to the
        catch-all in _precedence_allows can't silently start skipping these writers."""
        decision = guard_price_write(existing_source=existing_source, new_values=dict(_VALUES), writer=writer)
        assert decision.status == "applied"
        assert decision.source == writer

    def test_pricefighter_overwrites_baseline(self):
        decision = guard_price_write(
            existing_source=PriceSource.BASELINE, new_values=dict(_VALUES), writer=PriceSource.PRICEFIGHTER
        )
        assert decision.status == "applied"
        assert decision.source == PriceSource.PRICEFIGHTER

    def test_pricefighter_overwrites_own_row(self):
        decision = guard_price_write(
            existing_source=PriceSource.PRICEFIGHTER, new_values=dict(_VALUES), writer=PriceSource.PRICEFIGHTER
        )
        assert decision.status == "applied"

    def test_pricefighter_skips_admin_edit(self):
        decision = guard_price_write(
            existing_source=PriceSource.ADMIN_EDIT, new_values=dict(_VALUES), writer=PriceSource.PRICEFIGHTER
        )
        assert decision.status == "skipped"
        assert decision.source is None
        assert "admin_edit" in decision.reason

    def test_pricefighter_revert_to_baseline_writes_baseline_label(self):
        """writer=PRICEFIGHTER, stored_source=BASELINE on a source=pricefighter row -> applied, source=BASELINE."""
        decision = guard_price_write(
            existing_source=PriceSource.PRICEFIGHTER,
            new_values=dict(_VALUES),
            writer=PriceSource.PRICEFIGHTER,
            stored_source=PriceSource.BASELINE,
        )
        assert decision.status == "applied"
        assert decision.source == PriceSource.BASELINE

    def test_baseline_fill_only_creates_when_no_existing_row(self):
        decision = guard_price_write(existing_source=None, new_values=dict(_VALUES), writer=PriceSource.BASELINE)
        assert decision.status == "applied"
        assert decision.source == PriceSource.BASELINE

    @pytest.mark.parametrize(
        "existing_source",
        [
            PriceSource.CSV_IMPORT,
            PriceSource.ADMIN_EDIT,
            PriceSource.GENERATION,
            PriceSource.PRICEFIGHTER,
            PriceSource.MIGRATION,
        ],
    )
    def test_baseline_default_skips_existing_rows(self, existing_source):
        """Default policy (no PriceSourcePolicy rows seeded) = fill-only: baseline never overwrites an existing row."""
        decision = guard_price_write(
            existing_source=existing_source, new_values=dict(_VALUES), writer=PriceSource.BASELINE
        )
        assert decision.status == "skipped"

    def test_baseline_always_refreshes_its_own_prior_row(self):
        """Cost/VAT recalc must be able to update a row it wrote before — no seed config needed."""
        decision = guard_price_write(
            existing_source=PriceSource.BASELINE, new_values=dict(_VALUES), writer=PriceSource.BASELINE
        )
        assert decision.status == "applied"
        assert decision.source == PriceSource.BASELINE

    def test_baseline_overwrites_when_policy_allows(self):
        PriceSourcePolicy.objects.create(source=PriceSource.CSV_IMPORT, recalc_overwritable=True)
        decision = guard_price_write(
            existing_source=PriceSource.CSV_IMPORT, new_values=dict(_VALUES), writer=PriceSource.BASELINE
        )
        assert decision.status == "applied"
        assert decision.source == PriceSource.BASELINE


@pytest.mark.django_db
class TestStoredSourceLabel:
    def test_default_stored_source_is_writer(self):
        decision = guard_price_write(existing_source=None, new_values=dict(_VALUES), writer=PriceSource.CSV_IMPORT)
        assert decision.source == PriceSource.CSV_IMPORT

    def test_explicit_stored_source_overrides_writer_label(self):
        decision = guard_price_write(
            existing_source=None,
            new_values=dict(_VALUES),
            writer=PriceSource.PRICEFIGHTER,
            stored_source=PriceSource.BASELINE,
        )
        assert decision.source == PriceSource.BASELINE


@pytest.mark.django_db
class TestBoundsEnforcement:
    def test_no_bounds_hook_is_noop(self):
        decision = guard_price_write(
            existing_source=None, new_values=dict(_VALUES), writer=PriceSource.ADMIN_EDIT, bounds=None
        )
        assert decision.status == "applied"

    def test_within_floor_applies_unchanged(self):
        bounds = PriceBounds(floor=Decimal("50.00"))
        decision = guard_price_write(
            existing_source=None, new_values=dict(_VALUES), writer=PriceSource.BASELINE, bounds=bounds
        )
        assert decision.status == "applied"
        assert decision.values["gross_value"] == Decimal("123.00")

    def test_automated_writer_clamps_by_default(self):
        values = {
            "net_value": Decimal("50.00"),
            "gross_value": Decimal("60.00"),
            "tax_rate": _FakeTaxRate(Decimal("1.23")),
        }
        bounds = PriceBounds(floor=Decimal("100.00"))
        decision = guard_price_write(
            existing_source=None, new_values=values, writer=PriceSource.BASELINE, bounds=bounds
        )
        assert decision.status == "clamped"
        assert decision.values["gross_value"] == Decimal("100.00")
        assert decision.values["net_value"] == Decimal("100.00") / Decimal("1.23")

    def test_admin_edit_rejects_by_default(self):
        values = {"net_value": Decimal("50.00"), "gross_value": Decimal("60.00"), "tax_rate": None}
        bounds = PriceBounds(floor=Decimal("100.00"))
        decision = guard_price_write(
            existing_source=None, new_values=values, writer=PriceSource.ADMIN_EDIT, bounds=bounds
        )
        assert decision.status == "skipped"
        assert "below floor" in decision.reason

    def test_admin_edit_clamps_when_policy_overridden(self):
        PriceSourcePolicy.objects.create(source=PriceSource.ADMIN_EDIT, enforce_mode=PriceWriteEnforceMode.CLAMP)
        values = {"net_value": Decimal("50.00"), "gross_value": Decimal("60.00"), "tax_rate": None}
        bounds = PriceBounds(floor=Decimal("100.00"))
        decision = guard_price_write(
            existing_source=None, new_values=values, writer=PriceSource.ADMIN_EDIT, bounds=bounds
        )
        assert decision.status == "clamped"

    def test_tax_rate_change_never_rejects_even_with_reject_policy(self):
        PriceSourcePolicy.objects.create(source=PriceSource.TAX_RATE_CHANGE, enforce_mode=PriceWriteEnforceMode.REJECT)
        values = {
            "net_value": Decimal("50.00"),
            "gross_value": Decimal("60.00"),
            "tax_rate": _FakeTaxRate(Decimal("1.23")),
        }
        bounds = PriceBounds(floor=Decimal("100.00"))
        decision = guard_price_write(
            existing_source="admin_edit", new_values=values, writer=PriceSource.TAX_RATE_CHANGE, bounds=bounds
        )
        assert decision.status == "clamped"

    def test_special_gross_value_is_bounded_independently(self):
        values = {
            "net_value": Decimal("100.00"),
            "gross_value": Decimal("123.00"),
            "special_net_value": Decimal("40.00"),
            "special_gross_value": Decimal("49.20"),
            "tax_rate": _FakeTaxRate(Decimal("1.23")),
        }
        bounds = PriceBounds(floor=Decimal("100.00"))
        decision = guard_price_write(
            existing_source=None, new_values=values, writer=PriceSource.BASELINE, bounds=bounds
        )
        assert decision.status == "clamped"
        assert decision.values["gross_value"] == Decimal("123.00")  # untouched — already above floor
        assert decision.values["special_gross_value"] == Decimal("100.00")  # clamped

    def test_no_floor_configured_means_no_enforcement(self):
        bounds = PriceBounds(floor=None)
        decision = guard_price_write(
            existing_source=None, new_values=dict(_VALUES), writer=PriceSource.ADMIN_EDIT, bounds=bounds
        )
        assert decision.status == "applied"


@pytest.mark.django_db
class TestPolicyMapReuse:
    def test_passing_policy_map_skips_extra_queries(self, django_assert_num_queries):
        PriceSourcePolicy.objects.create(source=PriceSource.CSV_IMPORT, recalc_overwritable=True)
        from django_pricemanager.services.price_write_guard import load_policy_map

        policy_map = load_policy_map()
        with django_assert_num_queries(0):
            for _ in range(5):
                guard_price_write(
                    existing_source=PriceSource.CSV_IMPORT,
                    new_values=dict(_VALUES),
                    writer=PriceSource.BASELINE,
                    policy_map=policy_map,
                )
