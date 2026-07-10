# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os

from bievents import bi_django_command_decorator
from celery_once.tasks import AlreadyQueued
from django.conf import settings
from django.core.management.base import BaseCommand

from ...tasks import import_tax_class_from_csv


class Command(BaseCommand):
    help = "Import taxclass from CSV"

    def add_arguments(self, parser):
        parser.add_argument("tax_class_name", type=str)
        parser.add_argument("--file_path", type=str)

    @bi_django_command_decorator
    def handle(self, *args, **options):
        tax_class_name = options["tax_class_name"]
        file_path = options["file_path"]

        if file_path is None:
            file_path = os.path.join(settings.MEDIA_ROOT, "pricelists/tax_class.csv")

        try:
            import_tax_class_from_csv.delay(tax_class_name=tax_class_name, file_path=file_path)
        except AlreadyQueued:
            print(f"Task for {tax_class_name} was already queued")
        self.stdout.write(f"Job for for: `{tax_class_name}` added to queue for import tax class")
        self.stdout.write(self.style.SUCCESS("DONE"))
