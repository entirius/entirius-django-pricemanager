# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for price_bounds_service — floor computation, most-specific-wins, batch services."""

from decimal import Decimal

import pytest

from django_pricemanager.models import BaselineConfig, CurrentPrice, PurchaseCost
from django_pricemanager.models.baseline_config import PriceRounding
from django_pricemanager.models.price_bounds import PriceBoundsConfig
from django_pricemanager.services import price_bounds_service


@pytest.mark.django_db
class TestGetPriceBounds:
    def test_no_bounds_configured_returns_none_floor(self, prices_populated):
        ns = prices_populated
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result == {"floor": None, "ceiling": None, "baseline": None}

    def test_map_only(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("50.00"))
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == Decimal("50.00")

    def test_min_margin_only_uses_purchase_cost(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, min_margin_percent=Decimal("0.10"))
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        rate = ns.rates[("standard", "PL")]
        expected = rate.gross_price(Decimal("100.00") * Decimal("1.10"))
        assert result["floor"] == expected

    def test_map_and_min_margin_takes_the_higher(self, prices_populated):
        ns = prices_populated
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )
        rate = ns.rates[("standard", "PL")]
        cost_floor = rate.gross_price(Decimal("100.00") * Decimal("1.10"))
        PriceBoundsConfig.objects.create(
            product=ns.chair,
            channel=ns.channel,
            min_margin_percent=Decimal("0.10"),
            map_value=cost_floor - Decimal("10.00"),
        )
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == cost_floor  # cost floor wins, higher than MAP

        PriceBoundsConfig.objects.filter(product=ns.chair, channel=ns.channel).update(
            map_value=cost_floor + Decimal("20.00")
        )
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == cost_floor + Decimal("20.00")  # MAP wins, higher than cost floor

    def test_no_purchase_cost_means_min_margin_has_no_effect(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, min_margin_percent=Decimal("0.10"))
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] is None

    @pytest.mark.parametrize(
        "level,expected_floor",
        [
            ("global", Decimal("10.00")),
            ("channel", Decimal("20.00")),
            ("sku", Decimal("30.00")),
            ("sku_channel", Decimal("40.00")),
        ],
    )
    def test_most_specific_wins(self, prices_populated, level, expected_floor):
        """Only the row for `level` exists — it must be the one that wins, in isolation."""
        ns = prices_populated
        kwargs_by_level = {
            "global": {"product": None, "channel": None},
            "channel": {"product": None, "channel": ns.channel},
            "sku": {"product": ns.chair, "channel": None},
            "sku_channel": {"product": ns.chair, "channel": ns.channel},
        }
        PriceBoundsConfig.objects.create(**kwargs_by_level[level], map_value=expected_floor)

        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == expected_floor

    def test_channel_level_wins_over_global_when_no_sku_row(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=None, channel=None, map_value=Decimal("10.00"))
        PriceBoundsConfig.objects.create(product=None, channel=ns.channel, map_value=Decimal("20.00"))
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == Decimal("20.00")

    def test_sku_level_wins_over_channel_when_both_present_but_not_combined(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=None, channel=ns.channel, map_value=Decimal("20.00"))
        PriceBoundsConfig.objects.create(product=ns.chair, channel=None, map_value=Decimal("30.00"))
        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        assert result["floor"] == Decimal("30.00")


@pytest.mark.django_db
class TestGetPriceBoundsBaselineField:
    def test_baseline_reported_even_when_channel_not_opted_in(self, prices_populated):
        """The baseline reference value is available regardless of Channel.baseline_enabled."""
        ns = prices_populated
        assert ns.channel.baseline_enabled is False
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"), rounding=PriceRounding.NONE)
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        result = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        rate = ns.rates[("standard", "PL")]
        assert result["baseline"] == rate.gross_price(Decimal("100.00") * Decimal("1.20"))

    def test_baseline_none_without_config_or_cost(self, prices_populated):
        result = price_bounds_service.get_price_bounds("CHAIR-001", prices_populated.channel, prices_populated.pl)
        assert result["baseline"] is None

    def test_bulk_matches_single_item_baseline(self, prices_populated):
        ns = prices_populated
        BaselineConfig.objects.create(channel=ns.channel, markup_percent=Decimal("0.20"))
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("100.00")
        )

        single = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        bulk = price_bounds_service.get_price_bounds_bulk([("CHAIR-001", ns.channel, ns.pl)])
        assert bulk[("CHAIR-001", ns.channel.idx, ns.pl.iso2)]["baseline"] == single["baseline"]


@pytest.mark.django_db
class TestGetPriceBoundsBulk:
    def test_matches_single_item_result(self, prices_populated):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("50.00"))
        pairs = [("CHAIR-001", ns.channel, ns.pl), ("FOOD-001", ns.channel, ns.pl)]
        bulk = price_bounds_service.get_price_bounds_bulk(pairs)
        single_chair = price_bounds_service.get_price_bounds("CHAIR-001", ns.channel, ns.pl)
        single_food = price_bounds_service.get_price_bounds("FOOD-001", ns.channel, ns.pl)
        assert bulk[("CHAIR-001", ns.channel.idx, ns.pl.iso2)] == single_chair
        assert bulk[("FOOD-001", ns.channel.idx, ns.pl.iso2)] == single_food

    def test_constant_query_count_regardless_of_item_count(self, prices_populated, django_assert_max_num_queries):
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("50.00"))
        small = [("CHAIR-001", ns.channel, ns.pl)]
        large = [("CHAIR-001", ns.channel, c) for c in (ns.pl, ns.de, ns.fr)] * 10

        with django_assert_max_num_queries(5):
            price_bounds_service.get_price_bounds_bulk(small)
        with django_assert_max_num_queries(5):
            price_bounds_service.get_price_bounds_bulk(large)

    def test_unknown_sku_returns_none_floor(self, prices_populated):
        ns = prices_populated
        result = price_bounds_service.get_price_bounds_bulk([("GHOST", ns.channel, ns.pl)])
        assert result[("GHOST", ns.channel.idx, ns.pl.iso2)] == {"floor": None, "ceiling": None, "baseline": None}

    def test_differently_cased_sku_still_resolves_bounds(self, prices_populated):
        """A caller-supplied SKU casing that doesn't match the DB's stored casing must still
        resolve to the product — a plain `sku__in` (unlike single-item `sku__iexact`) would
        silently drop it and floor=None would let a write bypass MAP/min_margin enforcement."""
        ns = prices_populated
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("50.00"))
        result = price_bounds_service.get_price_bounds_bulk([("chair-001", ns.channel, ns.pl)])
        assert result[("chair-001", ns.channel.idx, ns.pl.iso2)]["floor"] == Decimal("50.00")


@pytest.mark.django_db
class TestGetMarkets:
    def test_returns_distinct_triples(self, prices_populated):
        markets = price_bounds_service.get_markets()
        triples = {(m["channel_idx"], m["country"], m["currency"]) for m in markets}
        assert (prices_populated.channel.idx, "PL", "PLN") in triples
        assert (prices_populated.channel.idx, "DE", "PLN") in triples
        assert (prices_populated.channel.idx, "FR", "PLN") in triples

    def test_no_duplicates(self, prices_populated):
        markets = price_bounds_service.get_markets()
        keys = [(m["channel_idx"], m["country"], m["currency"]) for m in markets]
        assert len(keys) == len(set(keys))

    def test_market_without_price_row_does_not_appear(self, products):
        """A channel/country/currency combo with zero CurrentPrice rows is not a market."""
        markets = price_bounds_service.get_markets()
        assert not any(m["channel_idx"] == products.channel.idx for m in markets)

    def test_b2b_tier_only_market_is_excluded(self, prices_populated):
        """A market with only a customer_representation-scoped (B2B tier) row must not be
        enumerated — get_current_prices_bulk already filters these out, so surfacing it here
        would hand the pricefighter engine a market with no matching general-price row."""
        from django_pricemanager.models import CustomerRepresentation

        ns = prices_populated
        tier = CustomerRepresentation.objects.create(uid="tier-1", user_email="b2b@example.com")
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.eur,
            tax_rate=ns.rates[("standard", "PL")],
            net_value=Decimal("50.00"),
            gross_value=Decimal("61.50"),
            customer_representation=tier,
            source="csv_import",
        )

        markets = price_bounds_service.get_markets()
        triples = {(m["channel_idx"], m["country"], m["currency"]) for m in markets}
        assert (ns.channel.idx, "PL", "EUR") not in triples

    def test_bundle_component_only_market_is_excluded(self, prices_populated):
        """A market with only a product_parent-scoped (bundle component) row must not be
        enumerated — same rationale as the B2B-tier case above."""
        ns = prices_populated
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.eur,
            tax_rate=ns.rates[("standard", "PL")],
            net_value=Decimal("50.00"),
            gross_value=Decimal("61.50"),
            product_parent=ns.bundle,
            source="csv_import",
        )

        markets = price_bounds_service.get_markets()
        triples = {(m["channel_idx"], m["country"], m["currency"]) for m in markets}
        assert (ns.channel.idx, "PL", "EUR") not in triples


@pytest.mark.django_db
class TestGetCurrentPricesBulk:
    def test_returns_matching_rows(self, prices_populated):
        ns = prices_populated
        pairs = [("CHAIR-001", ns.channel, ns.pl, ns.pln), ("FOOD-001", ns.channel, ns.de, ns.pln)]
        result = price_bounds_service.get_current_prices_bulk(pairs)
        chair_cp = result[("CHAIR-001", ns.channel.idx, ns.pl.iso2, ns.pln.iso3)]
        assert isinstance(chair_cp, CurrentPrice)
        assert chair_cp.product.sku == "CHAIR-001"

    def test_missing_pair_maps_to_none(self, prices_populated):
        ns = prices_populated
        result = price_bounds_service.get_current_prices_bulk([("GHOST", ns.channel, ns.pl, ns.pln)])
        assert result[("GHOST", ns.channel.idx, ns.pl.iso2, ns.pln.iso3)] is None

    def test_differently_cased_sku_still_resolves(self, prices_populated):
        ns = prices_populated
        result = price_bounds_service.get_current_prices_bulk([("chair-001", ns.channel, ns.pl, ns.pln)])
        cp = result[("chair-001", ns.channel.idx, ns.pl.iso2, ns.pln.iso3)]
        assert cp is not None
        assert cp.product.sku == "CHAIR-001"

    def test_constant_query_count(self, prices_populated, django_assert_max_num_queries):
        ns = prices_populated
        pairs = [("CHAIR-001", ns.channel, c, ns.pln) for c in (ns.pl, ns.de, ns.fr)] * 5
        with django_assert_max_num_queries(1):
            price_bounds_service.get_current_prices_bulk(pairs)


@pytest.mark.django_db
class TestGetPurchaseCostsBulk:
    def test_returns_cost_per_sku(self, prices_populated):
        ns = prices_populated
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("42.00")
        )
        result = price_bounds_service.get_purchase_costs_bulk(["CHAIR-001", "FOOD-001"], ns.channel)
        assert result["CHAIR-001"].net_cost == Decimal("42.00")
        assert result["FOOD-001"] is None

    def test_differently_cased_sku_still_resolves(self, prices_populated):
        ns = prices_populated
        PurchaseCost.objects.create(
            product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln, net_cost=Decimal("42.00")
        )
        result = price_bounds_service.get_purchase_costs_bulk(["chair-001"], ns.channel)
        assert result["chair-001"].net_cost == Decimal("42.00")

    def test_constant_query_count(self, prices_populated, django_assert_max_num_queries):
        ns = prices_populated
        with django_assert_max_num_queries(1):
            price_bounds_service.get_purchase_costs_bulk(["CHAIR-001", "FOOD-001", "BUNDLE-001"], ns.channel)
