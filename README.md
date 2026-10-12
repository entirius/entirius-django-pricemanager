# entirius-django-pricemanager

A Django module for product prices in Entirius, the open-source modular ecommerce platform. It keeps one current
price per product, sales channel, country and currency, converts between net and gross with country tax rates, and
records every change in a history log.

[![PyPI](https://img.shields.io/pypi/v/entirius-django-pricemanager.svg)](https://pypi.org/project/entirius-django-pricemanager/)
[![Python](https://img.shields.io/pypi/pyversions/entirius-django-pricemanager.svg)](https://pypi.org/project/entirius-django-pricemanager/)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](https://github.com/entirius/entirius-django-pricemanager/blob/develop/LICENSE)

## What it does

- Stores one live price per product, channel, country and currency, with an append-only history of every change.
- Calculates net and gross values from tax classes and country-specific tax rates.
- Supports special prices with validity dates, attribute-level prices and customer tier prices.
- Guards writes: a precedence table decides which price source may overwrite another, and bounds enforce a floor
  from a minimum price and a minimum margin over the purchase cost.
- Imports prices and tax rates from CSV files with management commands.
- Exposes an admin REST API for price editing, channels and tax classes, used by the CMS.

## Installation

```shell
uv add entirius-django-pricemanager
pip install entirius-django-pricemanager
```

```python
INSTALLED_APPS = [
    ...
    "django_utils",
    "django_regional",
    "django_pricemanager",
]

# urls.py
urlpatterns = [
    path("", include("django_pricemanager.urls")),
]
```

The admin API mounts at `api/pricemanager/v2/admin/`. Required settings: `BI_ENVIRONMENT` and `BI_BUSINESS_UNIT`
(read when the module's event definitions are imported). The optional ones are listed with their defaults in
https://github.com/entirius/entirius-django-pricemanager/blob/develop/docs/configuration.md.

Celery queue: `pricemanager_create_pricelist`. Optional integrations with `django_pim` (channel sync) and the
supplier cost feed are soft imports and do nothing when those modules are absent.

## Quick start

```python
from django_pricemanager.output import get_product_price_for_country_and_currency

price = get_product_price_for_country_and_currency("default", "SKU-1", "PL", "PLN")
```

Load prices first: `python manage.py import-pricelist-from-csv` (arguments in
https://github.com/entirius/entirius-django-pricemanager/blob/develop/docs/commands.md).

## Requirements

- Python 3.11 or newer, Django 5.0 or newer.
- PostgreSQL 15 or newer.
- Entirius packages pulled in: `entirius-django-regional`, `entirius-django-utils`, `entirius-py-bievents`,
  `entirius-py-idx-normalizator`, `entirius-py-int-enum-choices`, `entirius-py-lockfile`,
  `entirius-py-process-logger`.

## Documentation

- Module docs: https://github.com/entirius/entirius-django-pricemanager/tree/develop/docs
- Entirius documentation: https://docs.entirius.com/
- Changelog: https://github.com/entirius/entirius-django-pricemanager/blob/develop/CHANGELOG.md

## Part of Entirius

This module runs inside the Entirius backend service (Volkanos) and supplies prices to the catalog and the checkout.

- Backend service: https://github.com/entirius/entirius-service-volkanos
- Docker harness: https://github.com/entirius/entirius-zeno
- Sibling modules: https://github.com/entirius/entirius-django-regional,
  https://github.com/entirius/entirius-django-checkout, https://github.com/entirius/entirius-django-pim

## Development

```shell
make install     # sync dependencies (uv)
make check       # lint + format check (ruff)
make test        # test suite (pytest + pytest-django)
```

Development and agent instructions: https://github.com/entirius/entirius-django-pricemanager/blob/develop/AGENTS.md

## License

Mozilla Public License 2.0 (MPL-2.0) — see https://github.com/entirius/entirius-django-pricemanager/blob/develop/LICENSE.
