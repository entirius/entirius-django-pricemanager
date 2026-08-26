# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Trigger baseline recalc whenever PurchaseCost changes.

Listens on the module's own PurchaseCost post_save rather than django_atlas's
cost_updated_signal directly — the atlas receiver (signals.supplier_cost) already funnels
into PurchaseCost.update_or_create(), so this catches both the atlas-driven stream and any
manual PurchaseCost edit (Django admin, management command) without an atlas dependency.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from django_pricemanager.models import PurchaseCost

# Batch of (product, channel) pairs touched by PurchaseCost saves within the current
# transaction, stashed on the connection — the atlas cost stream saves one PurchaseCost per
# product, often many inside a single sync transaction, and recalculate_baseline_for_product
# alone is ~15-20 queries per pair. Collecting pairs here and flushing once via
# recalculate_baseline_bulk turns "N saves in one transaction" into one batched recalc.
_PENDING_ATTR = "_pricemanager_baseline_pending"


def _flush_pending() -> None:
    connection = transaction.get_connection()
    pending = getattr(connection, _PENDING_ATTR, None)
    setattr(connection, _PENDING_ATTR, None)
    if not pending:
        return
    from django_pricemanager.services.baseline_service import recalculate_baseline_bulk

    recalculate_baseline_bulk(list(pending.values()))


@receiver(post_save, sender=PurchaseCost, dispatch_uid="pricemanager_baseline_on_cost_change")
def on_purchase_cost_saved(sender: type, instance: PurchaseCost, raw: bool = False, **kwargs) -> None:
    """Receiver entry — collects the (product, channel) pair on the connection and registers a
    single flush callback (per transaction.on_commit) per transaction, so the whole
    batch resolves in one recalculate_baseline_bulk call at commit time instead of one call per
    PurchaseCost save.

    The "is a flush already registered" check reads ``connection.run_on_commit`` directly
    rather than trusting a bare not-None check on the pending dict: Django discards on_commit
    callbacks registered under a rolled-back savepoint (``connection.savepoint_rollback``), but
    a plain flag/dict wouldn't know that happened and would wrongly skip re-registering for the
    next, unrelated transaction on the same connection — starving it of any flush at all. When
    no flush is currently registered, any pre-existing pending dict is necessarily orphaned
    from an already-discarded batch, so it's reset before adding the current pair.

    Note: ``PurchaseCost.objects.bulk_create()`` never fires post_save — a bulk cost import
    must call ``baseline_service.recalculate_baseline_bulk`` explicitly instead of relying
    on this signal.
    """
    if raw:
        return
    connection = transaction.get_connection()
    already_scheduled = any(func is _flush_pending for _, func, _ in connection.run_on_commit)
    pending = getattr(connection, _PENDING_ATTR, None)
    if pending is None or not already_scheduled:
        pending = {}
        setattr(connection, _PENDING_ATTR, pending)
    # Add the pair BEFORE registering on_commit: in plain autocommit (no surrounding atomic
    # block — bare shell/management-command/task saves), on_commit() runs its callback
    # synchronously and immediately. Registering first left _flush_pending reading an empty
    # dict and the pair got added to an already-orphaned one afterward, silently dropping the
    # recalc.
    pending[(instance.product_id, instance.channel_id)] = (instance.product, instance.channel)
    if not already_scheduled:
        transaction.on_commit(_flush_pending)
