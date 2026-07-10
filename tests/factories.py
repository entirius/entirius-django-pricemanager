# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

import factory
from django_regional.models import Country, Currency
from factory.django import DjangoModelFactory

from django_pricemanager.models import (
    Channel,
    CurrentPrice,
    CustomerRepresentation,
    PriceHistory,
    ProductRepresentation,
    TaxClass,
    TaxRate,
)
from django_pricemanager.models.channel import CalculateDirectionEnum


class CountryFactory(DjangoModelFactory):
    """Creates Country records bypassing the save() guard via bulk_create."""

    iso2 = factory.Sequence(lambda n: f"C{n:1d}")
    iso3 = factory.Sequence(lambda n: f"CY{n:1d}")
    name_en = factory.Sequence(lambda n: f"Country {n}")
    name_pl = factory.Sequence(lambda n: f"Kraj {n}")
    prefix = ""

    class Meta:
        model = Country
        django_get_or_create = ("iso2",)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        existing = model_class.objects.filter(iso2=kwargs["iso2"]).first()
        if existing:
            return existing
        instance = model_class(**kwargs)
        model_class.objects.bulk_create([instance])
        return model_class.objects.get(iso2=kwargs["iso2"])


class CurrencyFactory(DjangoModelFactory):
    iso3 = factory.Sequence(lambda n: f"C{n:02d}")
    name_en = factory.Sequence(lambda n: f"Currency {n}")
    name_pl = factory.Sequence(lambda n: f"Currency {n}")
    symbol = factory.Sequence(lambda n: f"${n}")

    class Meta:
        model = Currency
        django_get_or_create = ("iso3",)


class ChannelFactory(DjangoModelFactory):
    idx = factory.Sequence(lambda n: f"channel-{n}")
    name = factory.Sequence(lambda n: f"Channel {n}")
    calculate_direction = CalculateDirectionEnum.FROM_NET_TO_GROSS

    class Meta:
        model = Channel
        django_get_or_create = ("idx",)


class TaxClassFactory(DjangoModelFactory):
    idx = factory.Sequence(lambda n: f"tax-class-{n}")
    name = factory.Sequence(lambda n: f"Tax Class {n}")

    class Meta:
        model = TaxClass
        django_get_or_create = ("idx",)


class TaxRateFactory(DjangoModelFactory):
    tax_class = factory.SubFactory(TaxClassFactory)
    country = factory.SubFactory(CountryFactory)
    rate = Decimal("0.2300")

    class Meta:
        model = TaxRate
        django_get_or_create = ("tax_class", "country")


class ProductRepresentationFactory(DjangoModelFactory):
    tax_class = factory.SubFactory(TaxClassFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n:04d}")

    class Meta:
        model = ProductRepresentation
        django_get_or_create = ("sku",)


class CustomerRepresentationFactory(DjangoModelFactory):
    uid = factory.Sequence(lambda n: f"customer-uid-{n}")
    user_email = factory.Sequence(lambda n: f"customer{n}@example.com")

    class Meta:
        model = CustomerRepresentation
        django_get_or_create = ("uid",)


class CurrentPriceFactory(DjangoModelFactory):
    product = factory.SubFactory(ProductRepresentationFactory)
    product_parent = None
    channel = factory.SubFactory(ChannelFactory)
    country = factory.SubFactory(CountryFactory)
    currency = factory.SubFactory(CurrencyFactory)
    customer_representation = None
    tax_rate = factory.SubFactory(TaxRateFactory)
    net_value = Decimal("100.0000")
    gross_value = Decimal("123.0000")
    source = "csv_import"

    class Meta:
        model = CurrentPrice


class PriceHistoryFactory(DjangoModelFactory):
    product = factory.SubFactory(ProductRepresentationFactory)
    channel = factory.SubFactory(ChannelFactory)
    country = factory.SubFactory(CountryFactory)
    currency = factory.SubFactory(CurrencyFactory)
    customer_representation = None
    tax_rate = factory.SubFactory(TaxRateFactory)
    net_value = Decimal("100.0000")
    gross_value = Decimal("123.0000")
    source = "csv_import"

    class Meta:
        model = PriceHistory
