# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django_regional.models import Country, Currency
from idx_normalizator import normalize_idx, normalize_sku
from process_logger import ProcessLoggerMixin

from django_pricemanager.models import (
    Channel,
    Price,
    PriceList,
    PriceListStatusEnum,
    ProductRepresentation,
    SaleChannel,
    TaxClass,
    TaxRate,
)


class DjangoPricemanagerRepository(ProcessLoggerMixin):
    name = "django_pricemanager"
    locale: str
    channel: Channel
    BULK_BATCH_SIZE: int = 1000
    regional_countries: dict[str, Country] = {}

    def get_tax_class(self, idx: str) -> TaxClass:
        return TaxClass.objects.get(idx=idx)

    def get_country(self, country_code: str) -> Country:
        if country_code in self.regional_countries:
            return self.regional_countries[country_code]
        else:
            country = Country.objects.get(iso2=country_code)
            self.regional_countries[country_code] = country
            return country

    def product_representation_bulk_get_or_create(
        self, skus: list[str | int], tax_class_idx: str
    ) -> tuple[dict[str, ProductRepresentation], dict[str, ProductRepresentation]]:
        tax_class = self.get_tax_class(tax_class_idx)
        normalized_skus = [normalize_sku(sku) for sku in skus]

        create = {}
        for sku in normalized_skus:
            create[sku] = ProductRepresentation(sku=sku, tax_class=tax_class)
        result = ProductRepresentation.objects.filter(sku__in=normalized_skus)
        get = {}
        for pr_in_db in result:
            create.pop(pr_in_db.sku)
            get[pr_in_db.sku] = pr_in_db

        created = {}
        if len(create) > 0:
            self.logger.set_db_operation("BULK_CREATE", self.name, "ProductRepresentation")
            prs = ProductRepresentation.objects.bulk_create(create.values(), batch_size=self.BULK_BATCH_SIZE)
            for pr in prs:
                created[pr.sku] = pr
            self.logger.set_code(None)
            self.logger.info(f"ProductRepresentation created in bulk: {len(create)}")

        return created, get

    def sale_channel_get_or_create(self, country_code: str) -> SaleChannel:
        name = SaleChannel.name_by_channel_and_country(self.channel.idx, country_code)
        country = self.get_country(country_code)
        idx = normalize_idx(name)
        try:
            sale_channel = SaleChannel.objects.get(
                channel=self.channel,
                price_source=SaleChannel.PRICE_SOURCE_API,
                country=country,
                customer_representation__isnull=True,
            )
        except ObjectDoesNotExist:
            sale_channel = SaleChannel(
                idx=idx,
                name=name,
                channel=self.channel,
                price_source=SaleChannel.PRICE_SOURCE_API,
                country=country,
                customer_representation=None,
            )
            sale_channel.save()
            self.logger.set_db_operation("CREATE", self.name, "SaleChannel")
            self.logger.set_code(None)
            self.logger.info(f"SaleChannel saved for channel: {self.channel.idx} and country: {country}")
        except MultipleObjectsReturned:
            sale_channel = SaleChannel.objects.filter(
                channel=self.channel,
                price_source=SaleChannel.PRICE_SOURCE_API,
                country=country,
                customer_representation__isnull=True,
            ).latest("pk")
            self.logger.set_code(None)
            self.logger.debug(f"Multiple SaleChannels found for channel: {self.channel.idx} and country: {country}")
        return sale_channel

    def get_currency_by_iso(self, iso3: str) -> Currency:
        return Currency.objects.get(iso3=iso3)

    def create_pricelist(self, sale_channel: SaleChannel, currency: Currency) -> PriceList:
        pricelist = PriceList(
            sale_channel=sale_channel,
            currency=currency,
            country=sale_channel.country,
            name=sale_channel.idx,
            status=PriceListStatusEnum.IN_PROGRESS,
        )
        pricelist.save()
        self.logger.set_db_operation("CREATE", self.name, "PriceList")
        self.logger.set_code(None)
        self.logger.info(f"PriceList saved for SaleChannel: {sale_channel.idx} and Currency: {currency.iso3}")
        return pricelist

    def get_existing_pricelist(self, sale_channel: SaleChannel, currency: Currency) -> PriceList | None:
        return PriceList.objects.filter(
            sale_channel=sale_channel, currency=currency, country=sale_channel.country, status=PriceListStatusEnum.READY
        ).latest()

    def get_active_pricelists(self, sale_channel: SaleChannel, currency: Currency) -> dict[str, PriceList | None]:
        """
        Get latest READY and IN_PROGRESS pricelists for journal log updates.

        Returns dict with:
        - 'READY': Latest READY pricelist (or None)
        - 'IN_PROGRESS': Latest IN_PROGRESS pricelist (or None)

        This allows journal logs to update BOTH:
        1. Current active pricelist (READY)
        2. New pricelist being created by bulk import (IN_PROGRESS)
        """
        pricelists = {"READY": None, "IN_PROGRESS": None}

        try:
            pricelists["READY"] = PriceList.objects.filter(
                sale_channel=sale_channel,
                currency=currency,
                country=sale_channel.country,
                status=PriceListStatusEnum.READY,
            ).latest()
        except PriceList.DoesNotExist:
            pass

        try:
            pricelists["IN_PROGRESS"] = PriceList.objects.filter(
                sale_channel=sale_channel,
                currency=currency,
                country=sale_channel.country,
                status=PriceListStatusEnum.IN_PROGRESS,
            ).latest()
        except PriceList.DoesNotExist:
            pass

        return pricelists

    def check_latest_existing_pricelist(self, sale_channel: SaleChannel, currency: Currency) -> PriceList | None:
        return PriceList.objects.filter(
            sale_channel=sale_channel, currency=currency, country=sale_channel.country
        ).latest()

    def get_existing_pricelist_from_pks(
        self, pricelist_pks_to_ready, sale_channel: SaleChannel, currency: Currency
    ) -> PriceList | None:

        return PriceList.objects.filter(
            sale_channel=sale_channel, currency=currency, country=sale_channel.country, pk__in=pricelist_pks_to_ready
        ).latest()

    def set_ready_pricelist_by_pks(self, pricelist_pks_to_ready: list[int]) -> int:
        """
        Set the status of PriceLists to READY based on the provided primary keys.
        """
        self.logger.set_db_operation("UPDATE", self.name, "PriceList")
        updated_count = PriceList.objects.filter(pk__in=pricelist_pks_to_ready).update(status=PriceListStatusEnum.READY)
        self.logger.set_code(None)
        self.logger.info(f"PriceLists set to READY: {updated_count}")
        return updated_count

    def get_prices(self, pricelist: PriceList) -> dict[str, Price]:
        prices = (
            Price.objects.filter(pricelist=pricelist, product_parent__isnull=True)
            .prefetch_related("product")
            .iterator(self.BULK_BATCH_SIZE)
        )
        return {price.product.sku: price for price in prices}

    def get_tax_rate(self, tax_class_idx: str, country: str) -> TaxRate | None:
        try:
            tax_rate = TaxRate.objects.get(tax_class__idx=tax_class_idx, country=country)
        except ObjectDoesNotExist:
            self.logger.set_code(None)
            self.logger.error(f"Can't find tax_rate for country {country}")
            tax_rate = None

        return tax_rate

    def price_bulk_update_or_create(
        self, prices: list[Price], updated_at: datetime | None = None
    ) -> tuple[list[Price], list[Price], int]:
        """
        Bulk update or create prices with timestamp-based conditional update.

        Args:
            prices: List of Price objects to create/update
            updated_at: Timestamp for conditional update (only update if DB record is older)
                       If None, updates unconditionally (backward compatibility)

        Returns:
            Tuple of (created_list, updated_list, skipped_count)
            - created_list: List of created prices
            - updated_list: List of updated prices
            - skipped_count: Number of prices skipped due to timestamp check

        Timestamp-based Protection:
            If updated_at is provided, only updates prices where:
            - DB updated_at < new updated_at (update with newer data)
            - OR DB updated_at is NULL (first time setting)
            This prevents race condition where bulk import (old data) overwrites
            journal update (fresh data).
        """
        if updated_at:
            self.logger.add_log_param("updated_at", updated_at.isoformat())

        prices_to_create_dict = {}
        for price in prices:
            key = (price.pricelist_id, price.product_id, price.product_parent_id)
            prices_to_create_dict[key] = price

        pricelist_ids = list(set(price.pricelist_id for price in prices))
        product_ids = list(set(price.product_id for price in prices))

        existing_prices = Price.objects.filter(
            pricelist_id__in=pricelist_ids,
            product_id__in=product_ids,
        ).select_related("product")

        to_create = prices_to_create_dict.copy()
        to_update = []
        skipped_count = 0

        for existing_price in existing_prices:
            key = (existing_price.pricelist_id, existing_price.product_id, existing_price.product_parent_id)

            if key not in prices_to_create_dict:
                continue

            new_price = prices_to_create_dict[key]

            if updated_at is not None:
                if existing_price.updated_at is not None and existing_price.updated_at >= updated_at:
                    self.logger.add_log_param_once("skipped_sku", existing_price.product.sku)
                    self.logger.add_log_param_once("db_updated_at", existing_price.updated_at.isoformat())
                    self.logger.debug(
                        f"Skipping price update for product {existing_price.product.sku}: "
                        f"DB updated_at ({existing_price.updated_at.isoformat()}) >= "
                        f"new updated_at ({updated_at.isoformat()})"
                    )
                    to_create.pop(key)
                    skipped_count += 1
                    continue

            # Update existing price
            existing_price.net_value = new_price.net_value
            existing_price.gross_value = new_price.gross_value
            existing_price.special_net_value = new_price.special_net_value
            existing_price.special_gross_value = new_price.special_gross_value
            existing_price.tax_rate = new_price.tax_rate
            existing_price.special_from_date = new_price.special_from_date
            existing_price.special_to_date = new_price.special_to_date
            existing_price.updated_at = new_price.updated_at

            to_update.append(existing_price)
            to_create.pop(key)

        created = []
        if len(to_create) > 0:
            self.logger.set_db_operation("BULK_CREATE", self.name, "Price")
            created = Price.objects.bulk_create(to_create.values(), batch_size=self.BULK_BATCH_SIZE)
            self.logger.set_code(None)
            self.logger.info(f"Prices created in bulk: {len(created)}")

        if len(to_update) > 0:
            self.logger.set_db_operation("BULK_UPDATE", self.name, "Price")
            bulk_update_kwargs = {
                "objs": to_update,
                "fields": [
                    "net_value",
                    "gross_value",
                    "special_net_value",
                    "special_gross_value",
                    "product_parent",
                    "tax_rate",
                    "special_from_date",
                    "special_to_date",
                    "updated_at",
                ],
                "batch_size": self.BULK_BATCH_SIZE,
            }
            if updated_at is not None:
                bulk_update_kwargs["filter_conditions"] = {"updated_at__lt": updated_at}

            updated_count = Price.objects.bulk_update(**bulk_update_kwargs)
            self.logger.set_code(None)
            self.logger.info(f"Prices updated in bulk: {updated_count}")

        if skipped_count > 0:
            self.logger.info(f"Price updates skipped (timestamp check): {skipped_count}")

        return created, to_update, skipped_count

    def price_bulk_create(self, prices: list[Price]) -> list[Price]:
        """
        Legacy method - delegates to price_bulk_update_or_create without timestamp protection.
        Kept for backward compatibility.
        """
        created, updated, _ = self.price_bulk_update_or_create(prices, updated_at=None)
        return created + updated

    def price_delete(self, pricelist: PriceList, filter_param):
        self.logger.set_db_operation("DELETE", self.name, "Price")
        if not pricelist and not filter_param:
            raise ValueError("No pricelist or filter_param provided for deletion")
        deleted = pricelist.prices.filter(filter_param).delete()
        self.logger.set_code(None)
        self.logger.info(f"Prices deleted: {len(deleted)}")
        return deleted

    def update_price_in_existing_pricelist(
        self, pricelist: PriceList, product_rep: ProductRepresentation, price_data: dict
    ) -> Price | None:
        """
        Update or create a price for a specific product in an EXISTING pricelist.

        This method is used by journal-based updates to update prices in the READY pricelist
        without creating a new pricelist (unlike bulk imports which create new pricelists).

        Args:
            pricelist: Existing READY pricelist to update
            product_rep: ProductRepresentation for the product
            price_data: Dictionary with price fields:
                - net_value: Decimal
                - gross_value: Decimal
                - special_net_value: Optional[Decimal]
                - special_gross_value: Optional[Decimal]
                - tax_rate: Optional[TaxRate]
                - special_from_date: Optional[datetime]
                - special_to_date: Optional[datetime]

        Returns:
            Price: Updated or created Price object
        """
        self.logger.set_db_operation("UPDATE_OR_CREATE", self.name, "Price")
        price, created = Price.objects.update_or_create(
            pricelist=pricelist,
            product=product_rep,
            defaults={
                "net_value": price_data["net_value"],
                "gross_value": price_data["gross_value"],
                "special_net_value": price_data.get("special_net_value"),
                "special_gross_value": price_data.get("special_gross_value"),
                "tax_rate": price_data.get("tax_rate"),
                "special_from_date": price_data.get("special_from_date"),
                "special_to_date": price_data.get("special_to_date"),
            },
        )

        action = "created" if created else "updated"
        self.logger.set_code(None)
        self.logger.info(f"Price {action} in existing pricelist for SKU {product_rep.sku}")

        return price
