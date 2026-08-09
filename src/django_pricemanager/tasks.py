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
    """Shared recalculation logic for tax change and channel change tasks.

    Neutral recalc: amounts change, CurrentPrice.source does NOT — a lock like
    admin_edit must survive a VAT change. PriceHistory still logs `source` (audit).
    """
    from django_pricemanager.models import CurrentPrice, PriceHistory
    from django_pricemanager.models.channel import CalculateDirectionEnum
    from django_pricemanager.services import price_bounds_service
    from django_pricemanager.services.price_write_guard import guard_price_write, load_policy_map

    policy_map = load_policy_map()
    prices = list(prices)
    bounds_by_row = price_bounds_service.get_price_bounds_bulk(
        [(cp.product.sku, cp.channel, cp.country) for cp in prices]
    )
    updated = []
    for cp in prices:
        rate = new_rate or cp.tax_rate
        if not rate:
            continue
        direction = cp.channel.calculate_direction
        new_values = {
            "net_value": cp.net_value,
            "gross_value": cp.gross_value,
            "special_net_value": cp.special_net_value,
            "special_gross_value": cp.special_gross_value,
            "tax_rate": rate,
        }
        if direction == CalculateDirectionEnum.FROM_NET_TO_GROSS:
            new_values["gross_value"] = rate.gross_price(cp.net_value)
            if cp.special_net_value:
                new_values["special_gross_value"] = rate.gross_price(cp.special_net_value)
        else:
            new_values["net_value"] = rate.net_price(cp.gross_value)
            if cp.special_gross_value:
                new_values["special_net_value"] = rate.net_price(cp.special_gross_value)

        bounds = price_bounds_service.bounds_for(bounds_by_row, cp.product.sku, cp.channel.idx, cp.country.iso2)

        # writer=TAX_RATE_CHANGE is unconditional in precedence and forced to clamp mode
        # (see price_write_guard._enforce_mode) — this call never returns "skipped".
        decision = guard_price_write(
            existing_source=cp.source,
            new_values=new_values,
            writer=PriceSource.TAX_RATE_CHANGE,
            policy_map=policy_map,
            bounds=bounds,
        )
        if decision.status == "skipped":
            continue  # defensive — TAX_RATE_CHANGE is forced to clamp mode, never actually skipped
        cp.net_value = decision.values["net_value"]
        cp.gross_value = decision.values["gross_value"]
        cp.special_net_value = decision.values.get("special_net_value")
        cp.special_gross_value = decision.values.get("special_gross_value")
        if new_rate:
            cp.tax_rate = new_rate
        updated.append(cp)

    if not updated:
        return 0

    update_fields = ["net_value", "gross_value", "special_net_value", "special_gross_value"]
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
    _trigger_baseline_recalc(updated)
    return len(updated)


def _trigger_baseline_recalc(updated: list) -> None:
    """Re-run baseline auto-price for (product, channel) pairs touched by a VAT recalc.

    The generic recalc above already updates amounts on existing BASELINE rows via plain
    tax conversion, which does not reapply BaselineConfig's markup/rounding — so baseline
    rows need a dedicated re-run to stay correct, and channels opted into baseline also
    need any still-missing rows filled for products that gained a TaxRate.

    Narrowed to the countries actually touched by the VAT recalc (not every country of the
    product/channel) and run as a single batch — `recalculate_baseline_bulk` prefetches once
    for all pairs instead of re-querying costs/configs/bounds per pair.
    """
    from django_pricemanager.services.baseline_service import recalculate_baseline_bulk

    pair_objects = {}
    countries_by_pair: dict = {}
    for cp in updated:
        if not cp.channel.baseline_enabled:
            continue
        key = (cp.product_id, cp.channel_id)
        pair_objects.setdefault(key, (cp.product, cp.channel))
        countries_by_pair.setdefault(key, {})[cp.country_id] = cp.country

    if not pair_objects:
        return
    countries_by_pair = {key: list(countries.values()) for key, countries in countries_by_pair.items()}
    recalculate_baseline_bulk(list(pair_objects.values()), countries_by_pair=countries_by_pair)


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
        "channel", "product", "country"
    )
    count = _recalculate_and_log(prices, source=PriceSource.TAX_RATE_CHANGE, new_rate=new_rate)
    logger.info("Recalculated %d prices for tax_class=%s, country=%s", count, tax_class_idx, country_iso2)
    return count


@shared_task(base=QueueOnce, queue="pricemanager_create_pricelist")
def recalculate_prices_for_channel_change(channel_idx: str):
    """Recalculate all CurrentPrices after Channel direction or countries change."""
    from django_pricemanager.models import CurrentPrice

    channel = Channel.objects.get(idx=channel_idx)
    prices = CurrentPrice.objects.filter(channel=channel).select_related("channel", "product", "tax_rate", "country")
    count = _recalculate_and_log(prices, source=PriceSource.TAX_RATE_CHANGE)
    logger.info("Recalculated %d prices for channel=%s", count, channel_idx)
    return count
