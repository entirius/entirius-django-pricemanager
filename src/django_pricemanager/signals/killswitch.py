# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Three-layer kill-switch for price→matrix signal-driven sync.

1. DB toggle: PriceManagerSettings.matrix_signals_enabled (cached 60s)
2. Thread-local: suppress_price_matrix_signals() context manager
3. Channel denylist: PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST setting
"""

import logging
import threading
from collections.abc import Generator
from contextlib import contextmanager

from django_pricemanager.settings import (
    CACHE_KEY_MATRIX_SIGNALS_ENABLED,
    PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST,
)

logger = logging.getLogger(__name__)
_local = threading.local()


@contextmanager
def suppress_price_matrix_signals() -> Generator[None, None, None]:
    """Suppress signal-driven Matrix sync. Use during bulk imports and recalc tasks."""
    _local.suppress_matrix_sync_depth = getattr(_local, "suppress_matrix_sync_depth", 0) + 1
    try:
        yield
    finally:
        _local.suppress_matrix_sync_depth = max(0, _local.suppress_matrix_sync_depth - 1)


def is_matrix_sync_suppressed() -> bool:
    """Check if suppressed via context manager (thread-local, no I/O)."""
    return getattr(_local, "suppress_matrix_sync_depth", 0) > 0


def is_matrix_signals_enabled() -> bool:
    """Check PriceManagerSettings DB toggle (cached 60s)."""
    from django.core.cache import cache

    cached = cache.get(CACHE_KEY_MATRIX_SIGNALS_ENABLED)
    if cached is not None:
        return cached
    try:
        from django_pricemanager.models.pm_settings import PriceManagerSettings

        enabled = PriceManagerSettings.load().matrix_signals_enabled
    except Exception:
        logger.warning("Failed to load PriceManagerSettings — signals disabled", exc_info=True)
        enabled = False
    cache.set(CACHE_KEY_MATRIX_SIGNALS_ENABLED, enabled, 60)
    return enabled


def should_skip(channel_idx: str | None = None) -> bool:
    """Return True if matrix sync should be skipped for this event."""
    if is_matrix_sync_suppressed():
        return True
    if not is_matrix_signals_enabled():
        return True
    if channel_idx and channel_idx in PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST:
        return True
    return False
