# AGENTS.md

Price management for Entirius — distribution `entirius-django-pricemanager`,
Django app `django_pricemanager`. Product pricing across countries, currencies, channels, and tax
regimes. Transitioning from snapshot model (PriceList/Price) to CurrentPrice + PriceHistory
architecture.

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest + pytest-django) |

Tests need PostgreSQL: set `DATABASE_URL` (see `docs/testing.md`).

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
- No AI attribution in commits or PR descriptions.

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
│   ├── price_edit_service.py    # FULL VATOSS edit flow (edit_price, bulk_edit_prices, delete/flush)
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
│   ├── views/                   # ViewSets (price, channel, tax_class) — currencies live in django-regional since 3.1.0
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

### Signal receivers

| Receiver | Signal | Purpose |
|---|---|---|
| `signals.handlers.on_current_price_save` | `post_save(CurrentPrice)` | Enqueue Matrix read-model sync (no-op when killswitch denies the channel) |
| `signals.handlers.on_current_price_delete` | `post_delete(CurrentPrice)` | Same sync trigger on delete |
| `signals.supplier_cost.on_supplier_cost_updated` | `django_atlas.signals.cost_updated_signal` | Write primary-source cost to the dedicated **`PurchaseCost`** store — NEVER to `CurrentPrice`. A source cost is what we PAY, not what we sell for, so it never creates a sellable price; the product stays unpriced until an operator sets a CurrentPrice (margin = CurrentPrice.net_value vs PurchaseCost.net_cost). Soft import of django_atlas — no-op when the atlas app is absent. Gates: ignored when link missing / link non-primary, skipped when product/channel/currency resolution fails, idempotent when net_cost matches. Paths emit an audit row (sources `cost_signal_received`, `cost_ignored_non_primary`, `cost_ignored_no_link`, `cost_skipped_resolution_failed`). Wrapped in `transaction.on_commit`. Business logic in `services.supplier_cost_service.apply_supplier_cost` so it can be unit-tested without registering django_atlas. |
| `signals.baseline.on_purchase_cost_saved` | `post_save(PurchaseCost)` | Triggers `baseline_service.recalculate_baseline_for_product` for the (product, channel), wrapped in `transaction.on_commit`. Listens on the module's own `PurchaseCost` save rather than the atlas signal directly — the atlas receiver above already funnels into `PurchaseCost.update_or_create()`, so this single hook catches both the atlas-driven stream and manual `PurchaseCost` edits (admin, management command) without an atlas dependency. Does NOT fire for `bulk_create()` — use `recalculate_baseline_bulk` for bulk cost imports. |

| Topic | Where |
|---|---|
| Overview, key concepts, dual-write transition | `docs/index.md` |
| Data model | `docs/data-model.md`, `docs/erd.md` |
| Admin API endpoints | `docs/api.md` |
| Write guard, bounds, baseline auto-price | `docs/write-guard.md` |
| Management commands | `docs/commands.md` |
| Settings and feature flags | `docs/configuration.md` |
| Testing | `docs/testing.md` |

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
