# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import time

from bievents import bi_django_command_decorator
from celery_once.tasks import AlreadyQueued
from django.core.management.base import BaseCommand

from ...tasks import import_pricelist_from_csv


class Command(BaseCommand):
    help = "Import pricelist from CSV"

    def add_arguments(self, parser):
        parser.add_argument("sale_channel_idx", type=str)
        parser.add_argument("file_path", type=str, help="example: pricelists/pricelist.csv")
        parser.add_argument("--currency_code", type=str)
        parser.add_argument("-t", "--celery-task", action="store_true", help="Create Celery task")

    @bi_django_command_decorator
    def handle(self, *args, **options):
        sale_channel_idx = options["sale_channel_idx"]
        file_path = options["file_path"]
        currency_code = options["currency_code"]
        celery_task = options["celery_task"]
        time_start = time.time()
        if currency_code is None:
            currency_code = "PLN"
        if celery_task:
            try:
                import_pricelist_from_csv.delay(
                    sale_channel_idx=sale_channel_idx, currency_code=currency_code, file_path=file_path
                )
                self.stdout.write(f"Job for SaleChannel: `{sale_channel_idx}` added to queue for import pricelist")
            except AlreadyQueued:
                print(f"Task for {sale_channel_idx} was already queued")
        else:
            import_pricelist_from_csv(
                sale_channel_idx=sale_channel_idx, currency_code=currency_code, file_path=file_path
            )
        time_end = time.time()
        self.stdout.write(self.style.SUCCESS(f"done. Took {(time_end - time_start)} seconds"))
