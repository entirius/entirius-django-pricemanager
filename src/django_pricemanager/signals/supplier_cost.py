# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Subscribe to ``django_atlas.signals.cost_updated_signal`` and project the
primary-source cost into ``PurchaseCost``.

Decoupling: django_atlas is optional from pricemanager's standpoint. The
signal definition lives there, the receiver lives here. If ``django_atlas``
is not installed (e.g. standalone test runs of pricemanager) the module
imports cleanly and the receiver registration is a no-op — there is simply no
signal to dispatch on.

The business rules live in ``services.supplier_cost_service.apply_supplier_cost``
so the DB path can be unit-tested without registering the atlas app.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.dispatch import receiver

from django_pricemanager.services import supplier_cost_service

logger = logging.getLogger(__name__)


try:  # pragma: no cover — import-time wiring, exercised by all integration runs
    from django_atlas.models import SourceProductLink
    from django_atlas.services import audit_service
    from django_atlas.signals import cost_updated_signal

    _ATLAS_AVAILABLE = True
except (ImportError, RuntimeError):
    # ImportError → package not installed at all (clean isolation).
    # RuntimeError → package is on PYTHONPATH but not in INSTALLED_APPS, so Django
    #                refuses to materialise its model classes. Same outcome for us:
    #                we cannot bind to the signal, treat as "atlas absent".
    cost_updated_signal = None
    SourceProductLink = None
    audit_service = None
    _ATLAS_AVAILABLE = False


def _resolve_link(real_product_sku: str, source):
    """Return (has_link, is_primary). ``source`` is the django_atlas Source instance."""
    if SourceProductLink is None:
        return False, False
    link = SourceProductLink.objects.filter(real_product_sku=real_product_sku, source=source, is_active=True).first()
    if link is None:
        return False, False
    return True, bool(link.is_primary)


def _emit_audit(*, source_product, outcome) -> None:
    if outcome.audit_source is None or audit_service is None:
        return
    try:
        audit_service.log_change(
            source_product=source_product,
            source=outcome.audit_source,
            field_path=outcome.field_path,
            before=outcome.before,
            after=outcome.after,
            applied_to_pim=outcome.written,
        )
    except Exception:  # noqa: BLE001 — audit is best-effort, never block the signal path
        logger.exception("Failed to write supplier-cost audit row (signal continues).")


def _handle(sender, source_product, channel_idx, cost, currency, **kwargs) -> None:
    """Resolve atlas context, delegate to the service, fire the audit row."""
    if not _ATLAS_AVAILABLE:
        return
    if source_product is None or source_product.real_product_id is None:
        return
    real_sku = source_product.real_product.sku
    if not real_sku:
        return
    has_link, is_primary = _resolve_link(real_sku, source_product.source)
    outcome = supplier_cost_service.apply_supplier_cost(
        real_product_sku=real_sku,
        supplier_idx=source_product.source.idx,
        channel_idx=channel_idx,
        cost=cost,
        currency=currency,
        is_preferred=is_primary,
        has_link=has_link,
    )
    _emit_audit(source_product=source_product, outcome=outcome)


def on_supplier_cost_updated(sender, source_product, channel_idx, cost, currency, **kwargs) -> None:
    """Receiver entry — wraps the work in ``transaction.on_commit`` so it runs only after the batch commits."""
    transaction.on_commit(lambda: _handle(sender, source_product, channel_idx, cost, currency, **kwargs))


if _ATLAS_AVAILABLE:  # pragma: no branch
    on_supplier_cost_updated = receiver(  # type: ignore[assignment]
        cost_updated_signal, dispatch_uid="pricemanager_supplier_cost_handler"
    )(on_supplier_cost_updated)
