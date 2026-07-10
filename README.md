# Django Price Manager

Price management for the Volkanos ecommerce platform: product prices across countries, currencies,
channels, and tax regimes. CurrentPrice + PriceHistory architecture with a legacy snapshot model
(PriceList/Price) kept for the dual-write transition.

## Quick Start

Requires Python 3.11+ and PostgreSQL 15+.

```bash
make install                     # uv sync, incl. extras
make test                        # pytest against DATABASE_URL
```

Tests read `DATABASE_URL` (default `postgresql://postgres:postgres@localhost:5432/test` —
matches the CI service).

### Other commands

```bash
make check    # ruff check + format-check
make fix      # auto-fix lint + format
```

## Usage

Add `django_pricemanager` to `INSTALLED_APPS` (requires `django_regional`). Admin API mounts at
`api/pricemanager/v2/admin/`. Optional integrations: `django_pim` (channel sync) and
`django_suppliers` (purchase costs) — both soft imports, no-ops when absent.

## Celery queues

- `pricemanager_create_pricelist`

## Details

See `AGENTS.md` for architecture, data model, API contract, and gotchas.
