# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Subscribe to ``django_suppliers.signals.cost_updated_signal`` and project the
preferred-supplier cost into ``CurrentPrice``.

Decoupling: django_suppliers is optional from pricemanager's standpoint. The
signal definition lives there, the receiver lives here. If ``django_suppliers``
is not installed (e.g. standalone test runs of pricemanager) the module
imports cleanly and the receiver registration is a no-op — there is simply no
signal to dispatch on.

The business rules live in ``services.supplier_cost_service.apply_supplier_cost``
so the DB path can be unit-tested without registering the suppliers app.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.dispatch import receiver

from django_pricemanager.services import supplier_cost_service

logger = logging.getLogger(__name__)


try:  # pragma: no cover — import-time wiring, exercised by all integration runs
    from django_suppliers.models import ProductSupplierLink
    from django_suppliers.services import audit_service
    from django_suppliers.signals import cost_updated_signal

    _SUPPLIERS_AVAILABLE = True
except (ImportError, RuntimeError):
    # ImportError → package not installed at all (clean isolation).
    # RuntimeError → package is on PYTHONPATH but not in INSTALLED_APPS, so Django
    #                refuses to materialise its model classes. Same outcome for us:
    #                we cannot bind to the signal, treat as "suppliers absent".
    cost_updated_signal = None
    ProductSupplierLink = None
    audit_service = None
    _SUPPLIERS_AVAILABLE = False


def _resolve_link(real_product_sku: str, supplier):
    """Return (has_link, is_preferred). ``supplier`` is the django_suppliers Supplier instance."""
    if ProductSupplierLink is None:
        return False, False
    link = ProductSupplierLink.objects.filter(
        real_product_sku=real_product_sku, supplier=supplier, is_active=True
    ).first()
    if link is None:
        return False, False
    return True, bool(link.is_preferred)


def _emit_audit(*, supplier_product, outcome) -> None:
    if outcome.audit_source is None or audit_service is None:
        return
    try:
        audit_service.log_change(
            supplier_product=supplier_product,
            source=outcome.audit_source,
            field_path=outcome.field_path,
            before=outcome.before,
            after=outcome.after,
            applied_to_pim=outcome.written,
        )
    except Exception:  # noqa: BLE001 — audit is best-effort, never block the signal path
        logger.exception("Failed to write supplier-cost audit row (signal continues).")


def _handle(sender, supplier_product, channel_idx, cost, currency, **kwargs) -> None:
    """Resolve suppliers context, delegate to the service, fire the audit row."""
    if not _SUPPLIERS_AVAILABLE:
        return
    if supplier_product is None or supplier_product.real_product_id is None:
        return
    real_sku = supplier_product.real_product.sku
    if not real_sku:
        return
    has_link, is_preferred = _resolve_link(real_sku, supplier_product.supplier)
    outcome = supplier_cost_service.apply_supplier_cost(
        real_product_sku=real_sku,
        supplier_idx=supplier_product.supplier.idx,
        channel_idx=channel_idx,
        cost=cost,
        currency=currency,
        is_preferred=is_preferred,
        has_link=has_link,
    )
    _emit_audit(supplier_product=supplier_product, outcome=outcome)


def on_supplier_cost_updated(sender, supplier_product, channel_idx, cost, currency, **kwargs) -> None:
    """Receiver entry — wraps the work in ``transaction.on_commit`` per D32."""
    transaction.on_commit(lambda: _handle(sender, supplier_product, channel_idx, cost, currency, **kwargs))


if _SUPPLIERS_AVAILABLE:  # pragma: no branch
    on_supplier_cost_updated = receiver(  # type: ignore[assignment]
        cost_updated_signal, dispatch_uid="pricemanager_supplier_cost_handler"
    )(on_supplier_cost_updated)
