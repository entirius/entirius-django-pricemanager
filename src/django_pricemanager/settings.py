# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.conf import settings

# ilosc pricelists o statusie success ktore nie zostana usuniete przy procesie garbage collector
SUCCES_PRICELIST_TO_SAVE = getattr(settings, "SUCCES_PRICELIST_TO_SAVE", 3)
# ilosc pricelists o statusie error ktore nie zostana usuniete przy procesie garbage collector
ERROR_PRICELIST_TO_SAVE = getattr(settings, "ERROR_PRICELIST_TO_SAVE", 2)
# ilosc pricelists o statusie in_progress ktore nie zostana usuniete przy procesie garbage collector
INPROGRESS_PRICELIST_TO_SAVE = getattr(settings, "ERROR_PRICELIST_TO_SAVE", 1)
# czy po usunieciu pricelists w procesie garbage collector wykonac vacuum na tabelach price i pricelist
VACUUM = getattr(settings, "PRICEMANAGER_VACUUM", False)
APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES = getattr(
    settings, "APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES", True
)
ATTR_PRICE_CSV_SEPARATOR = getattr(settings, "ATTR_PRICE_CSV_SEPARATOR", ";")
CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING = getattr(settings, "CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING", 10)

BULK_CREATE_BATCH_SIZE = getattr(settings, "PRICEMANAGER_BULK_CREATE_BATCH_SIZE", 5000)

# CurrentPrice + PriceHistory settings
PRICE_HISTORY_RETENTION_DAYS = getattr(settings, "PRICE_HISTORY_RETENTION_DAYS", 365)
PRICEMANAGER_DUAL_WRITE = getattr(settings, "PRICEMANAGER_DUAL_WRITE", False)
# Deprecated — use PriceManagerSettings.read_from_current (DB toggle) instead
PRICEMANAGER_READ_FROM_CURRENT = getattr(settings, "PRICEMANAGER_READ_FROM_CURRENT", False)

# Matrix signal-driven sync (DB toggle: PriceManagerSettings.matrix_signals_enabled)
PRICEMANAGER_MATRIX_SIGNALS_DEBOUNCE_SECONDS = getattr(settings, "PRICEMANAGER_MATRIX_SIGNALS_DEBOUNCE_SECONDS", 5)
PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST = tuple(
    getattr(settings, "PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST", ())
)

# Cache key constants — used in killswitch.py, admin.py, output.py
CACHE_KEY_MATRIX_SIGNALS_ENABLED = "pricemanager:matrix_signals_enabled"
CACHE_KEY_READ_FROM_CURRENT = "pricemanager:read_from_current"
