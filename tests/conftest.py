# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django_regional.models import Country, Currency
from rest_framework.test import APIClient

from django_pricemanager.models import (
    Channel,
    CurrentPrice,
    ProductRepresentation,
    TaxClass,
    TaxRate,
)
from django_pricemanager.models.channel import CalculateDirectionEnum

User = get_user_model()


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin",
        password="admin123",
        email="admin@test.com",
    )


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="user",
        password="user123",
        email="user@test.com",
    )


# ---------------------------------------------------------------------------
# Tax + country setup
# ---------------------------------------------------------------------------


def _create_country(iso2: str, iso3: str, name_en: str, name_pl: str) -> Country:
    """Bypass Country.save() guard by using bulk_create."""
    existing = Country.objects.filter(iso2=iso2).first()
    if existing:
        return existing
    country = Country(iso2=iso2, iso3=iso3, name_en=name_en, name_pl=name_pl, prefix="")
    Country.objects.bulk_create([country])
    return Country.objects.get(iso2=iso2)


@pytest.fixture
def tax_setup(db):
    pl = _create_country("PL", "POL", "Poland", "Polska")
    de = _create_country("DE", "DEU", "Germany", "Niemcy")
    fr = _create_country("FR", "FRA", "France", "Francja")

    standard = TaxClass.objects.create(idx="standard", name="Standard")
    reduced = TaxClass.objects.create(idx="reduced", name="Reduced")

    rate_data = [
        (standard, pl, Decimal("0.2300")),
        (standard, de, Decimal("0.1900")),
        (standard, fr, Decimal("0.2000")),
        (reduced, pl, Decimal("0.0800")),
        (reduced, de, Decimal("0.0700")),
        (reduced, fr, Decimal("0.0500")),
    ]

    rates = {}
    for tax_class, country, rate in rate_data:
        tax_rate = TaxRate.objects.create(tax_class=tax_class, country=country, rate=rate)
        rates[(tax_class.idx, country.iso2)] = tax_rate

    return SimpleNamespace(
        pl=pl,
        de=de,
        fr=fr,
        standard=standard,
        reduced=reduced,
        rates=rates,
    )


# ---------------------------------------------------------------------------
# Channel + currency setup
# ---------------------------------------------------------------------------


@pytest.fixture
def channel_setup(tax_setup):
    channel = Channel.objects.create(
        idx="b2c-europe",
        name="B2C Europe",
        calculate_direction=CalculateDirectionEnum.FROM_NET_TO_GROSS,
    )
    channel.calculate_countries.set([tax_setup.pl, tax_setup.de, tax_setup.fr])
    channel.default_country = tax_setup.pl
    channel.save()

    pln, _ = Currency.objects.get_or_create(
        iso3="PLN", defaults={"name_en": "Polish Zloty", "name_pl": "Polski złoty", "symbol": "zł"}
    )
    eur, _ = Currency.objects.get_or_create(iso3="EUR", defaults={"name_en": "Euro", "name_pl": "Euro", "symbol": "€"})

    return SimpleNamespace(
        **vars(tax_setup),
        channel=channel,
        pln=pln,
        eur=eur,
    )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@pytest.fixture
def products(channel_setup):
    chair = ProductRepresentation.objects.create(
        sku="CHAIR-001",
        tax_class=channel_setup.standard,
    )
    food = ProductRepresentation.objects.create(
        sku="FOOD-001",
        tax_class=channel_setup.reduced,
    )
    bundle = ProductRepresentation.objects.create(
        sku="BUNDLE-001",
        tax_class=channel_setup.standard,
    )

    return SimpleNamespace(
        **vars(channel_setup),
        chair=chair,
        food=food,
        bundle=bundle,
    )


# ---------------------------------------------------------------------------
# Populated prices (chair + food × PL/DE/FR × PLN)
# ---------------------------------------------------------------------------


@pytest.fixture
def prices_populated(products):
    ns = products
    net = Decimal("100.00")
    price_records = []

    for product, tax_class_idx in [(ns.chair, "standard"), (ns.food, "reduced")]:
        for country_iso2 in ("PL", "DE", "FR"):
            country = getattr(ns, country_iso2.lower())
            tax_rate = ns.rates[(tax_class_idx, country_iso2)]
            gross = tax_rate.gross_price(net)
            price = CurrentPrice.objects.create(
                product=product,
                channel=ns.channel,
                country=country,
                currency=ns.pln,
                tax_rate=tax_rate,
                net_value=net,
                gross_value=gross,
                source="csv_import",
            )
            price_records.append(price)

    return SimpleNamespace(
        **vars(ns),
        prices=price_records,
    )
