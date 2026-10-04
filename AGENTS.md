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
- Access: areas live on the AppConfig (`access_areas`, `access_route_rules`), every admin view carries
  `access_area`; a new admin route without one fails `tests/test_access_ownership.py`.
- Default: do not commit — git is the user's call.

## Architecture

```
src/django_pricemanager/
├── models/
│   ├── current_price.py         # One live price per product/channel/country/currency
│   ├── price_history.py         # Append-only audit log of all price changes
│   ├── current_price_attribute.py # M2M through for attribute pricing
│   ├── choices.py               # PriceSource enum (SOURCE_CHOICES alias)
│   ├── channel.py               # Channel (calculate_direction, calculate_countries, baseline_enabled)
│   ├── price_write_policy.py    # PriceSourcePolicy — per-source write guard config
│   ├── price_bounds.py          # PriceBoundsConfig — MAP + min_margin, global/channel/sku scope
│   ├── baseline_config.py       # BaselineConfig — per-channel markup% + rounding
│   ├── baseline_tombstone.py    # BaselineTombstone — delete exclusion marker
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
│   ├── price_edit_service.py    # D1 FULL VATOSS edit flow (edit_price, bulk_edit_prices, delete/flush)
│   ├── price_write_guard.py     # guard_price_write() — single choke-point for CurrentPrice writes
│   ├── price_bounds_service.py  # get_price_bounds(_bulk), get_markets, get_current_prices_bulk, get_purchase_costs_bulk
│   ├── baseline_service.py      # recalculate_baseline_for_product — fill-only auto-price-from-cost
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
| PriceSourcePolicy | source (unique), recalc_overwritable, enforce_mode | — (config, one row per `PriceSource`) |
| PriceBoundsConfig | map_value, min_margin_percent | FK: product (nullable), channel (nullable) — global→channel→sku, most-specific-wins; unique on (product, channel) with `nulls_distinct=False`, so only one row per scope, including the all-NULL global row |
| BaselineConfig | markup_percent, rounding | FK: channel (OneToOne) |
| BaselineTombstone | created_at | FK: product, channel; unique: (product, channel) |

### Legacy (deprecated, kept for dual-write transition)

| Entity | Key Fields | Relationships |
|--------|-----------|---------------|
| PriceList | status, source_file | FK: sale_channel, currency, country |
| Price | net_value, gross_value, special_* | FK: pricelist, product, tax_rate, product_parent; M2M: attrs |
| SaleChannel | price_source, is_only_for_verified_user | FK: channel, country, customer_representation |

### Shared

| Entity | Key Fields | Relationships |
|--------|-----------|---------------|
| Channel | idx (unique), name, calculate_direction, baseline_enabled | M2M: calculate_countries; O2O: baseline_config |
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

## Write Guard & Bounds

`services.price_write_guard.guard_price_write()` is the single choke-point every writer of
`CurrentPrice` funnels through, except **Django admin** (emergency root tool — overwrites
unconditionally) and the audit-only `flush_special_prices`/`delete_prices` paths (log
source strings outside the `PriceSource` enum, e.g. `admin_flush_special`, `admin_delete`).

**Precedence table** (who may overwrite a row currently stamped `existing_source`):

| Writer | May overwrite | Notes |
|--------|---------------|-------|
| `admin_edit`, `csv_import`, `generation`, `migration`, `api`, ... | anything | today's behavior, unchanged |
| `pricefighter` | anything except `admin_edit` | own prior rows always overwritable; revert-to-baseline: `writer=pricefighter, stored_source=baseline` |
| `baseline` | only sources marked `recalc_overwritable=True` in `PriceSourcePolicy` (default: none — fill-only), plus its own prior `baseline` rows | |
| `tax_rate_change` (VAT recalc) | anything | mandatory, never rejects — bounds enforcement is always `clamp`, not `reject`, for this writer |

Precedence is resolved by `writer`; the label persisted to `CurrentPrice.source` is
`stored_source` (defaults to `writer`) — this is how a writer can hand control to another
layer (e.g. the revert case above) without literally being that layer. The special-only
branch of `bulk_edit_prices` (items with no `value`, only `special_value`) writes with
`writer=admin_edit` but `stored_source=cp.source` — touching only the promotional special
price must not seize permanent `admin_edit` ownership of a row a `pricefighter`/`baseline`
automation owns.

**Bounds** (`services.price_bounds_service`): floor = `max(PriceBoundsConfig.map_value,
PurchaseCost.net_cost × (1+min_margin_percent) → GROSS via TaxRate)`, resolved
most-specific-wins (`sku+channel > sku > channel > global`, nullable FK scoping). Applies to
both `gross_value`/`net_value` and `special_gross_value`/`special_net_value`. Violations are
`clamp`ed or `reject`ed per `PriceSourcePolicy.enforce_mode` (default: automatons clamp,
`admin_edit` rejects). `get_price_bounds(sku, channel, country)` and the bulk variant also
return a `baseline` reference value (cost × markup, informational, independent of whether the
channel opted into auto-writing baseline prices).

Batch read services (constant query count regardless of item count — required for the
pricefighter engine): `get_price_bounds_bulk(pairs)`, `get_markets()` (distinct
channel/country/currency triples with a priced row — a market without a price does not
exist), `get_current_prices_bulk(pairs)`, `get_purchase_costs_bulk(skus, channel)`.

**Baseline auto-price-from-cost** (`services.baseline_service.recalculate_baseline_for_product`):
opt-in per channel (`Channel.baseline_enabled`), fill-only by construction (writes go through
the guard as `writer=PriceSource.BASELINE`), skipped entirely when a `BaselineTombstone`
exists for the (product, channel) pair. `CurrentPrice = PurchaseCost.net_cost × (1+markup) →
rounded (BaselineConfig.rounding: none/.99/.95/int) → GROSS`. Triggered by `post_save` on
`PurchaseCost` (catches both the atlas cost-signal stream and manual admin edits, wrapped in
`transaction.on_commit`) and by VAT rate changes (re-run after `tasks._recalculate_and_log`
for any touched (product, channel) pair on a baseline-enabled channel — the generic VAT recalc
above only does a plain tax conversion, which does not reapply markup/rounding).
`PurchaseCost.objects.bulk_create()` never fires `post_save` — a bulk cost import must call
`recalculate_baseline_bulk(pairs)` explicitly instead of relying on the signal.
`price_edit_service.delete_prices()` writes a tombstone when the channel has baseline
enabled **and the delete is not scoped to a single currency** — `BaselineTombstone` has no
currency dimension, so a currency-scoped delete must not exclude the whole (product, channel)
pair from recalc. Without the tombstone (full delete), the next cost save would resurrect the
deleted price; removing the tombstone is a deliberate admin action.

Deployment precondition: baseline/pricefighter writes require
`output.read_from_current()` to be `True` (DB-backed `PriceManagerSettings` singleton,
`PRICEMANAGER_READ_FROM_CURRENT` setting is a deprecated fallback only) — otherwise consumers
still read the legacy `PriceList` and the written price never reaches the storefront.
`recalculate_baseline_for_product` logs a warning when this is off.

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
| `signals.supplier_cost.on_supplier_cost_updated` | `django_atlas.signals.cost_updated_signal` | Write primary-source cost to the dedicated **`PurchaseCost`** store — NEVER to `CurrentPrice`. A source cost is what we PAY, not what we sell for, so it never creates a sellable price; the product stays unpriced until an operator sets a CurrentPrice (margin = CurrentPrice.net_value vs PurchaseCost.net_cost). Soft import of django_atlas — no-op when the atlas app is absent. Gates: ignored when link missing / link non-primary, skipped when product/channel/currency resolution fails, idempotent when net_cost matches. Paths emit an audit row (sources `cost_signal_received`, `cost_ignored_non_primary`, `cost_ignored_no_link`, `cost_skipped_resolution_failed`). Wrapped in `transaction.on_commit`. Business logic in `services.supplier_cost_service.apply_supplier_cost` so it can be unit-tested without registering django_atlas. |
| `signals.baseline.on_purchase_cost_saved` | `post_save(PurchaseCost)` | Triggers `baseline_service.recalculate_baseline_for_product` for the (product, channel), wrapped in `transaction.on_commit`. Listens on the module's own `PurchaseCost` save rather than the atlas signal directly — the atlas receiver above already funnels into `PurchaseCost.update_or_create()`, so this single hook catches both the atlas-driven stream and manual `PurchaseCost` edits (admin, management command) without an atlas dependency. Does NOT fire for `bulk_create()` — use `recalculate_baseline_bulk` for bulk cost imports. |

## Gotchas

- `calculate_direction` on Channel controls whether admin edits net or gross — CMS must respect this.
- PriceHistory uses `default=timezone.now` (not `auto_now_add`) so backfill can set custom timestamps.
- Two partial UniqueConstraints on CurrentPrice for general vs B2B tier prices (PostgreSQL NULL handling).
- `product_parent` in unique constraint — a product can have both regular and bundle component prices.
- Feature flags `PRICEMANAGER_DUAL_WRITE` and `PRICEMANAGER_READ_FROM_CURRENT` control phased rollout — the latter is deprecated as a runtime toggle; the live check is `output.read_from_current()` (DB `PriceManagerSettings` singleton, cached).
- Legacy `output.py` functions keep identical signatures — consumers (matrix, checkout) don't change.
- Any new `CurrentPrice` writer MUST go through `guard_price_write()` — a bare `save()`/`bulk_update()`/`update_or_create()` on `CurrentPrice` outside the guard silently breaks precedence and bounds (exception: Django admin, by design).
- Bounds floor and the baseline reference value are always **GROSS** — comparing against `net_value` gives a wrong clamp decision.
- `PriceBoundsConfig`/`BaselineConfig` scoping has no currency dimension — MAP is a raw amount in the market's currency (v1 limitation, seeded channels are single-currency).
