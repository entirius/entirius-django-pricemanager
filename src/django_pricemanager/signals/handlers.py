# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Django signal handlers for CurrentPrice → Matrix read model sync."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from django_pricemanager.models import CurrentPrice
from django_pricemanager.signals.dispatch import enqueue_price_sync
from django_pricemanager.signals.killswitch import should_skip


@receiver(post_save, sender=CurrentPrice, dispatch_uid="pm_currentprice_post_save_matrix")
def on_current_price_save(sender: type, instance: CurrentPrice, raw: bool = False, **kwargs) -> None:
    if raw or should_skip(instance.channel.idx if instance.channel_id else None):
        return
    enqueue_price_sync(instance.product.sku, instance.channel.idx)


@receiver(post_delete, sender=CurrentPrice, dispatch_uid="pm_currentprice_post_delete_matrix")
def on_current_price_delete(sender: type, instance: CurrentPrice, **kwargs) -> None:
    if should_skip(instance.channel.idx if instance.channel_id else None):
        return
    enqueue_price_sync(instance.product.sku, instance.channel.idx)
