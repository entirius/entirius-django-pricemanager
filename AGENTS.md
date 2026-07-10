# AGENTS.md

Price management for the Volkanos ecommerce platform — distribution `entirius-django-pricemanager`,
Django app `django_pricemanager`. Product pricing across countries, currencies, channels, and tax
regimes. Transitioning from snapshot model (PriceList/Price) to CurrentPrice + PriceHistory
architecture.

**Tech:** Python >=3.11, Django >=5.0, DRF, Pydantic v2, drf-spectacular, Celery, PostgreSQL

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest + pytest-django) |

## Conventions

- English only: code, docs, commits, branches, PRs.
- MPL-2.0: every non-trivial source file carries the license header (pre-commit inserts it).
- Toolchain: uv + ruff + hatchling + pytest; all config in `pyproject.toml`; `uv.lock` committed.
- Git flow: `master` (production) + `develop` (integration); changes land via PR; semver tag on `master`.
- Never rename the package / Django app_label / DB table prefix `django_pricemanager` — it is a schema contract.
- Migrations are part of the public contract — never edit an already released migration.
- Default: do not commit — git is the user's call.

## Architecture

```
src/django_pricemanager/
├── models/
│   ├── current_price.py         # One live price per product/channel/country/currency
│   ├── price_history.py         # Append-only audit log of all price changes
│   ├── current_price_attribute.py # M2M through for attribute pricing
│   ├── choices.py               # SOURCE_CHOICES constant
│   ├── channel.py               # Channel (calculate_direction, calculate_countries)
│   ├── sale_channel.py          # SaleChannel (legacy, internal routing)
│   ├── pricelist.py             # PriceList (legacy snapshot container)
│   ├── price.py                 # Price + PriceAttribute (legacy)
│   ├── tax_rate.py              # TaxRate (tax_class × country)
│   ├── tax_class.py             # TaxClass
│   ├── product_representation.py # ProductRepresentation (sku + tax_class)
│   ├── attr_representation.py   # AttributeRepresentation
│   ├── customer_representation.py # CustomerRepresentation (B2B tiers)
│   └── managers/                # PriceManager, CountryAwareManager
├── schemas/
│   ├── requests/                # Pydantic request schemas
│   └── responses/               # Pydantic response schemas (from_attributes)
├── services/
│   ├── price_edit_service.py    # D1 FULL VATOSS edit flow
│   ├── channel_sync_service.py  # Sync channels from PIM
│   ├── price_output_service.py  # CurrentPrice read layer (compatibility)
│   ├── migration_service.py     # Data migration from snapshots
│   ├── pricelist_service.py     # CSV import + pricelist retrieval
│   ├── garbage_collector.py     # Legacy cleanup (deprecated)
│   └── ...
├── api/admin/
│   ├── views/                   # 3 ViewSets (price, channel, tax_class) — currencies live in django-regional since 3.1.0
│   ├── urls.py                  # v2 endpoints
│   ├── pagination.py            # AdminPageNumberPagination
│   └── permissions.py           # JWTAuthentication + IsAdminUser
├── output.py                    # Public read API for matrix/checkout
├── output_bundle.py             # Bundle pricing output
├── output_custom.py             # Attribute pricing output
├── management/commands/         # CLI commands
├── tasks.py                     # Celery tasks
├── workers.py                   # Background workers
└── settings.py                  # Module settings
```

## Data Model

### Core (v3 — CurrentPrice architecture)

| Entity | Key Fields | Relationships |
|--------|-----------|---------------|
| CurrentPrice | net_value, gross_value, special_*, source | FK: product, channel, country, currency, tax_rate, customer_representation; M2M: attrs |
| PurchaseCost | net_cost, supplier_idx | FK: product, channel, country, currency (BaseModel timestamps). Buy-side cost — independent of the sell price; written only by the supplier-cost receiver. Margin = CurrentPrice.net_value vs PurchaseCost.net_cost. |
| PriceHistory | net_value, gross_value, special_*, source, changed_by | FK: product, channel, country, currency, tax_rate |
| CurrentPriceAttribute | — | Through table: current_price × attr |

### Legacy (deprecated, kept for dual-write transition)

| Entity | Key Fields | Relationships |
|--------|-----------|---------------|
| PriceList | status, source_file | FK: sale_channel, currency, country |
| Price | net_value, gross_value, special_* | FK: pricelist, product, tax_rate, product_parent; M2M: attrs |
| SaleChannel | price_source, is_only_for_verified_user | FK: channel, country, customer_representation |

### Shared

| Entity | Key Fields | Relationships |
|--------|-----------|---------------|
| Channel | idx, name, calculate_direction | M2M: calculate_countries |
| TaxClass | idx, name | — |
| TaxRate | rate | FK: tax_class, country; unique: (tax_class, country) |
| ProductRepresentation | sku | FK: tax_class |

Note: `Currency` lives in `django_regional` (model: `django_regional.Currency`, fields: `iso3`, `name_en`, `name_pl`, `symbol`). PM models FK to it directly. The local PM Currency table was removed in migration `0021_currency_to_regional`.

## API Contract

All endpoints: `api/pricemanager/v2/admin/` with JWTAuthentication + IsAdminUser.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{ch}/prices/` | List prices (paginated, filterable) |
| GET | `/{ch}/prices/{sku}/` | Price detail per country |
| POST | `/{ch}/prices/{sku}/preview/` | Preview price change (read-only) |
| PATCH | `/{ch}/prices/{sku}/` | Save price change (propagates to all countries) |
| GET | `/{ch}/prices/{sku}/history/` | Price history per SKU |
| GET | `/channels/` | List channels |
| GET | `/channels/{idx}/` | Channel detail + stats |
| POST | `/channels/` | Create channel |
| PATCH | `/channels/{idx}/` | Update channel |
| DELETE | `/channels/{idx}/` | Delete channel |
| POST | `/channels/sync/` | Sync from PIM |
| GET | `/tax-classes/` | List tax classes |
| GET | `/tax-classes/{idx}/` | Tax class + rates |
| POST | `/tax-classes/` | Create tax class |
| PATCH | `/tax-classes/{idx}/` | Update tax class |
| DELETE | `/tax-classes/{idx}/` | Delete tax class |
| POST | `/tax-classes/{idx}/rates/` | Add tax rate |
| PATCH | `/tax-classes/{idx}/rates/{iso2}/` | Update tax rate (triggers recalc) |
| DELETE | `/tax-classes/{idx}/rates/{iso2}/` | Remove tax rate |

Currencies are exposed by `django-regional` admin API at `/api/regional/v2/admin/currencies/` (read-only since 1.7.0). The legacy PM CRUD endpoints (`/api/pricemanager/v2/admin/currencies/...`) were removed in 3.1.0.

## Testing

Postgres required. Tests read `DATABASE_URL` (default
`postgresql://postgres:postgres@localhost:5432/test` — matches the CI service). Run via `make test`.

## Commands

| Command | Purpose |
|---------|---------|
| `migrate_to_current_price` | Data migration from snapshots to CurrentPrice |
| `import-pricelist-from-csv` | Import prices from CSV |
| `import-taxclass-from-csv` | Import tax rates from CSV |
| `manage-pricelists` | Generate pricelists for countries (legacy) |
| `pricemanager-garbage-collector` | Cleanup old pricelists (deprecated) |

## Signal Receivers

| Receiver | Signal | Purpose |
|---|---|---|
| `signals.handlers.on_current_price_save` | `post_save(CurrentPrice)` | Enqueue Matrix read-model sync (no-op when killswitch denies the channel) |
| `signals.handlers.on_current_price_delete` | `post_delete(CurrentPrice)` | Same sync trigger on delete |
| `signals.supplier_cost.on_supplier_cost_updated` | `django_suppliers.signals.cost_updated_signal` | Write preferred-supplier cost to the dedicated **`PurchaseCost`** store — NEVER to `CurrentPrice`. A supplier cost is what we PAY, not what we sell for, so it never creates a sellable price; the product stays unpriced until an operator sets a CurrentPrice (margin = CurrentPrice.net_value vs PurchaseCost.net_cost). Soft import of django_suppliers — no-op when suppliers app is absent. Gates: ignored when link missing / link non-preferred, skipped when product/channel/currency resolution fails, idempotent when net_cost matches. Paths emit an audit row (sources `cost_signal_received`, `cost_ignored_non_preferred`, `cost_ignored_no_link`, `cost_skipped_resolution_failed`). Wrapped in `transaction.on_commit` per D32. Business logic in `services.supplier_cost_service.apply_supplier_cost` so it can be unit-tested without registering django_suppliers. |

## Gotchas

- `calculate_direction` on Channel controls whether admin edits net or gross — CMS must respect this.
- PriceHistory uses `default=timezone.now` (not `auto_now_add`) so backfill can set custom timestamps.
- Two partial UniqueConstraints on CurrentPrice for general vs B2B tier prices (PostgreSQL NULL handling).
- `product_parent` in unique constraint — a product can have both regular and bundle component prices.
- Feature flags `PRICEMANAGER_DUAL_WRITE` and `PRICEMANAGER_READ_FROM_CURRENT` control phased rollout.
- Legacy `output.py` functions keep identical signatures — consumers (matrix, checkout) don't change.
