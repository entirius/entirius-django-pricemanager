# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from bievents import bi_django_command_decorator
from django.core.management.base import BaseCommand

from ... import settings
from ...services import GarbageCollector


class Command(BaseCommand):
    help = (
        f"Delete pricelists except for "
        f"the last {settings.SUCCES_PRICELIST_TO_SAVE} with succes "
        f"and {settings.ERROR_PRICELIST_TO_SAVE} errors "
        f"and {settings.INPROGRESS_PRICELIST_TO_SAVE} in progress"
    )

    @bi_django_command_decorator
    def handle(self, *args, **options):
        worker = GarbageCollector()
        rv = worker.start()
        if rv:
            self.stdout.write(self.style.SUCCESS("done"))
        else:
            self.stdout.write(self.style.ERROR("error"))
