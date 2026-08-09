# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for workers.create_price_from_source() — legacy generation write path.

Exercises the guard/bounds behavior of the PRICE_SOURCE_GENERATED dual-write, which had
zero test coverage even though it writes CurrentPrice with writer=PriceSource.GENERATION.
"""

from decimal import Decimal

import pytest

import django_pricemanager.workers as workers_module
from django_pricemanager.models import CurrentPrice, Price, PriceList, SaleChannel
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_bounds import PriceBoundsConfig
from django_pricemanager.models.pricelist import PriceListStatusEnum
from django_pricemanager.workers import create_price_from_source


@pytest.fixture
def dual_write_enabled(monkeypatch):
    monkeypatch.setattr(workers_module, "PRICEMANAGER_DUAL_WRITE", True)


def _make_price_original(ns, product, net=Decimal("100.00")):
    sale_channel = SaleChannel.objects.create(
        idx=f"sc-src-{product.sku.lower()}",
        name=f"Source {product.sku}",
        channel=ns.channel,
        country=ns.pl,
        price_source=SaleChannel.PRICE_SOURCE_CSV,
    )
    pricelist = PriceList.objects.create(
        sale_channel=sale_channel,
        currency=ns.pln,
        country=ns.pl,
        status=PriceListStatusEnum.READY,
    )
    tax_rate = ns.rates[(product.tax_class.idx, "PL")]
    gross = tax_rate.gross_price(net)
    return Price.objects.create(
        pricelist=pricelist, product=product, net_value=net, gross_value=gross, tax_rate=tax_rate
    )


def _make_target_pricelist(ns):
    sale_channel = SaleChannel.objects.create(
        idx="sc-generated-pl",
        name="Generated PL",
        channel=ns.channel,
        country=ns.pl,
        price_source=SaleChannel.PRICE_SOURCE_GENERATED,
    )
    return PriceList.objects.create(
        sale_channel=sale_channel,
        currency=ns.pln,
        country=ns.pl,
        status=PriceListStatusEnum.IN_PROGRESS,
    )


@pytest.mark.django_db
class TestCreatePriceFromSourceDualWrite:
    def test_writes_current_price_with_generation_source(self, products, dual_write_enabled):
        ns = products
        price_original = _make_price_original(ns, ns.chair)
        target_pricelist = _make_target_pricelist(ns)

        create_price_from_source(target_pricelist, price_original, ns.pl, ns.channel.calculate_direction)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.GENERATION
        assert cp.gross_value == price_original.gross_value

    def test_generation_overwrites_existing_admin_edit_row(self, products, dual_write_enabled):
        """writer=GENERATION is not pricefighter/baseline — precedence keeps overwriting everything."""
        ns = products
        target_pricelist = _make_target_pricelist(ns)
        rate = ns.rates[("standard", "PL")]
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=rate,
            net_value=Decimal("50.00"),
            gross_value=rate.gross_price(Decimal("50.00")),
            source=PriceSource.ADMIN_EDIT,
        )
        price_original = _make_price_original(ns, ns.chair, net=Decimal("999.00"))

        create_price_from_source(target_pricelist, price_original, ns.pl, ns.channel.calculate_direction)

        # GENERATION is not pricefighter/baseline — precedence still overwrites (today's behavior).
        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.GENERATION
        assert cp.net_value == Decimal("999.00")

    @pytest.mark.parametrize("existing_source", [PriceSource.PRICEFIGHTER, PriceSource.BASELINE])
    def test_generation_overwrites_automated_sources(self, products, dual_write_enabled, existing_source):
        """writer=GENERATION is not pricefighter/baseline itself, so the guard's special-casing
        of those two writers never applies here — precedence still overwrites unconditionally,
        same as the admin_edit case above. Regression guard: a future change to the catch-all
        branch of _precedence_allows must not silently start skipping these rows."""
        ns = products
        target_pricelist = _make_target_pricelist(ns)
        rate = ns.rates[("standard", "PL")]
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=rate,
            net_value=Decimal("50.00"),
            gross_value=rate.gross_price(Decimal("50.00")),
            source=existing_source,
        )
        price_original = _make_price_original(ns, ns.chair, net=Decimal("999.00"))

        create_price_from_source(target_pricelist, price_original, ns.pl, ns.channel.calculate_direction)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.GENERATION
        assert cp.net_value == Decimal("999.00")

    def test_clamps_to_map_bound(self, products, dual_write_enabled):
        ns = products
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("500.00"))
        price_original = _make_price_original(ns, ns.chair, net=Decimal("10.00"))
        target_pricelist = _make_target_pricelist(ns)

        create_price_from_source(target_pricelist, price_original, ns.pl, ns.channel.calculate_direction)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.gross_value == Decimal("500.00")
        assert cp.source == PriceSource.GENERATION

    def test_noop_when_dual_write_disabled(self, products, monkeypatch):
        monkeypatch.setattr(workers_module, "PRICEMANAGER_DUAL_WRITE", False)
        ns = products
        price_original = _make_price_original(ns, ns.chair)
        target_pricelist = _make_target_pricelist(ns)

        create_price_from_source(target_pricelist, price_original, ns.pl, ns.channel.calculate_direction)

        assert not CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel, country=ns.pl).exists()

    def test_bulk_context_matches_per_row_fallback(self, products, dual_write_enabled):
        """_build_dual_write_ctx built once for many rows must match the single-row fallback path."""
        ns = products
        target_pricelist = _make_target_pricelist(ns)
        chair_price = _make_price_original(ns, ns.chair, net=Decimal("100.00"))
        food_price = _make_price_original(ns, ns.food, net=Decimal("20.00"))

        ctx = workers_module._build_dual_write_ctx(target_pricelist, [chair_price, food_price], ns.channel, ns.pl)
        create_price_from_source(
            target_pricelist, chair_price, ns.pl, ns.channel.calculate_direction, dual_write_ctx=ctx
        )
        create_price_from_source(
            target_pricelist, food_price, ns.pl, ns.channel.calculate_direction, dual_write_ctx=ctx
        )

        assert CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel, source=PriceSource.GENERATION).exists()
        assert CurrentPrice.objects.filter(product=ns.food, channel=ns.channel, source=PriceSource.GENERATION).exists()
