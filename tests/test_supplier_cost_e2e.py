# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Integration tests for the cost subscriber path.

Covers the full DB write (PurchaseCost only — never CurrentPrice/PriceHistory),
the resolution failure branch, and the receiver module's contract on import when
django_suppliers is not installed (pricemanager test settings deliberately omit
suppliers from INSTALLED_APPS).
"""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PriceHistory, PurchaseCost
from django_pricemanager.services import supplier_cost_service

pytestmark = pytest.mark.django_db


def test_preferred_write_persists_purchasecost_only(products):
    """One signal application → one PurchaseCost row; no CurrentPrice, no PriceHistory."""
    outcome = supplier_cost_service.apply_supplier_cost(
        real_product_sku=products.chair.sku,
        supplier_idx="fortrade",
        channel_idx=products.channel.idx,
        cost=Decimal("0.13"),
        currency=products.pln.iso3,
        is_preferred=True,
        has_link=True,
    )

    assert outcome.written is True
    pc = PurchaseCost.objects.get(product=products.chair, channel=products.channel, country=products.pl)
    assert pc.net_cost == Decimal("0.13")
    assert pc.supplier_idx == "fortrade"

    # Buy-side cost must NOT leak into the sell price or its history.
    assert not CurrentPrice.objects.filter(product=products.chair, channel=products.channel).exists()
    assert not PriceHistory.objects.filter(product=products.chair, channel=products.channel).exists()


def test_resolution_failure_when_product_unknown(products):
    """Unknown SKU → product resolution fails, service skips with resolution_failed, no write."""
    outcome = supplier_cost_service.apply_supplier_cost(
        real_product_sku="DOES-NOT-EXIST",
        supplier_idx="fortrade",
        channel_idx=products.channel.idx,
        cost=Decimal("0.13"),
        currency=products.pln.iso3,
        is_preferred=True,
        has_link=True,
    )

    assert outcome.written is False
    assert outcome.audit_source == supplier_cost_service.AUDIT_SKIPPED_RESOLUTION
    assert not PurchaseCost.objects.filter(channel=products.channel).exists()


def test_signal_handler_module_imports_without_suppliers_installed():
    """Pricemanager test settings deliberately omit django_suppliers — module must import cleanly."""
    from django_pricemanager.signals import supplier_cost as handler_module

    assert handler_module._SUPPLIERS_AVAILABLE is False
    # The receiver function exists and is safely callable as a no-op.
    handler_module.on_supplier_cost_updated(
        sender=None, supplier_product=None, channel_idx="x", cost=Decimal("0"), currency="PLN"
    )
