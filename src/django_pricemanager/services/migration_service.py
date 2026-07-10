# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Data migration: PriceList snapshots -> CurrentPrice + PriceHistory.

Used by management command migrate_to_current_price.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from django_regional.models import Currency

from django_pricemanager.models import (
    CurrentPrice,
    CurrentPriceAttribute,
    Price,
    PriceAttribute,
    PriceHistory,
    PriceList,
    SaleChannel,
)
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.pricelist import PriceListStatusEnum

logger = logging.getLogger(__name__)


def populate_current_prices(batch_size: int = 5000, dry_run: bool = False) -> int:
    """Create CurrentPrice from latest READY snapshots."""
    combos = (
        PriceList.objects.filter(status=PriceListStatusEnum.READY).values("sale_channel_id", "currency_id").distinct()
    )

    total_created = 0
    for combo in combos:
        sale_channel = SaleChannel.objects.select_related("channel", "customer_representation").get(
            id=combo["sale_channel_id"]
        )
        currency = Currency.objects.get(id=combo["currency_id"])

        try:
            pricelist = PriceList.objects.filter(
                sale_channel=sale_channel,
                currency=currency,
                status=PriceListStatusEnum.READY,
            ).latest("created_on", "pk")
        except PriceList.DoesNotExist:
            continue

        prices = (
            Price.objects.filter(pricelist=pricelist)
            .select_related("product", "tax_rate", "product_parent")
            .iterator(chunk_size=batch_size)
        )

        batch = []
        for price in prices:
            batch.append(
                CurrentPrice(
                    product=price.product,
                    product_parent=price.product_parent,
                    channel=sale_channel.channel,
                    country=pricelist.country,
                    currency=currency,
                    customer_representation=sale_channel.customer_representation,
                    net_value=price.net_value,
                    gross_value=price.gross_value,
                    special_net_value=price.special_net_value,
                    special_gross_value=price.special_gross_value,
                    special_from_date=price.special_from_date,
                    special_to_date=price.special_to_date,
                    tax_rate=price.tax_rate,
                    is_only_for_verified_user=sale_channel.is_only_for_verified_user,
                    source=PriceSource.MIGRATION,
                )
            )
            if len(batch) >= batch_size:
                if not dry_run:
                    _flush_current_prices(batch)
                total_created += len(batch)
                batch.clear()

        if batch:
            if not dry_run:
                _flush_current_prices(batch)
            total_created += len(batch)

    logger.info("Populated %d CurrentPrice rows (dry_run=%s)", total_created, dry_run)
    return total_created


def _flush_current_prices(batch: list[CurrentPrice]) -> None:
    for cp in batch:
        lookup = {
            "product": cp.product,
            "channel": cp.channel,
            "country": cp.country,
            "currency": cp.currency,
            "customer_representation": cp.customer_representation,
            "product_parent": cp.product_parent,
        }
        defaults = {
            "net_value": cp.net_value,
            "gross_value": cp.gross_value,
            "special_net_value": cp.special_net_value,
            "special_gross_value": cp.special_gross_value,
            "special_from_date": cp.special_from_date,
            "special_to_date": cp.special_to_date,
            "tax_rate": cp.tax_rate,
            "is_only_for_verified_user": cp.is_only_for_verified_user,
            "source": cp.source,
        }
        CurrentPrice.objects.update_or_create(**lookup, defaults=defaults)


def backfill_price_history(days: int = 90, batch_size: int = 5000, dry_run: bool = False) -> int:
    """Create PriceHistory from recent PriceList snapshots."""
    cutoff = timezone.now() - timedelta(days=days)

    pricelists = (
        PriceList.objects.filter(status=PriceListStatusEnum.READY, created_on__gte=cutoff)
        .select_related("sale_channel__channel", "currency")
        .order_by("created_on")
    )

    total_created = 0
    for pricelist in pricelists:
        channel = pricelist.sale_channel.channel
        prices = (
            Price.objects.filter(pricelist=pricelist, product_parent__isnull=True)
            .select_related("product", "tax_rate")
            .only("product_id", "net_value", "gross_value", "special_net_value", "special_gross_value", "tax_rate_id")
            .iterator(chunk_size=batch_size)
        )

        batch = []
        for price in prices:
            batch.append(
                PriceHistory(
                    product=price.product,
                    channel=channel,
                    country=pricelist.country,
                    currency=pricelist.currency,
                    net_value=price.net_value,
                    gross_value=price.gross_value,
                    special_net_value=price.special_net_value,
                    special_gross_value=price.special_gross_value,
                    tax_rate=price.tax_rate,
                    source=PriceSource.MIGRATION_BACKFILL,
                    created_at=pricelist.created_on,
                )
            )
            if len(batch) >= batch_size:
                if not dry_run:
                    PriceHistory.objects.bulk_create(batch, batch_size=batch_size)
                total_created += len(batch)
                batch.clear()

        if batch:
            if not dry_run:
                PriceHistory.objects.bulk_create(batch, batch_size=batch_size)
            total_created += len(batch)

    logger.info("Backfilled %d PriceHistory rows (%d days, dry_run=%s)", total_created, days, dry_run)
    return total_created


def migrate_price_attributes(batch_size: int = 5000, dry_run: bool = False) -> int:
    """Migrate PriceAttribute M2M from Price to CurrentPriceAttribute."""
    current_prices = CurrentPrice.objects.filter(product__isnull=False).select_related(
        "product", "channel", "country", "currency"
    )

    total = 0
    for cp in current_prices.iterator(chunk_size=batch_size):
        old_attr_ids = (
            PriceAttribute.objects.filter(
                price__product=cp.product,
                price__pricelist__sale_channel__channel=cp.channel,
                price__pricelist__country=cp.country,
                price__pricelist__currency=cp.currency,
                price__pricelist__status=PriceListStatusEnum.READY,
            )
            .values_list("attr_id", flat=True)
            .distinct()
        )

        if old_attr_ids:
            batch = [CurrentPriceAttribute(current_price=cp, attr_id=attr_id) for attr_id in old_attr_ids]
            if not dry_run:
                CurrentPriceAttribute.objects.bulk_create(batch, ignore_conflicts=True)
            total += len(batch)

    logger.info("Migrated %d CurrentPriceAttribute rows (dry_run=%s)", total, dry_run)
    return total


def verify_migration() -> list[str]:
    """Compare CurrentPrice with old get_latest_pricelist() output."""
    from django_pricemanager.models import Channel
    from django_pricemanager.services.pricelist_service import get_latest_pricelist

    mismatches = []
    for channel in Channel.objects.all():
        for sc in channel.sale_channels.filter(customer_representation__isnull=True):
            for currency in Currency.objects.all():
                old_pl = get_latest_pricelist(channel.idx, currency.iso3, sc.country.iso2)
                if not old_pl:
                    continue

                old_prices = {
                    p.product.sku: p
                    for p in old_pl.prices.filter(product_parent__isnull=True).select_related("product")
                }
                new_prices = {
                    cp.product.sku: cp
                    for cp in CurrentPrice.objects.filter(
                        channel=channel,
                        country=sc.country,
                        currency=currency,
                        customer_representation__isnull=True,
                        product_parent__isnull=True,
                    ).select_related("product")
                }

                for sku, old_p in old_prices.items():
                    new_p = new_prices.get(sku)
                    if not new_p:
                        mismatches.append(f"MISSING: {sku} in {channel.idx}/{sc.country.iso2}")
                        continue
                    for field in ["gross_value", "net_value", "special_gross_value", "special_net_value"]:
                        if getattr(old_p, field) != getattr(new_p, field):
                            mismatches.append(
                                f"MISMATCH: {sku} {field} {getattr(old_p, field)} vs {getattr(new_p, field)} "
                                f"in {channel.idx}/{sc.country.iso2}"
                            )

    logger.info("Verification: %d mismatches found", len(mismatches))
    return mismatches
