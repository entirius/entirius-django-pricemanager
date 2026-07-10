# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import csv
import logging
from datetime import datetime
from decimal import Decimal

from django.db import reset_queries, transaction
from django.db.models import ObjectDoesNotExist
from idx_normalizator import normalize_idx, normalize_sku

from django_pricemanager.models import (
    AttributeRepresentation,
    Price,
    PriceAttribute,
    PriceList,
    PriceListStatus,
    PriceListStatusEnum,
    ProductRepresentation,
    SaleChannel,
    TaxClass,
    TaxRate,
)
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.settings import ATTR_PRICE_CSV_SEPARATOR, BULK_CREATE_BATCH_SIZE, PRICEMANAGER_DUAL_WRITE

logger_process = logging.getLogger("process")
logger = logging.getLogger(__name__)


def get_latest_pricelist(channel_idx: str, currency: str, country: str, uid: str | None = None) -> PriceList | None:
    """
    Ultimate method to get latest pricelist for given channel, currency and country and optional customer uid.
    Please use only this one method and dont create your own.
    """

    uid = str(uid) if uid else None
    # If no UID just search pricelist that are for anyone
    if not uid:
        try:
            return PriceList.objects.filter(
                sale_channel__channel__idx=channel_idx,
                country=country,
                currency__iso3=currency,
                status=PriceListStatus.enumClass.READY,
                sale_channel__customer_representation__isnull=True,
            ).latest("created_on", "pk")
        except ObjectDoesNotExist:
            return None
    else:
        # IF UID find pricelist for specific customer
        try:
            # If found return it
            return PriceList.objects.filter(
                sale_channel__channel__idx=channel_idx,
                country=country,
                currency__iso3=currency,
                status=PriceListStatus.enumClass.READY,
                sale_channel__customer_representation__uid=uid,
            ).latest("created_on", "pk")
        except ObjectDoesNotExist:
            # If not found return pricelist that are for anyone
            return get_latest_pricelist(channel_idx, currency, country, None)


def read_from_file(pricelist: PriceList, absolute_path: str | None = None):
    result = PriceListStatusEnum.IN_PROGRESS
    if absolute_path is not None:
        file_path = absolute_path
    else:
        file_path = pricelist.source_file.path

    # file should contain at least ["sku", "tax_class", and one of "net" or "gross" price]
    total = 0
    with open(file_path) as fp:
        for total, line in enumerate(fp):
            pass
    total += 1
    m = f"Importing {total} prices from csv is starting from {file_path}"
    logger.info(m)
    print(m)

    # Initialize caches to avoid N+1 queries
    tax_class_cache = {}

    # Prefetch ALL TaxClasses at once
    all_tax_classes = TaxClass.objects.all()
    for tc in all_tax_classes:
        tax_class_cache[tc.idx] = tc
    msg = f"Loaded {len(tax_class_cache)} tax classes into cache"
    logger.info(msg)
    print(msg)

    unique_skus = {}  # sku -> tax_class_idx
    unique_idxs = {}  # idx -> tax_class_idx

    with open(file_path) as f:
        reader = csv.DictReader(f)
        for item in reader:
            if item.get("tax_class", None) in ["", None] or all(
                [item.get("sku", None) in ["", None], item.get("idx", None) in ["", None]]
            ):
                continue

            tax_class_idx = item["tax_class"]

            # Collect SKUs
            if "sku" in item and item["sku"]:
                sku_normalized = normalize_sku(item["sku"])
                if sku_normalized not in unique_skus:
                    unique_skus[sku_normalized] = tax_class_idx

            # Collect IDXs
            if "idx" in item and item["idx"]:
                for idx in item["idx"].split(ATTR_PRICE_CSV_SEPARATOR):
                    idx_normalized = normalize_idx(idx)
                    if idx_normalized not in unique_idxs:
                        unique_idxs[idx_normalized] = tax_class_idx

    msg = f"Found {len(unique_skus)} unique SKUs and {len(unique_idxs)} unique attributes in CSV"
    logger.info(msg)
    print(msg)

    # Prefetch existing products and attributes
    product_cache = {}
    all_products = ProductRepresentation.objects.select_related("tax_class").all()
    for prod in all_products:
        product_cache[prod.sku] = prod

    attr_cache = {}
    all_attrs = AttributeRepresentation.objects.select_related("tax_class").all()
    for attr in all_attrs:
        attr_cache[attr.idx] = attr

    msg = f"Loaded {len(product_cache)} existing products and {len(attr_cache)} existing attributes from DB"
    logger.info(msg)
    print(msg)

    # Bulk create missing products
    new_products = []
    for sku, tax_class_idx in unique_skus.items():
        if sku not in product_cache:
            # Get or create tax class
            if tax_class_idx not in tax_class_cache:
                taxclass, created = TaxClass.objects.get_or_create(idx=tax_class_idx)
                tax_class_cache[tax_class_idx] = taxclass
            else:
                taxclass = tax_class_cache[tax_class_idx]

            new_products.append(ProductRepresentation(sku=sku, tax_class=taxclass))

    if new_products:
        msg = f"Bulk creating {len(new_products)} new products..."
        logger.info(msg)
        print(msg)
        with transaction.atomic():
            created_products = ProductRepresentation.objects.bulk_create(
                new_products, ignore_conflicts=True, batch_size=BULK_CREATE_BATCH_SIZE
            )
            # Reload to get IDs
            for prod in ProductRepresentation.objects.filter(sku__in=[p.sku for p in new_products]):
                product_cache[prod.sku] = prod
        msg = f"Created {len(new_products)} new products"
        logger.info(msg)
        print(msg)

    new_attrs = []
    for idx, tax_class_idx in unique_idxs.items():
        if idx not in attr_cache:
            # Get or create tax class
            if tax_class_idx not in tax_class_cache:
                taxclass, created = TaxClass.objects.get_or_create(idx=tax_class_idx)
                tax_class_cache[tax_class_idx] = taxclass
            else:
                taxclass = tax_class_cache[tax_class_idx]

            new_attrs.append(AttributeRepresentation(idx=idx, tax_class=taxclass))

    if new_attrs:
        msg = f"Bulk creating {len(new_attrs)} new attributes..."
        logger.info(msg)
        print(msg)
        with transaction.atomic():
            created_attrs = AttributeRepresentation.objects.bulk_create(
                new_attrs, ignore_conflicts=True, batch_size=BULK_CREATE_BATCH_SIZE
            )
            for attr in AttributeRepresentation.objects.filter(idx__in=[a.idx for a in new_attrs]):
                attr_cache[attr.idx] = attr
        msg = f"Created {len(new_attrs)} new attributes"
        logger.info(msg)
        print(msg)

    tax_rate_cache = {}
    all_tax_rates = TaxRate.objects.filter(country=pricelist.country).select_related("tax_class")
    for tax_rate in all_tax_rates:
        cache_key = (pricelist.country.id, tax_rate.tax_class_id)
        tax_rate_cache[cache_key] = tax_rate

    msg = f"Loaded {len(tax_rate_cache)} tax rates into cache for country {pricelist.country.iso2}"
    logger.info(msg)
    print(msg)

    cnt = 0
    prices_batch = []
    prices_with_attrs = []
    error_list = []

    def _dual_write_batch(created_prices):
        """Write created Price objects to CurrentPrice + PriceHistory if dual-write is enabled."""
        if not PRICEMANAGER_DUAL_WRITE:
            return
        from django_pricemanager.models import CurrentPrice, PriceHistory

        channel = pricelist.sale_channel.channel
        history_batch = []
        for price in created_prices:
            if not price.product:
                continue
            cp, _ = CurrentPrice.objects.update_or_create(
                product=price.product,
                channel=channel,
                country=pricelist.country,
                currency=pricelist.currency,
                customer_representation=pricelist.sale_channel.customer_representation,
                product_parent=price.product_parent,
                defaults={
                    "net_value": price.net_value,
                    "gross_value": price.gross_value,
                    "special_net_value": price.special_net_value,
                    "special_gross_value": price.special_gross_value,
                    "special_from_date": price.special_from_date,
                    "special_to_date": price.special_to_date,
                    "tax_rate": price.tax_rate,
                    "source": PriceSource.CSV_IMPORT,
                    "is_only_for_verified_user": pricelist.sale_channel.is_only_for_verified_user,
                },
            )
            history_batch.append(
                PriceHistory(
                    product=price.product,
                    channel=channel,
                    country=pricelist.country,
                    currency=pricelist.currency,
                    customer_representation=pricelist.sale_channel.customer_representation,
                    gross_value=price.gross_value,
                    net_value=price.net_value,
                    special_gross_value=price.special_gross_value,
                    special_net_value=price.special_net_value,
                    tax_rate=price.tax_rate,
                    source=PriceSource.CSV_IMPORT,
                )
            )
        if history_batch:
            PriceHistory.objects.bulk_create(history_batch, batch_size=BULK_CREATE_BATCH_SIZE)

    def _bulk_create_batch():
        """Helper function to bulk create accumulated prices"""
        nonlocal prices_batch, prices_with_attrs
        if not prices_batch:
            return

        try:
            # Wrap both Price and PriceAttribute creation in atomic transaction
            # If PriceAttribute fails, Price will be rolled back too
            with transaction.atomic():
                # Bulk create all prices in the batch
                created_prices = Price.objects.bulk_create(prices_batch, batch_size=BULK_CREATE_BATCH_SIZE)

                # Handle M2M relationships for attrs - bulk create PriceAttribute through table
                if prices_with_attrs:
                    price_attributes = []
                    for price_idx, attrs in prices_with_attrs:
                        if price_idx < len(created_prices):
                            price = created_prices[price_idx]
                            for attr in attrs:
                                price_attributes.append(PriceAttribute(price=price, attr=attr))

                    # Bulk create all PriceAttribute relationships at once
                    if price_attributes:
                        PriceAttribute.objects.bulk_create(
                            price_attributes, ignore_conflicts=True, batch_size=BULK_CREATE_BATCH_SIZE
                        )

            _dual_write_batch(created_prices)

            msg = f"  - Batch saved: {cnt} / {total} prices"
            print(msg)
            logger.info(msg)

            prices_batch.clear()
            prices_with_attrs.clear()
            reset_queries()

        except Exception as e:
            logger_process.exception(e)
            logger_process.error(f"Error during bulk_create: {e}")
            prices_batch.clear()
            prices_with_attrs.clear()
            raise

    with open(file_path) as f:
        reader = csv.DictReader(f)

        for item in reader:
            cnt += 1

            if item.get("tax_class", None) in ["", None] or all(
                [item.get("sku", None) in ["", None], item.get("idx", None) in ["", None]]
            ):
                continue

            # Get TaxClass from cache (should always exist after Pass 1)
            tax_class_idx = item["tax_class"]
            taxclass = tax_class_cache.get(tax_class_idx)
            if taxclass is None:
                logger.warning(f"TaxClass {tax_class_idx} not found in cache - skipping row")
                continue

            product = None
            attrs = []
            sku_idx = None
            error = False

            # Handle product (sku) - should be in cache from Pass 1
            if "sku" in item and item["sku"]:
                sku_idx = normalize_sku(item["sku"])
                product = product_cache.get(sku_idx)
                if product is None:
                    logger.warning(f"Product {sku_idx} not found in cache - skipping row")
                    error_idx_data = {"sku": sku_idx, "tax_class": item["tax_class"]}
                    error_list.append(error_idx_data)
                    continue

            # Handle attributes (idx) - should be in cache from Pass 1
            if "idx" in item and item["idx"]:
                for idx in item["idx"].split(ATTR_PRICE_CSV_SEPARATOR):
                    attr_idx = normalize_idx(idx)
                    attr = attr_cache.get(attr_idx)
                    if attr is None:
                        logger.warning(f"Attribute {attr_idx} not found in cache - skipping row")
                        error_idx_data = {"idx": attr_idx, "tax_class": item["tax_class"]}
                        error_list.append(error_idx_data)
                        error = True
                        continue
                    attrs.append(attr)

            if not product and not attrs:
                logger.warning("No sku/idx for row")
                continue

            if error:
                continue

            # Parse prices
            net_price: Decimal = Decimal(item.get("net", "0.0"))
            gross_price: Decimal = Decimal(item.get("gross", "0.0"))
            special_price_net: Decimal | None = (
                Decimal(item.get("special_price_net"))
                if item.get("special_price_net") != ""
                and item.get("special_price_net") != "0"
                and item.get("special_price_net") != "0.0"
                and item.get("special_price_net") != "0.00"
                and item.get("special_price_net") != 0.0
                and item.get("special_price_net") != " "
                and item.get("special_price_net") != None
                else None
            )
            special_price_gross: Decimal | None = (
                Decimal(item.get("special_price_gross"))
                if item.get("special_price_gross") != ""
                and item.get("special_price_gross") != "0"
                and item.get("special_price_gross") != "0.0"
                and item.get("special_price_gross") != "0.00"
                and item.get("special_price_gross") != " "
                and item.get("special_price_gross") != 0.0
                and item.get("special_price_gross") != None
                else None
            )

            special_from_date = item.get("special_from_date")
            special_to_date = item.get("special_to_date")

            try:
                special_from_date = datetime.fromisoformat(str(special_from_date))
                special_to_date = datetime.fromisoformat(str(special_to_date))
            except Exception:
                special_from_date = None
                special_to_date = None

            # Get TaxRate from cache (already prefetched)
            cache_key = (pricelist.country.id, taxclass.id)
            tax_rate = tax_rate_cache.get(cache_key)

            if tax_rate is None:
                logger.warning(
                    (
                        f"No TaxRate for product sku/attr idx={sku_idx} taxclass={taxclass} "
                        f"in given country={pricelist.country.iso2} - read_from_file()"
                    ),
                    extra={"product_sku/atrr_idx": sku_idx, "country": pricelist.country.iso2},
                )
                result = PriceListStatusEnum.ERROR
                continue

            if net_price is None and gross_price is None:
                logger_process.warning(
                    f"Cannot read prices for product/attr {sku_idx} in given country: {pricelist.country.iso2}",
                    extra={"product/attr": sku_idx, "country": pricelist.country.iso2},
                )
                result = PriceListStatusEnum.ERROR
                continue
            elif net_price == 0:
                net_price = tax_rate.net_price(gross_price)
            elif gross_price == 0:
                gross_price = tax_rate.gross_price(net_price)

            if special_price_net is not None or special_price_gross is not None:
                if special_price_net != 0 or special_price_gross != 0:
                    if (
                        (special_price_net == 0 or special_price_net is None)
                        and special_price_gross != 0
                        and special_price_gross is not None
                    ):
                        special_price_net = tax_rate.net_price(special_price_gross)
                    if (special_price_gross == 0 or special_price_gross is None) and (
                        special_price_net != 0 and special_price_net is not None
                    ):
                        special_price_gross = tax_rate.gross_price(special_price_net)

            # Create Price object (but don't save yet)
            price = Price(
                net_value=net_price,
                gross_value=gross_price,
                product=product,
                pricelist=pricelist,
                special_net_value=special_price_net,
                special_gross_value=special_price_gross,
                special_from_date=special_from_date,
                special_to_date=special_to_date,
                tax_rate=tax_rate,
            )

            prices_batch.append(price)

            # Store attrs for M2M relationship after bulk_create
            if attrs:
                prices_with_attrs.append((len(prices_batch) - 1, attrs))

            logger_process.info(
                f"Prepared price for product/idx {sku_idx} in given country: {pricelist.country.iso2} by tax rate: {tax_rate.rate}",
                extra={
                    "product_sku/idx": sku_idx,
                    "idx": [attr.idx for attr in attrs],
                    "country": pricelist.country.iso2,
                    "tax_rate": float(tax_rate.rate),
                    "pricelist": pricelist.name,
                    "source": SaleChannel.PRICE_SOURCE_CSV,
                },
            )
            result = PriceListStatusEnum.READY

            # Bulk create when batch is full
            if len(prices_batch) >= BULK_CREATE_BATCH_SIZE:
                _bulk_create_batch()

        # Bulk create remaining prices
        if prices_batch:
            _bulk_create_batch()

        if len(error_list) > 0:
            logger_process.info(
                f"Errors while creating prices for products in given country: {pricelist.country.iso2}",
                extra={"products_errors": error_list},
            )

    m = "Importing prices from csv is done"
    logger.info(m)
    print(m)
    return result
