# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging
from datetime import timedelta

from celery import shared_task
from celery_once import QueueOnce
from django.utils import timezone

from .models import Channel, SaleChannel
from .models.choices import PriceSource
from .workers import create_pricelist_from_csv, create_pricelists, create_tax_class_from_csv

logger = logging.getLogger(__name__)


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def create_channel_pricelist(channel_idx: str, price_source: str = SaleChannel.PRICE_SOURCE_CSV):
    channel = Channel.objects.get(idx=channel_idx)
    create_pricelists(channel, price_source)


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def import_pricelist_from_csv(sale_channel_idx: str, currency_code: str, file_path: str):
    sale_channel: SaleChannel = SaleChannel.objects.get(idx=sale_channel_idx, price_source=SaleChannel.PRICE_SOURCE_CSV)
    create_pricelist_from_csv(sale_channel, currency_code, file_path)


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def import_tax_class_from_csv(tax_class_name: str, file_path: str):
    create_tax_class_from_csv(tax_class_name, file_path)


@shared_task
def cleanup_price_history():
    """Daily beat: delete PriceHistory older than retention period."""
    from django_pricemanager.models import PriceHistory
    from django_pricemanager.settings import PRICE_HISTORY_RETENTION_DAYS

    if PRICE_HISTORY_RETENTION_DAYS <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=PRICE_HISTORY_RETENTION_DAYS)
    deleted, _ = PriceHistory.objects.filter(created_at__lt=cutoff).delete()
    logger.info("Cleaned up %d PriceHistory entries older than %s", deleted, cutoff)
    return deleted


def _recalculate_and_log(prices, source: str, new_rate=None) -> int:
    """Shared recalculation logic for tax change and channel change tasks."""
    from django_pricemanager.models import CurrentPrice, PriceHistory
    from django_pricemanager.models.channel import CalculateDirectionEnum

    updated = []
    for cp in prices:
        rate = new_rate or cp.tax_rate
        if not rate:
            continue
        direction = cp.channel.calculate_direction
        if direction == CalculateDirectionEnum.FROM_NET_TO_GROSS:
            cp.gross_value = rate.gross_price(cp.net_value)
            if cp.special_net_value:
                cp.special_gross_value = rate.gross_price(cp.special_net_value)
        else:
            cp.net_value = rate.net_price(cp.gross_value)
            if cp.special_gross_value:
                cp.special_net_value = rate.net_price(cp.special_gross_value)
        if new_rate:
            cp.tax_rate = new_rate
        cp.source = source
        updated.append(cp)

    if not updated:
        return 0

    update_fields = ["net_value", "gross_value", "special_net_value", "special_gross_value", "source"]
    if new_rate:
        update_fields.append("tax_rate")
    CurrentPrice.objects.bulk_update(updated, fields=update_fields, batch_size=500)

    PriceHistory.objects.bulk_create(
        [
            PriceHistory(
                product=cp.product,
                channel=cp.channel,
                country=cp.country,
                currency=cp.currency,
                customer_representation=cp.customer_representation,
                gross_value=cp.gross_value,
                net_value=cp.net_value,
                special_gross_value=cp.special_gross_value,
                special_net_value=cp.special_net_value,
                tax_rate=cp.tax_rate,
                source=source,
            )
            for cp in updated
        ],
        batch_size=500,
    )
    return len(updated)


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def recalculate_prices_for_tax_change(tax_class_idx: str, country_iso2: str):
    """Recalculate all CurrentPrices for a (tax_class, country) after TaxRate update."""
    from django_regional.models import Country

    from django_pricemanager.models import CurrentPrice, TaxClass, TaxRate

    try:
        country = Country.objects.get(iso2=country_iso2)
        tax_class = TaxClass.objects.get(idx=tax_class_idx)
        new_rate = TaxRate.objects.get(tax_class=tax_class, country=country)
    except (Country.DoesNotExist, TaxClass.DoesNotExist, TaxRate.DoesNotExist):
        logger.warning("Cannot recalculate: tax_class=%s, country=%s not found", tax_class_idx, country_iso2)
        return 0

    prices = CurrentPrice.objects.filter(product__tax_class=tax_class, country=country).select_related(
        "channel", "product"
    )
    count = _recalculate_and_log(prices, source=PriceSource.TAX_RATE_CHANGE, new_rate=new_rate)
    logger.info("Recalculated %d prices for tax_class=%s, country=%s", count, tax_class_idx, country_iso2)
    return count


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def recalculate_prices_for_channel_change(channel_idx: str):
    """Recalculate all CurrentPrices after Channel direction or countries change."""
    from django_pricemanager.models import CurrentPrice

    channel = Channel.objects.get(idx=channel_idx)
    prices = CurrentPrice.objects.filter(channel=channel).select_related("channel", "product", "tax_rate")
    count = _recalculate_and_log(prices, source=PriceSource.TAX_RATE_CHANGE)
    logger.info("Recalculated %d prices for channel=%s", count, channel_idx)
    return count
