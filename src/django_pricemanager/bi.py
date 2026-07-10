# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from bievents import BiEventAbstract
from django.conf import settings

BI_SOURCE = "django-pricemanager"
BI_ENVIRONMENT = settings.BI_ENVIRONMENT
BI_BUSINESS_UNIT = settings.BI_BUSINESS_UNIT


class EventAbstract(BiEventAbstract):
    details_type = "Event Abstract"
    version = 1

    def __init__(self, **kwargs):
        kwargs["source"] = BI_SOURCE
        kwargs["environment"] = BI_ENVIRONMENT
        kwargs["business_unit"] = BI_BUSINESS_UNIT
        super().__init__(**kwargs)


class PM_CreatePricelistsEvent(EventAbstract):
    details_type = "PriceManager Create Pricelists"
    version = 1

    def __init__(self, channel_idx, **kwargs):
        self.details = {"channel_idx": channel_idx}
        super().__init__(**kwargs)


class PM_CreatePricelistFromCsvEvent(EventAbstract):
    details_type = "PriceManager Create Pricelist From CSV"
    version = 1

    def __init__(self, file_path, channel_idx, currency_code, **kwargs):
        self.details = {"file_path": file_path, "channel_idx": channel_idx, "currency_code": currency_code}
        super().__init__(**kwargs)
