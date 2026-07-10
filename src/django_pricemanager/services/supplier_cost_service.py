# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply a supplier cost update to PurchaseCost (buy-side cost store).

Pure service — caller (signal handler in ``signals/supplier_cost.py``) resolves the
supplier-side context (link / preferred flag / supplier idx) by talking to
``django_suppliers`` and passes it in. This module has zero hard dependency on
django_suppliers, so the test suite can exercise the full DB write path without
having the suppliers app installed.

The supplier cost lands in ``PurchaseCost`` — NOT ``CurrentPrice``. A supplier cost
is what we PAY, not what we SELL for, so it never creates a sellable price. The
product stays unpriced until an operator sets a CurrentPrice; margin is then
CurrentPrice.net_value vs PurchaseCost.net_cost.

Decision rules:

* No active ProductSupplierLink → skip, audit ``cost_ignored_no_link``
* Link.is_preferred is False → skip, audit ``cost_ignored_non_preferred``
* Channel / Currency / Product lookup misses → skip, audit ``cost_skipped_resolution_failed``
* Existing PurchaseCost.net_cost == new cost → idempotency skip (no audit)
* Otherwise → update_or_create PurchaseCost, audit ``cost_signal_received``
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django_regional.models import Currency

from django_pricemanager.models import Channel, PurchaseCost
from django_pricemanager.models.product_representation import ProductRepresentation

SkipReason = str  # narrow type alias for the discriminated values below


@dataclass(frozen=True)
class SupplierCostOutcome:
    """What happened when the receiver processed a single (sp, channel) signal."""

    written: bool
    audit_source: str | None
    field_path: str
    before: Decimal | None = None
    after: Decimal | None = None
    skip_reason: SkipReason | None = None


# Audit source constants — mirrored in django_suppliers.enums.ChangeLogSource
# whitelist. Kept here as plain strings so this module has no hard dep on the
# suppliers package (consistent with the rest of pricemanager's "soft coupling"
# rule for the cost subscriber).
AUDIT_COST_RECEIVED = "cost_signal_received"
AUDIT_IGNORED_NON_PREFERRED = "cost_ignored_non_preferred"
AUDIT_IGNORED_NO_LINK = "cost_ignored_no_link"
AUDIT_SKIPPED_RESOLUTION = "cost_skipped_resolution_failed"


def _resolve_resources(
    *, real_product_sku: str, channel_idx: str, currency_code: str
) -> tuple[ProductRepresentation, Channel, Currency] | None:
    # Buy-side cost needs no TaxRate — we only store the net cost, no gross derivation.
    product = ProductRepresentation.objects.filter(sku=real_product_sku).first()
    if product is None:
        return None
    channel = Channel.objects.filter(idx=channel_idx).first()
    if channel is None or channel.default_country_id is None:
        return None
    currency = Currency.objects.filter(iso3=currency_code).first()
    if currency is None:
        return None
    return product, channel, currency


def apply_supplier_cost(
    *,
    real_product_sku: str,
    supplier_idx: str,
    channel_idx: str,
    cost: Decimal,
    currency: str,
    is_preferred: bool,
    has_link: bool,
) -> SupplierCostOutcome:
    """Apply preferred-supplier cost to PurchaseCost. Idempotent, audited. Never touches the sell price."""
    field_path = f"purchase_cost.net_cost[channel={channel_idx}]"

    if not has_link:
        return SupplierCostOutcome(
            written=False,
            audit_source=AUDIT_IGNORED_NO_LINK,
            field_path=field_path,
            after=cost,
            skip_reason="no_link",
        )
    if not is_preferred:
        return SupplierCostOutcome(
            written=False,
            audit_source=AUDIT_IGNORED_NON_PREFERRED,
            field_path=field_path,
            after=cost,
            skip_reason="non_preferred",
        )

    resolved = _resolve_resources(real_product_sku=real_product_sku, channel_idx=channel_idx, currency_code=currency)
    if resolved is None:
        return SupplierCostOutcome(
            written=False,
            audit_source=AUDIT_SKIPPED_RESOLUTION,
            field_path=field_path,
            after=cost,
            skip_reason="resolution_failed",
        )
    product, channel, currency_obj = resolved

    existing = PurchaseCost.objects.filter(
        product=product,
        channel=channel,
        country=channel.default_country,
        currency=currency_obj,
    ).first()

    if existing is not None and existing.net_cost == cost:
        return SupplierCostOutcome(
            written=False,
            audit_source=None,  # idempotency: no audit spam
            field_path=field_path,
            before=existing.net_cost,
            after=cost,
            skip_reason="idempotent",
        )

    before_cost = existing.net_cost if existing is not None else None

    with transaction.atomic():
        PurchaseCost.objects.update_or_create(
            product=product,
            channel=channel,
            country=channel.default_country,
            currency=currency_obj,
            defaults={"net_cost": cost, "supplier_idx": supplier_idx},
        )

    return SupplierCostOutcome(
        written=True,
        audit_source=AUDIT_COST_RECEIVED,
        field_path=field_path,
        before=before_cost,
        after=cost,
    )
