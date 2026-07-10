# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit tests for the supplier_cost service.

Exercises the decision logic of ``apply_supplier_cost`` directly. The supplier cost
lands in ``PurchaseCost`` (buy-side) and must NEVER create a sellable ``CurrentPrice``.
"""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PurchaseCost
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.services import supplier_cost_service

pytestmark = pytest.mark.django_db


def _apply(products, *, is_preferred=True, has_link=True, cost="0.13", currency=None):
    return supplier_cost_service.apply_supplier_cost(
        real_product_sku=products.chair.sku,
        supplier_idx="fortrade",
        channel_idx=products.channel.idx,
        cost=Decimal(cost),
        currency=(currency or products.pln.iso3),
        is_preferred=is_preferred,
        has_link=has_link,
    )


def test_preferred_cost_creates_purchasecost_not_currentprice(products):
    """No existing cost → service creates a PurchaseCost row and NO sellable price."""
    outcome = _apply(products, cost="0.13")

    assert outcome.written is True
    assert outcome.audit_source == supplier_cost_service.AUDIT_COST_RECEIVED
    pc = PurchaseCost.objects.get(product=products.chair, channel=products.channel, country=products.pl)
    assert pc.net_cost == Decimal("0.13")
    assert pc.supplier_idx == "fortrade"
    # Product stays unpriced — cost must not create a CurrentPrice.
    assert not CurrentPrice.objects.filter(product=products.chair, channel=products.channel).exists()


def test_preferred_existing_cost_is_updated_then_idempotent(products):
    """Update path: existing PurchaseCost gets new net_cost; same value second time = no-op."""
    _apply(products, cost="0.13")

    outcome2 = _apply(products, cost="0.10")
    assert outcome2.written is True
    pc = PurchaseCost.objects.get(product=products.chair, channel=products.channel, country=products.pl)
    assert pc.net_cost == Decimal("0.10")

    outcome3 = _apply(products, cost="0.10")
    assert outcome3.written is False
    assert outcome3.audit_source is None
    assert outcome3.skip_reason == "idempotent"
    assert PurchaseCost.objects.filter(product=products.chair, channel=products.channel).count() == 1


def test_non_preferred_supplier_is_ignored(products):
    """Non-preferred link: no DB write, audit reason = ignored_non_preferred."""
    outcome = _apply(products, is_preferred=False, has_link=True, cost="0.13")

    assert outcome.written is False
    assert outcome.audit_source == supplier_cost_service.AUDIT_IGNORED_NON_PREFERRED
    assert outcome.skip_reason == "non_preferred"
    assert not PurchaseCost.objects.filter(product=products.chair, channel=products.channel).exists()


def test_no_link_is_skipped_with_no_link_audit(products):
    """Supplier has no active link to this SKU: no DB write, audit reason = no_link."""
    outcome = _apply(products, has_link=False, is_preferred=False, cost="0.13")

    assert outcome.written is False
    assert outcome.audit_source == supplier_cost_service.AUDIT_IGNORED_NO_LINK
    assert outcome.skip_reason == "no_link"
    assert not PurchaseCost.objects.filter(product=products.chair, channel=products.channel).exists()


def test_existing_sell_price_is_untouched_by_cost(products):
    """A manually-set CurrentPrice (sell price) must stay intact — cost only writes PurchaseCost."""
    pl_tax_rate = products.rates[("standard", "PL")]
    CurrentPrice.objects.create(
        product=products.chair,
        channel=products.channel,
        country=products.pl,
        currency=products.pln,
        tax_rate=pl_tax_rate,
        net_value=Decimal("99.99"),
        gross_value=Decimal("122.99"),
        source=PriceSource.ADMIN_EDIT,
    )

    outcome = _apply(products, cost="0.13")

    assert outcome.written is True
    # Sell price unchanged…
    cp = CurrentPrice.objects.get(product=products.chair, channel=products.channel, country=products.pl)
    assert cp.net_value == Decimal("99.99")
    assert cp.source == PriceSource.ADMIN_EDIT
    # …and cost landed separately.
    pc = PurchaseCost.objects.get(product=products.chair, channel=products.channel, country=products.pl)
    assert pc.net_cost == Decimal("0.13")
