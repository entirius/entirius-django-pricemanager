---
title: Price Manager
description: Multi-country, multi-currency pricing with tax calculation and audit trail for Volkanos.
sidebar:
  label: Overview
  collapsed: true
---

django-pricemanager handles product pricing across countries, currencies, and tax regimes for Volkanos storefronts. One canonical price per product/channel/country/currency combination, recalculated whenever tax rates change, with a full audit trail of every change.

## What It Does

- Stores one live price per product/channel/country/currency in `CurrentPrice` — updated in-place, not appended
- Writes every price change to `PriceHistory` as an append-only audit log
- Calculates net ↔ gross using country-specific `TaxRate` records (per `TaxClass`)
- Supports special prices with optional `from_date`/`to_date` validity windows
- Attribute-level pricing via `CurrentPriceAttribute` M2M through table (for configurable products)
- B2B tier pricing via `CustomerRepresentation` FK on `CurrentPrice`
- Admin API (v2, 23 endpoints) for CMS price editing, channel management, and tax configuration
- CSV import pipeline for bulk price loading
- `output.py` public interface consumed by Matrix and Checkout — identical signatures to the legacy layer

## Architecture

```
CSV Import / Admin API / Tax Rate Change
  → price_edit_service (D1 FULL VATOSS flow)
    → CurrentPrice (upsert in-place)
    → PriceHistory (append)

output.py / output_bundle.py / output_custom.py
  → price_output_service
    → CurrentPrice (read, when PRICEMANAGER_READ_FROM_CURRENT=True)
    → PriceList snapshots (read, legacy fallback)
      → Matrix / Checkout
```

The `output.py` interface keeps identical function signatures regardless of which storage layer is active. Matrix and Checkout call the same functions whether the feature flag is on or off.

## Key Concepts

### CurrentPrice

One row per `(product, channel, country, currency)`. Updated in-place when prices change. Four partial `UniqueConstraint`s handle the combinations of B2B tier pricing and bundle component pricing (PostgreSQL NULL semantics require separate constraints for nullable FKs).

Stores both `net_value` and `gross_value`. Which one is authoritative depends on `Channel.calculate_direction`.

### PriceHistory

Append-only. Every write to `CurrentPrice` adds a row here with the previous values, timestamp, and `source` (who or what triggered the change). Uses `default=timezone.now` instead of `auto_now_add` so backfill can set historical timestamps.

Retention controlled by `PRICE_HISTORY_RETENTION_DAYS`. Set to `0` to keep forever.

### TaxClass and TaxRate

`TaxClass` groups products by tax regime (e.g., "Standard", "Reduced", "Zero"). `TaxRate` links a `TaxClass` to a `Country` with a specific rate. Changing a `TaxRate` triggers recalculation for all `CurrentPrice` rows in that country/tax class combination.

`ProductRepresentation` links SKUs to their `TaxClass`. This is the join point between PIM and the pricing layer.

### calculate_direction

`Channel.calculate_direction` controls whether the admin edits net or gross values. `FROM_NET_TO_GROSS` (default) means the admin enters net; the system calculates gross. `FROM_GROSS_TO_NET` means the admin enters gross; the system calculates net. The CMS must respect this per-channel setting when rendering price inputs.

### PriceSource

`CurrentPrice.source` and `PriceHistory.source` record what triggered a write:

| Value | When |
|---|---|
| `csv_import` | Bulk CSV import via management command |
| `api` | Admin API edit |
| `generation` | `manage-pricelists` country generation |
| `admin_edit` | Manual edit via admin API |
| `tax_rate_change` | Automatic recalculation after TaxRate update |
| `migration` | Data migration from legacy snapshots |
| `migration_backfill` | Historical backfill during migration |

## Who Uses It

- **Admin API** — CMS price editing panel. Authenticated with JWT + `IsAdminUser`.
- **Matrix** — reads prices via `output.py` for the product read model. No direct model imports.
- **Checkout** — reads prices via `output.py` for cart calculation. No direct model imports.
- **Omnibus** — consumes `PriceHistory` to calculate the 30-day minimum price required by EU Omnibus Directive.

## Dual-Write Transition

Two feature flags control phased migration from the legacy `PriceList`/`Price` snapshot model:

- `PRICEMANAGER_DUAL_WRITE` — writes go to both legacy and `CurrentPrice` simultaneously
- `PRICEMANAGER_READ_FROM_CURRENT` — reads come from `CurrentPrice` instead of snapshots

Both default to `False`. Run them in sequence to migrate without downtime: enable dual-write first, verify, then flip the read flag.

Legacy models (`PriceList`, `Price`, `SaleChannel`) remain in the schema during transition and are removed once all consumers have migrated.

## Pages

- [Configuration](./configuration/) — all settings and feature flags
- [Commands](./commands/) — management commands for import, migration, and maintenance
- [Changelog](./changelog/) — version history and breaking changes
