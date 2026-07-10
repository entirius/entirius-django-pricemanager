# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import concurrent.futures
import logging

from django.db.models import Q
from django_regional.models import Country, Currency
from idx_normalizator import normalize_idx
from tqdm import tqdm

from django_pricemanager.models import (
    CalculateDirectionEnum,
    Channel,
    Price,
    PriceList,
    PriceListStatusEnum,
    SaleChannel,
    TaxClass,
    TaxRate,
)
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.services.pricelist_service import read_from_file
from django_pricemanager.services.sale_channel_service import (
    get_latest_pricelist_by_source,
)
from django_pricemanager.services.tax_class_service import read_from_csv
from django_pricemanager.settings import CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING, PRICEMANAGER_DUAL_WRITE

from .bi import PM_CreatePricelistFromCsvEvent, PM_CreatePricelistsEvent

logger_process = logging.getLogger("process")
logger = logging.getLogger(__name__)


def check_pricelist_soruce(price_source: str):
    match price_source:
        case SaleChannel.PRICE_SOURCE_CSV:
            return SaleChannel.PRICE_SOURCE_CSV
        case SaleChannel.PRICE_SOURCE_API:
            return SaleChannel.PRICE_SOURCE_API
        case _:
            return SaleChannel.PRICE_SOURCE_CSV


def create_pricelists(channel: Channel, price_source: str = SaleChannel.PRICE_SOURCE_CSV):
    logger_process.info(f"Creating pricelists for channel={channel}")
    bev = PM_CreatePricelistsEvent(channel_idx=channel.idx, is_ongoing_event=True)
    raport = {}
    price_source = check_pricelist_soruce(price_source)
    try:
        pricelist: PriceList = get_latest_pricelist_by_source(channel, price_source)
        prices = Price.objects.filter(pricelist=pricelist)
        raport["prices_count"] = len(prices)
        rest_countries = (
            TaxRate.objects.filter(~Q(country=pricelist.country)).values_list("country", flat=True).distinct()
        )
        countries_objects = Country.objects.filter(id__in=rest_countries)

        if channel.calculate_countries.exists():
            countries_objects = countries_objects.filter(id__in=channel.calculate_countries.all())

        def process_country(country_obj):
            country = country_obj
            if "countries" not in raport:
                raport["countries"] = []
            raport["countries"].append(str(country.iso2))
            name = SaleChannel.name_by_channel_and_country(channel.name, country)
            new_sale_channel, created = SaleChannel.objects.get_or_create(
                price_source=SaleChannel.PRICE_SOURCE_GENERATED,
                channel=channel,
                name=name,
                idx=normalize_idx(name),
                country=country,
            )
            new_pricelist: PriceList = PriceList(
                sale_channel=new_sale_channel,
                currency=pricelist.currency,  # not used at a moment
                name=name,
                status=PriceListStatusEnum.IN_PROGRESS,
                country=country,
            )
            new_pricelist.save()
            for price in tqdm(prices, desc=f"Creating prices for country: {country.iso2} - channel: {channel.idx}"):
                create_price_from_source(new_pricelist, price, country, channel.calculate_direction)
            new_pricelist.status = PriceListStatusEnum.READY
            new_pricelist.save()

        with concurrent.futures.ThreadPoolExecutor(max_workers=CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING) as executor:
            futures = [executor.submit(process_country, country_obj) for country_obj in countries_objects]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        if raport:
            bev.set_details(raport)
            bev.finish_with_success(finish_tag="Pricelists has been created")
    except Exception as e:
        logger_process.error(f"Error while creating pricelists error={e}")
        bev.set_details(raport)
        bev.finish_with_error(finish_tag="Error while creating pricelists", error_message=str(e))
        raise e


def create_price_from_source(pricelist: PriceList, price_original: Price, country, calculate_direction):
    if price_original.attrs.exists():
        tax_rate = TaxRate.objects.filter(
            country=country, tax_class__attr_representations__prices_attrs=price_original
        ).first()
        sku_idx = price_original.attrs.values_list("idx", flat=True)
    else:
        tax_rate = TaxRate.objects.get(country=country, tax_class__product_representations__prices=price_original)
        sku_idx = price_original.product.sku
    if tax_rate is None:
        logger_process.warning(
            f"No TaxRate for sku/idx {sku_idx} in given country: {country.iso2} - create_price_from_source()",
            extra={"product_sku": sku_idx, "country": country.iso2},
        )

    if CalculateDirectionEnum.FROM_GROSS_TO_NET == calculate_direction:
        net_value = tax_rate.net_price(price_original.gross_value)
        gross_value = price_original.gross_value
        special_net_value = (
            tax_rate.net_price(price_original.special_gross_value)
            if price_original.special_gross_value is not None
            else None
        )
        special_gross_value = price_original.special_gross_value
    else:
        # FROM NET TO GROSS IS DEFAULT
        net_value = price_original.net_value
        gross_value = tax_rate.gross_price(price_original.net_value)
        special_net_value = price_original.special_net_value
        special_gross_value = (
            tax_rate.gross_price(price_original.special_net_value)
            if price_original.special_net_value is not None
            else None
        )

    price = Price(
        pricelist=pricelist,
        product=price_original.product if price_original.product else None,
        product_parent=price_original.product_parent if price_original.product_parent else None,
        net_value=net_value,
        gross_value=gross_value,
        special_net_value=special_net_value,
        special_gross_value=special_gross_value,
        special_from_date=price_original.special_from_date,
        special_to_date=price_original.special_to_date,
        tax_rate=tax_rate,
    )
    price.save()

    if price_original.attrs.exists():
        price.attrs.set(price_original.attrs.all())
        price.save()

    # Dual-write to CurrentPrice + PriceHistory
    if PRICEMANAGER_DUAL_WRITE and price.product:
        from django_pricemanager.models import CurrentPrice, PriceHistory

        channel = pricelist.sale_channel.channel
        cp, _ = CurrentPrice.objects.update_or_create(
            product=price.product,
            channel=channel,
            country=country,
            currency=pricelist.currency,
            customer_representation=pricelist.sale_channel.customer_representation,
            product_parent=price.product_parent,
            defaults={
                "net_value": net_value,
                "gross_value": gross_value,
                "special_net_value": special_net_value,
                "special_gross_value": special_gross_value,
                "special_from_date": price_original.special_from_date,
                "special_to_date": price_original.special_to_date,
                "tax_rate": tax_rate,
                "source": PriceSource.GENERATION,
                "is_only_for_verified_user": pricelist.sale_channel.is_only_for_verified_user,
            },
        )
        PriceHistory.objects.create(
            product=price.product,
            channel=channel,
            country=country,
            currency=pricelist.currency,
            customer_representation=pricelist.sale_channel.customer_representation,
            gross_value=gross_value,
            net_value=net_value,
            special_gross_value=special_gross_value,
            special_net_value=special_net_value,
            tax_rate=tax_rate,
            source=PriceSource.GENERATION,
        )

    logger_process.info(
        f"Created prices for sku/idx {sku_idx} in given country: {country.iso2} by tax rate: {tax_rate.rate}",
        extra={
            "sku_idx": sku_idx,
            "country": country.iso2,
            "tax_rate": float(tax_rate.rate),
            "pricelist": pricelist.name,
            "source": SaleChannel.PRICE_SOURCE_GENERATED,
        },
    )


def create_pricelist_from_csv(sale_channel: SaleChannel, currency_code: str, file_path: str):
    bev = PM_CreatePricelistFromCsvEvent(
        file_path=file_path, channel_idx=sale_channel.idx, currency_code=currency_code, is_ongoing_event=True
    )
    try:
        currency: Currency = Currency.objects.filter(iso3=currency_code).first()
        if currency is None:
            raise ValueError(f"Currency {currency_code} not found in django_regional currency table.")
        pricelist: PriceList = PriceList(
            sale_channel=sale_channel,
            currency=currency,
            country=sale_channel.country,
            name="import",
            status=PriceListStatusEnum.IN_PROGRESS,
        )
        pricelist.save()
        status = read_from_file(pricelist, file_path)
        pricelist.status = status
        pricelist.save()
        bev.finish_with_success(finish_tag="Pricelist has been created")
    except Exception as e:
        logger_process.error(f"Error while creating pricelist error={e}")
        bev.finish_with_error(finish_tag="Error while creating pricelists", error_message=str(e))
        raise e


def create_tax_class_from_csv(tax_class_name: str, file_path: str):
    tax_class, created = TaxClass.objects.get_or_create(idx=tax_class_name, defaults={"name": tax_class_name})
    read_from_csv(tax_class, file_path)
