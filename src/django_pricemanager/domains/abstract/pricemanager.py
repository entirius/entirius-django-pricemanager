# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime

from django_utils.domains.domain import Domain
from process_logger import ProcessLogger

from django_pricemanager.models import Channel
from django_pricemanager.repository import DjangoPricemanagerRepository


class DomainPricemanager(Domain):
    channel: Channel
    pricemanager_repository: DjangoPricemanagerRepository
    updated_at: datetime | None = None

    def __init__(self):
        self.pricemanager_repository = DjangoPricemanagerRepository()

    def set_logger(self, logger: ProcessLogger) -> None:
        super().set_logger(logger)
        self.pricemanager_repository.set_logger(logger)

    def set_channel(self, channel: Channel) -> None:
        self.channel = channel
        self.pricemanager_repository.channel = channel

    def set_updated_at(self, updated_at: datetime) -> None:
        self.updated_at = updated_at
