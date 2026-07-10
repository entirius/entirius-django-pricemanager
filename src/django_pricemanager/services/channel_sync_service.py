# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Channel sync from PIM — idx + name only. Domain fields stay manual."""

import logging

from django_pricemanager.models import Channel

logger = logging.getLogger(__name__)


def sync_channels_from_pim() -> dict:
    """Sync channels from PIM (soft dependency). Returns counts."""
    try:
        from django_pim.models import Channel as PimChannel
    except (ImportError, RuntimeError):
        logger.info("django_pim not available — skipping channel sync")
        return {"synced": 0, "created": 0, "updated": 0}

    created = 0
    updated = 0
    for pim_ch in PimChannel.objects.all():
        _, was_created = Channel.objects.update_or_create(
            idx=pim_ch.idx,
            defaults={"name": pim_ch.name},
        )
        if was_created:
            created += 1
        else:
            updated += 1

    total = created + updated
    logger.info("Synced %d channels from PIM (created=%d, updated=%d)", total, created, updated)
    return {"synced": total, "created": created, "updated": updated}
