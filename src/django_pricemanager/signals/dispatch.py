# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Enqueue price changes for matrix read model sync via shared Redis sorted set."""

import logging
import time

from celery import current_app
from django.core.cache import caches

from django_pricemanager.settings import PRICEMANAGER_MATRIX_SIGNALS_DEBOUNCE_SECONDS

logger = logging.getLogger(__name__)

# Shared with PIM — matrix's flush_pending_matrix_sync reads from this key
PENDING_KEY = "pim:matrix:pending"
LOCK_KEY = "pim:matrix:flush_scheduled"


def enqueue_price_sync(sku: str, channel_idx: str) -> None:
    """Add SKU+channel to the shared Redis sorted set for matrix sync."""
    try:
        redis = caches["default"].client.get_client()
        member = f"{sku}:{channel_idx}"
        debounce = PRICEMANAGER_MATRIX_SIGNALS_DEBOUNCE_SECONDS

        redis.zadd(PENDING_KEY, {member: time.time()})
        redis.expire(PENDING_KEY, 300)

        if redis.set(LOCK_KEY, "1", nx=True, ex=debounce + 1):
            current_app.send_task(
                "django_matrix.tasks.flush_pending_matrix_sync",
                countdown=debounce,
                queue="matrix_pull",
            )
            logger.info("Price sync flush scheduled in %ds, enqueued %s", debounce, member)
        else:
            logger.debug("Flush already scheduled, enqueued %s", member)
    except Exception:
        logger.warning("Failed to enqueue price sync for %s:%s", sku, channel_idx, exc_info=True)
