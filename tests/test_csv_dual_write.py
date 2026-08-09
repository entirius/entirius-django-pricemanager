# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Integration tests for pricelist_service.read_from_file() dual-write to CurrentPrice.

_dual_write_batch (writer=PriceSource.CSV_IMPORT) had guard/bounds unit coverage only via
test_price_write_guard.py's abstract PriceSource.CSV_IMPORT cases — no test actually ran a
CSV file through read_from_file() and checked the resulting CurrentPrice rows.
"""

from decimal import Decimal

import pytest

import django_pricemanager.services.pricelist_service as pricelist_service_module
from django_pricemanager.models import CurrentPrice, PriceList, SaleChannel
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_bounds import PriceBoundsConfig
from django_pricemanager.models.pricelist import PriceListStatusEnum
from django_pricemanager.services.pricelist_service import read_from_file


@pytest.fixture
def dual_write_enabled(monkeypatch):
    monkeypatch.setattr(pricelist_service_module, "PRICEMANAGER_DUAL_WRITE", True)


def _write_csv(tmp_path, rows):
    path = tmp_path / "prices.csv"
    header = "sku,tax_class,net,gross\n"
    body = "".join(f"{r['sku']},{r['tax_class']},{r['net']},{r['gross']}\n" for r in rows)
    path.write_text(header + body)
    return str(path)


def _make_pricelist(ns):
    sale_channel = SaleChannel.objects.create(
        idx="sc-csv-pl",
        name="CSV PL",
        channel=ns.channel,
        country=ns.pl,
        price_source=SaleChannel.PRICE_SOURCE_CSV,
    )
    return PriceList.objects.create(
        sale_channel=sale_channel,
        currency=ns.pln,
        country=ns.pl,
        status=PriceListStatusEnum.IN_PROGRESS,
    )


@pytest.mark.django_db
class TestCsvImportDualWrite:
    def test_writes_current_price_with_csv_import_source(self, products, dual_write_enabled, tmp_path):
        ns = products
        csv_path = _write_csv(
            tmp_path, [{"sku": ns.chair.sku, "tax_class": "standard", "net": "100.00", "gross": "123.00"}]
        )
        pricelist = _make_pricelist(ns)

        read_from_file(pricelist, csv_path)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.CSV_IMPORT
        assert cp.gross_value == Decimal("123.00")

    def test_generation_row_gets_overwritten_by_csv_import(self, products, dual_write_enabled, tmp_path):
        """CSV import is not pricefighter/baseline — precedence keeps overwriting everything."""
        ns = products
        rate = ns.rates[("standard", "PL")]
        CurrentPrice.objects.create(
            product=ns.chair,
            channel=ns.channel,
            country=ns.pl,
            currency=ns.pln,
            tax_rate=rate,
            net_value=Decimal("50.00"),
            gross_value=rate.gross_price(Decimal("50.00")),
            source=PriceSource.GENERATION,
        )
        csv_path = _write_csv(
            tmp_path, [{"sku": ns.chair.sku, "tax_class": "standard", "net": "100.00", "gross": "123.00"}]
        )
        pricelist = _make_pricelist(ns)

        read_from_file(pricelist, csv_path)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.source == PriceSource.CSV_IMPORT
        assert cp.gross_value == Decimal("123.00")

    def test_clamps_to_map_bound(self, products, dual_write_enabled, tmp_path):
        ns = products
        PriceBoundsConfig.objects.create(product=ns.chair, channel=ns.channel, map_value=Decimal("500.00"))
        csv_path = _write_csv(
            tmp_path, [{"sku": ns.chair.sku, "tax_class": "standard", "net": "10.00", "gross": "12.30"}]
        )
        pricelist = _make_pricelist(ns)

        read_from_file(pricelist, csv_path)

        cp = CurrentPrice.objects.get(product=ns.chair, channel=ns.channel, country=ns.pl, currency=ns.pln)
        assert cp.gross_value == Decimal("500.00")
        assert cp.source == PriceSource.CSV_IMPORT

    def test_noop_when_dual_write_disabled(self, products, monkeypatch, tmp_path):
        monkeypatch.setattr(pricelist_service_module, "PRICEMANAGER_DUAL_WRITE", False)

        ns = products
        csv_path = _write_csv(
            tmp_path, [{"sku": ns.chair.sku, "tax_class": "standard", "net": "100.00", "gross": "123.00"}]
        )
        pricelist = _make_pricelist(ns)

        read_from_file(pricelist, csv_path)

        assert not CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel, country=ns.pl).exists()
