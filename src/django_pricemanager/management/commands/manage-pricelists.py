# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from bievents import bi_django_command_decorator
from celery_once.tasks import AlreadyQueued
from django.core.management.base import BaseCommand

from django_pricemanager.models import Channel, PriceList, SaleChannel
from django_pricemanager.services.sale_channel_service import get_latest_pricelist_by_source
from django_pricemanager.workers import check_pricelist_soruce

from ...tasks import create_channel_pricelist


class Command(BaseCommand):
    help = "Create new pricelists for every Channel"

    def add_arguments(self, parser):
        parser.add_argument("-t", "--celery-task", action="store_true", help="Create Celery task")
        parser.add_argument("--channel_idx", type=str, help="Volkanos Channel/Shop IDX")
        parser.add_argument("--price_source", help="Starting PriceList source type: api/csv, default=csv")

    @bi_django_command_decorator
    def handle(self, *args, **options):
        celery_task = options["celery_task"]
        channel_idx = options["channel_idx"]
        price_source = options["price_source"]

        if channel_idx:
            channels: list[Channel] = Channel.objects.filter(idx=channel_idx)
        else:
            channels: list[Channel] = Channel.objects.all()

        if len(channels) == 0:
            self.stdout.write("No Channels for calculate. Exiting")
            return

        source = check_pricelist_soruce(price_source)
        ready = [c for c in channels if self._has_source_pricelist(c, source)]
        if not ready:
            self.stdout.write("No price lists to manage. Exiting")
            return

        for channel in ready:
            if celery_task:
                try:
                    create_channel_pricelist.delay(channel_idx=channel.idx, price_source=price_source)
                    self.stdout.write(f"Job for Channel: `{channel.idx}` added to queue for calculating pricelist")
                except AlreadyQueued:
                    print(f"Task for {channel.idx} was already queued")
            else:
                self.stdout.write(f"Calculating pricelist for Channel: `{channel.idx}`")
                create_channel_pricelist(channel_idx=channel.idx, price_source=price_source)
        self.stdout.write(self.style.SUCCESS("DONE"))

    def _has_source_pricelist(self, channel: Channel, price_source: str) -> bool:
        try:
            get_latest_pricelist_by_source(channel, price_source)
        except (SaleChannel.DoesNotExist, PriceList.DoesNotExist):
            self.stdout.write(f"No price list for Channel: `{channel.idx}`, skipping")
            return False
        return True
