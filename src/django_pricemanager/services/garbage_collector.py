# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging
import sys

from django.db import connection
from django.utils import timezone
from lockfile import LockFile

from django_pricemanager.models.pricelist import PriceListStatusEnum
from django_pricemanager.models.sale_channel import SaleChannel

from .. import settings
from ..models import PriceList

logger = logging.getLogger(__name__)


class GarbageCollector:
    CHUNK_SIZE = 2000
    LOCK_FILE = "/tmp/_pricemanager_garbage_collector.lock"
    lock = None

    def __init__(self):
        self.lock = LockFile(self.LOCK_FILE, wait_for_acquire=False)
        try:
            self.lock.acquire()
        except OSError:
            # another instance is running
            now = timezone.now()
            m = f"[{now}] Exiting, another instance is running ..."
            print(m)
            logger.info(m)
            sys.exit(0)

    def vacuum(self):
        print("Executing Vacuum on tables: django_pricemanager_pricelist, django_pricemanager_price")
        logger.info("Executing Vacuum")
        cursor = connection.cursor()
        cursor.execute('VACUUM FULL "public"."django_pricemanager_pricelist";')
        cursor.execute('VACUUM FULL "public"."django_pricemanager_price";')

    def start(self):
        sale_channels = SaleChannel.objects.all()
        total_channel = len(sale_channels)
        cnt_channel = 0
        for sale_channel in sale_channels:
            cnt_channel += 1

            #
            # Pricelists with success
            #
            ids_to_stay = list(
                PriceList.objects.filter(status=PriceListStatusEnum.READY, sale_channel=sale_channel)
                .order_by("-created_on")[0 : settings.SUCCES_PRICELIST_TO_SAVE]
                .values_list("id", flat=True)
            )
            msg = (
                "Removing all pricelists with status=success, "
                f"except {settings.SUCCES_PRICELIST_TO_SAVE} latest for sale channel={sale_channel}, progress: {cnt_channel} / {total_channel}"
            )
            logger.info(msg)
            print(msg)
            pricelists = PriceList.objects.filter(status=PriceListStatusEnum.READY, sale_channel=sale_channel).exclude(
                id__in=ids_to_stay
            )
            _, cnt = pricelists.delete()
            if cnt:
                msg = f"Removed objects: {cnt}"
            else:
                msg = "Nothing was removed"
            logger.info(msg)
            print(msg)

            #
            # Pricelists with errors
            #
            ids_to_stay = list(
                PriceList.objects.filter(status=PriceListStatusEnum.ERROR, sale_channel=sale_channel)
                .order_by("-created_on")[0 : settings.ERROR_PRICELIST_TO_SAVE]
                .values_list("id", flat=True)
            )
            msg = f"Removing all pricelists with status=error, except {settings.ERROR_PRICELIST_TO_SAVE} latest for sale channel={sale_channel}, progress: {cnt_channel} / {total_channel}"
            logger.info(msg)
            print(msg)
            pricelists = PriceList.objects.filter(status=PriceListStatusEnum.ERROR, sale_channel=sale_channel).exclude(
                id__in=ids_to_stay
            )
            _, cnt = pricelists.delete()
            if cnt:
                msg = f"Removed objects: {cnt}"
            else:
                msg = "Nothing was removed"
            logger.info(msg)
            print(msg)

            #
            # Pricelists dangling in_progress
            #
            ids_to_stay = list(
                PriceList.objects.filter(status=PriceListStatusEnum.IN_PROGRESS, sale_channel=sale_channel)
                .order_by("-created_on")[0 : settings.INPROGRESS_PRICELIST_TO_SAVE]
                .values_list("id", flat=True)
            )
            msg = (
                "Removing all pricelists with status=in_progress, "
                f"except {settings.INPROGRESS_PRICELIST_TO_SAVE} latest for sale channel={sale_channel}, progress: {cnt_channel} / {total_channel}"
            )
            logger.info(msg)
            print(msg)
            pricelists = PriceList.objects.filter(
                status=PriceListStatusEnum.IN_PROGRESS, sale_channel=sale_channel
            ).exclude(id__in=ids_to_stay)
            _, cnt = pricelists.delete()
            if cnt:
                msg = f"Removed objects: {cnt}"
            else:
                msg = "Nothing was removed"
            logger.info(msg)
            print(msg)

        #
        # Vacuum
        #
        if settings.VACUUM:
            self.vacuum()

        return True
