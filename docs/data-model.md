---
title: Data Model
description: Entities of the Price Manager module: current prices, history, bounds, baseline and the legacy snapshot models.
---

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
