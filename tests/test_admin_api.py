# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Integration tests for the v2 admin API endpoints."""

from decimal import Decimal

import pytest

from django_pricemanager.models import Channel, CurrentPrice, PriceHistory, ProductRepresentation, TaxClass

# ---------------------------------------------------------------------------
# Authentication / authorisation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthRequirements:
    def test_401_no_token(self, api_client):
        """Unauthenticated request to channels list returns 401."""
        response = api_client.get("/api/pricemanager/v2/admin/channels/")
        assert response.status_code == 401

    def test_403_regular_user(self, api_client, regular_user):
        """Non-staff user receives 403."""
        api_client.force_authenticate(user=regular_user)
        response = api_client.get("/api/pricemanager/v2/admin/channels/")
        assert response.status_code == 403

    def test_200_admin_channels(self, admin_client):
        """Admin user gets 200 on channels list."""
        response = admin_client.get("/api/pricemanager/v2/admin/channels/")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChannelEndpoints:
    def test_list_channels(self, admin_client, channel_setup):
        """GET /channels/ returns at least the seeded channel."""
        response = admin_client.get("/api/pricemanager/v2/admin/channels/")
        assert response.status_code == 200
        idxs = [ch["idx"] for ch in response.data]
        assert "b2c-europe" in idxs

    def test_channel_detail(self, admin_client, channel_setup):
        """GET /channels/{idx}/ includes calculate_direction field."""
        response = admin_client.get("/api/pricemanager/v2/admin/channels/b2c-europe/")
        assert response.status_code == 200
        assert "calculate_direction" in response.data
        assert response.data["calculate_direction"] in ("from_net_to_gross", "from_gross_to_net")

    def test_sync_channels(self, admin_client):
        """POST /channels/sync/ returns 200 with a structured response (even if no PIM)."""
        response = admin_client.post("/api/pricemanager/v2/admin/channels/sync/")
        assert response.status_code == 200
        # The response schema has synced/created/updated — all are integers
        for key in ("synced", "created", "updated"):
            assert key in response.data
            assert isinstance(response.data[key], int)


# ---------------------------------------------------------------------------
# Tax Classes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTaxClassEndpoints:
    def test_list_tax_classes(self, admin_client, tax_setup):
        """GET /tax-classes/ returns both seeded tax classes."""
        response = admin_client.get("/api/pricemanager/v2/admin/tax-classes/")
        assert response.status_code == 200
        idxs = [tc["idx"] for tc in response.data]
        assert "standard" in idxs
        assert "reduced" in idxs

    def test_tax_class_detail_with_rates(self, admin_client, tax_setup):
        """GET /tax-classes/{idx}/ returns inline rates array."""
        response = admin_client.get("/api/pricemanager/v2/admin/tax-classes/standard/")
        assert response.status_code == 200
        assert "rates" in response.data
        assert len(response.data["rates"]) >= 1
        first_rate = response.data["rates"][0]
        assert "country" in first_rate
        assert "rate" in first_rate


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPriceEndpoints:
    def test_patch_price_by_sku(self, admin_client, prices_populated):
        """PATCH /{ch}/prices/{sku}/ with a value returns 200 and updated price data."""
        response = admin_client.patch(
            "/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/",
            {"value": "95.00"},
            format="json",
        )
        assert response.status_code == 200
        assert "sku" in response.data
        assert response.data["sku"] == "CHAIR-001"
        assert "prices" in response.data
        assert len(response.data["prices"]) >= 1

    def test_price_history_after_edit(self, admin_client, prices_populated):
        """After a PATCH, GET /{ch}/prices/{sku}/history/ returns at least one entry."""
        admin_client.patch(
            "/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/",
            {"value": "95.00"},
            format="json",
        )
        response = admin_client.get("/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/history/")
        assert response.status_code == 200
        assert response.data["count"] >= 1
        first = response.data["results"][0]
        assert "gross_value" in first
        assert "net_value" in first
        assert "source" in first

    def test_patch_price_400_invalid_payload(self, admin_client, prices_populated):
        """PATCH with missing value field returns 400."""
        resp = admin_client.patch(
            "/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/",
            data={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_patch_price_404_unknown_channel(self, admin_client, prices_populated):
        """PATCH to nonexistent channel returns 404."""
        resp = admin_client.patch(
            "/api/pricemanager/v2/admin/nonexistent/prices/CHAIR-001/",
            data={"value": "100.00", "currency_code": "PLN"},
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_get_price_detail(self, admin_client, prices_populated):
        """GET detail returns sku, calculate_direction, prices array."""
        resp = admin_client.get("/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sku"] == "CHAIR-001"
        assert "calculate_direction" in data
        assert isinstance(data["prices"], list)

    def test_price_detail_purchase_costs_empty_when_none(self, admin_client, prices_populated):
        """No PurchaseCost for the SKU → purchase_costs is an empty list."""
        resp = admin_client.get("/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/")
        assert resp.json()["purchase_costs"] == []

    def test_price_detail_includes_purchase_costs(self, admin_client, prices_populated):
        """A PurchaseCost for the SKU/channel surfaces in the detail response."""
        from django_regional.models import Country, Currency

        from django_pricemanager.models import Channel, ProductRepresentation, PurchaseCost

        ch = Channel.objects.get(idx="b2c-europe")
        PurchaseCost.objects.create(
            product=ProductRepresentation.objects.get(sku="CHAIR-001"),
            channel=ch,
            country=ch.default_country or Country.objects.first(),
            currency=Currency.objects.first(),
            net_cost="12.3400",
            supplier_idx="fortrade",
        )
        resp = admin_client.get("/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/")
        assert resp.status_code == 200
        pcs = resp.json()["purchase_costs"]
        assert len(pcs) == 1
        assert pcs[0]["net_cost"] == "12.3400"
        assert pcs[0]["supplier_idx"] == "fortrade"
        assert "modified_at" in pcs[0]

    def test_post_preview(self, admin_client, prices_populated):
        """POST preview returns breakdown without saving."""
        resp = admin_client.post(
            "/api/pricemanager/v2/admin/b2c-europe/prices/CHAIR-001/preview/",
            data={"value": "999.00"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "preview" in data

    def test_pagination_contract(self, admin_client, prices_populated):
        """Price list returns paginated envelope with count/next/previous/results."""
        resp = admin_client.get("/api/pricemanager/v2/admin/b2c-europe/prices/")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "results" in data
        assert isinstance(data["results"], list)


# ---------------------------------------------------------------------------
# Channel mutations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChannelMutations:
    def test_create_channel(self, admin_client, tax_setup):
        """POST /channels/ creates a new channel and returns 201 with name."""
        resp = admin_client.post(
            "/api/pricemanager/v2/admin/channels/",
            data={"name": "Test Channel", "calculate_direction": "from_net_to_gross"},
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Channel"

    def test_patch_channel(self, admin_client, channel_setup):
        """PATCH /channels/{idx}/ updates name and returns 200."""
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/channels/{channel_setup.channel.idx}/",
            data={"name": "Updated Name"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_delete_channel_no_prices(self, admin_client, tax_setup):
        """DELETE a channel that has no CurrentPrices returns 204."""
        ch = Channel.objects.create(idx="deletable", name="Deletable", calculate_direction=0)
        resp = admin_client.delete(f"/api/pricemanager/v2/admin/channels/{ch.idx}/")
        assert resp.status_code == 204

    def test_delete_channel_with_prices_400(self, admin_client, prices_populated):
        """DELETE a channel that has CurrentPrices returns 400."""
        ns = prices_populated
        resp = admin_client.delete(f"/api/pricemanager/v2/admin/channels/{ns.channel.idx}/")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tax class mutations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTaxClassMutations:
    def test_create_tax_class(self, admin_client):
        """POST /tax-classes/ creates a new tax class and returns 201 with name."""
        resp = admin_client.post(
            "/api/pricemanager/v2/admin/tax-classes/",
            data={"name": "Luxury"},
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Luxury"

    def test_patch_tax_class(self, admin_client, tax_setup):
        """PATCH /tax-classes/{idx}/ updates the name and returns 200."""
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/tax-classes/{tax_setup.standard.idx}/",
            data={"name": "Standard Updated"},
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_delete_tax_class(self, admin_client):
        """DELETE a tax class with no associated products returns 204."""
        from django_pricemanager.models import TaxClass as TC

        tc = TC.objects.create(name="Temp", idx="temp")
        resp = admin_client.delete("/api/pricemanager/v2/admin/tax-classes/temp/")
        assert resp.status_code == 204

    def test_create_tax_rate_duplicate_returns_400(self, admin_client, tax_setup):
        """POST a rate for a country that already has a rate on this class returns 400."""
        resp = admin_client.post(
            f"/api/pricemanager/v2/admin/tax-classes/{tax_setup.reduced.idx}/rates/",
            data={"country_code": tax_setup.pl.iso2, "rate": "0.0500"},
            content_type="application/json",
        )
        # PL already has a rate on the reduced tax class — duplicate must be rejected.
        assert resp.status_code == 400

    def test_patch_tax_rate(self, admin_client, tax_setup, mocker):
        """PATCH /tax-classes/{idx}/rates/{iso2}/ updates the rate and returns 200."""
        mocker.patch("django_pricemanager.api.admin.views.tax_class_views.recalculate_prices_for_tax_change")
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/tax-classes/{tax_setup.standard.idx}/rates/{tax_setup.pl.iso2}/",
            data={"rate": "0.2500"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["rate"] == "0.2500"

    def test_delete_tax_rate(self, admin_client, tax_setup):
        """DELETE /tax-classes/{idx}/rates/{iso2}/ removes the rate and returns 204."""
        resp = admin_client.delete(
            f"/api/pricemanager/v2/admin/tax-classes/{tax_setup.standard.idx}/rates/{tax_setup.pl.iso2}/"
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Bulk price endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPriceEndpoint:
    def test_bulk_happy_path(self, admin_client, prices_populated):
        """PATCH bulk/ with two valid SKUs returns updated=2 and no errors."""
        ns = prices_populated
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/bulk/",
            data={
                "items": [
                    {"sku": "CHAIR-001", "value": "150.00"},
                    {"sku": "FOOD-001", "value": "75.00"},
                ],
                "currency_code": ns.pln.iso3,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 2
        assert data["changes_logged"] > 0
        assert data["errors"] == []

    def test_bulk_partial_errors(self, admin_client, prices_populated):
        """PATCH bulk/ with one valid and one invalid SKU returns updated=1 and one error."""
        ns = prices_populated
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/bulk/",
            data={
                "items": [
                    {"sku": "CHAIR-001", "value": "150.00"},
                    {"sku": "BAD-SKU", "value": "50.00", "tax_class_idx": "nonexistent-class"},
                ],
                "currency_code": ns.pln.iso3,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["sku"] == "BAD-SKU"

    def test_bulk_empty_items(self, admin_client, prices_populated):
        """PATCH bulk/ with an empty items list returns updated=0 and no errors."""
        ns = prices_populated
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/bulk/",
            data={"items": [], "currency_code": ns.pln.iso3},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 0
        assert data["errors"] == []

    def test_bulk_new_product_with_tax_class(self, admin_client, prices_populated):
        """PATCH bulk/ with a new SKU creates a ProductRepresentation and returns updated=1."""
        ns = prices_populated
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/bulk/",
            data={
                "items": [
                    {"sku": "BULK-NEW-001", "value": "99.99", "tax_class_idx": ns.standard.idx},
                ],
                "currency_code": ns.pln.iso3,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 1
        assert data["errors"] == []
        assert ProductRepresentation.objects.filter(sku__iexact="BULK-NEW-001").exists()


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNewEndpoints:
    def test_channel_default_country(self, admin_client, channel_setup):
        """Channel detail returns default_country."""
        ns = channel_setup
        ns.channel.default_country = ns.pl
        ns.channel.save()
        resp = admin_client.get(f"/api/pricemanager/v2/admin/channels/{ns.channel.idx}/")
        assert resp.status_code == 200
        assert resp.json()["default_country"] == "PL"

    def test_channel_set_default_country(self, admin_client, channel_setup):
        """PATCH channel with default_country_code sets it."""
        ns = channel_setup
        resp = admin_client.patch(
            f"/api/pricemanager/v2/admin/channels/{ns.channel.idx}/",
            data={"default_country_code": "DE"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["default_country"] == "DE"

    def test_products_with_price_status(self, admin_client, prices_populated):
        """GET /prices/products/ returns SKUs with has_price flag."""
        ns = prices_populated
        resp = admin_client.get(f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/products/?currency={ns.pln.iso3}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        # Check structure
        first = data["results"][0]
        assert "sku" in first
        assert "tax_class" in first
        assert "has_price" in first

    def test_products_filter_without_price(self, admin_client, prices_populated):
        """GET /prices/products/?has_price=false returns unpriced SKUs."""
        ns = prices_populated
        # Create a product with no price
        from django_pricemanager.models import ProductRepresentation

        tc = TaxClass.objects.first()
        ProductRepresentation.objects.create(sku="NO-PRICE-SKU", tax_class=tc)

        resp = admin_client.get(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/products/?currency={ns.pln.iso3}&has_price=false"
        )
        assert resp.status_code == 200
        skus = [r["sku"] for r in resp.json()["results"]]
        assert "NO-PRICE-SKU" in skus

    def test_prices_flat_with_currency(self, admin_client, prices_populated):
        """GET /prices/?currency=PLN returns flat per-SKU with default country."""
        ns = prices_populated
        ns.channel.default_country = ns.pl
        ns.channel.save()
        resp = admin_client.get(f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/?currency={ns.pln.iso3}")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "results" in data
        if data["results"]:
            first = data["results"][0]
            assert "sku" in first
            assert first.get("country") == "PL"
            assert "net" in first
            assert "gross" in first

    def test_prices_flat_with_explicit_country(self, admin_client, prices_populated):
        """GET /prices/?currency=PLN&country=DE uses explicit country."""
        ns = prices_populated
        resp = admin_client.get(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/?currency={ns.pln.iso3}&country=DE"
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["results"]:
            assert data["results"][0].get("country") == "DE"

    def test_products_search(self, admin_client, prices_populated):
        """GET /prices/products/?search=CHAIR returns matching SKUs."""
        ns = prices_populated
        resp = admin_client.get(
            f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/products/?currency={ns.pln.iso3}&search=CHAIR"
        )
        assert resp.status_code == 200
        skus = [r["sku"] for r in resp.json()["results"]]
        assert all("CHAIR" in s for s in skus)

    def test_prices_flat_requires_currency(self, admin_client, prices_populated):
        """GET /prices/ without currency param falls back to grouped (backward compat)."""
        ns = prices_populated
        resp = admin_client.get(f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/")
        assert resp.status_code == 200
        # Should still work (grouped mode fallback)


# ---------------------------------------------------------------------------
# Auth coverage across all ViewSets (#4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthAllViewSets:
    """Verify 401/403 on representative endpoints from each ViewSet."""

    @pytest.mark.parametrize(
        "url",
        [
            "/api/pricemanager/v2/admin/channels/",
            "/api/pricemanager/v2/admin/tax-classes/",
        ],
    )
    def test_401_no_token(self, api_client, url):
        resp = api_client.get(url)
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "url",
        [
            "/api/pricemanager/v2/admin/channels/",
            "/api/pricemanager/v2/admin/tax-classes/",
        ],
    )
    def test_403_regular_user(self, api_client, regular_user, url):
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get(url)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Channel PATCH 404 (#7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChannelEdgeCases:
    def test_patch_channel_404_unknown_idx(self, admin_client):
        resp = admin_client.patch(
            "/api/pricemanager/v2/admin/channels/nonexistent/",
            data={"name": "Test"},
            content_type="application/json",
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tax Class DELETE guard (#6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTaxClassEdgeCases:
    def test_delete_tax_class_with_products_returns_400(self, admin_client, tax_setup):
        """DELETE /tax-classes/{idx}/ with associated products returns 400."""
        from django_pricemanager.models import ProductRepresentation

        # Precondition: at least one product linked to the tax class
        ProductRepresentation.objects.create(sku="TAX-GUARD-TEST-SKU", tax_class=tax_setup.standard)

        resp = admin_client.delete(f"/api/pricemanager/v2/admin/tax-classes/{tax_setup.standard.idx}/")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Flush Special + Delete Prices (C3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFlushSpecialEndpoint:
    def test_flush_special_clears_fields(self, admin_client, prices_populated):
        """POST /prices/{sku}/flush-special/ clears special values and logs history."""
        ns = prices_populated
        # Set a special price first
        cp = CurrentPrice.objects.filter(channel=ns.channel, product=ns.chair).first()
        cp.special_net_value = Decimal("10.00")
        cp.special_gross_value = Decimal("12.30")
        cp.save()
        history_before = PriceHistory.objects.count()

        resp = admin_client.post(f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/{ns.chair.sku}/flush-special/")
        assert resp.status_code == 200
        assert resp.json()["flushed"] > 0

        # Verify special fields are cleared
        cp.refresh_from_db()
        assert cp.special_net_value is None
        assert cp.special_gross_value is None

        # Verify history was logged
        assert PriceHistory.objects.count() > history_before

    def test_flush_special_404_unknown_sku(self, admin_client, channel_setup):
        """POST /prices/{sku}/flush-special/ with no prices returns 404."""
        resp = admin_client.post(
            f"/api/pricemanager/v2/admin/{channel_setup.channel.idx}/prices/NONEXISTENT/flush-special/"
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestDestroyPriceEndpoint:
    def test_delete_prices_removes_all(self, admin_client, prices_populated):
        """DELETE /prices/{sku}/ removes CurrentPrice rows and logs history."""
        ns = prices_populated
        sku = ns.chair.sku
        assert CurrentPrice.objects.filter(channel=ns.channel, product=ns.chair).exists()
        history_before = PriceHistory.objects.count()

        resp = admin_client.delete(f"/api/pricemanager/v2/admin/{ns.channel.idx}/prices/{sku}/")
        assert resp.status_code == 204

        # Prices gone
        assert not CurrentPrice.objects.filter(channel=ns.channel, product=ns.chair).exists()

        # History preserved
        assert PriceHistory.objects.count() > history_before

    def test_delete_prices_empty_sku_returns_204(self, admin_client, channel_setup):
        """DELETE /prices/{sku}/ with no existing prices returns 204 (idempotent)."""
        resp = admin_client.delete(f"/api/pricemanager/v2/admin/{channel_setup.channel.idx}/prices/NONEXISTENT/")
        assert resp.status_code == 204
