---
title: Configuration
description: All configurable settings for the Price Manager module.
---

## Settings

| Setting | Default | Description |
|---|---|---|
| `PRICE_HISTORY_RETENTION_DAYS` | `365` | Days to retain `PriceHistory` rows. Set to `0` to keep forever. Rows older than this limit are eligible for cleanup. |
| `PRICEMANAGER_DUAL_WRITE` | `False` | Write price changes to both legacy `PriceList`/`Price` models and the new `CurrentPrice` simultaneously. Enable during migration; disable once `PRICEMANAGER_READ_FROM_CURRENT` is stable. |
| `PRICEMANAGER_READ_FROM_CURRENT` | `False` | Read prices from `CurrentPrice` instead of legacy `PriceList` snapshots. Enable after verifying dual-write is consistent. |
| `APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES` | `True` | Whether a special price with no `from_date` and no `to_date` is considered active. Set to `False` to require explicit date ranges on all special prices. |
| `PRICEMANAGER_BULK_CREATE_BATCH_SIZE` | `5000` | Batch size for `bulk_create` calls in import and migration commands. Lower this if you hit memory limits on large imports. |
| `CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING` | `10` | Thread pool size for the `manage-pricelists` country generation command. Tune based on available DB connections. |
| `ATTR_PRICE_CSV_SEPARATOR` | `";"` | Column separator for attribute price CSV imports. |
| `SUCCES_PRICELIST_TO_SAVE` | `3` | **Deprecated.** Number of `SUCCESS` status `PriceList` records the garbage collector retains before deleting older ones. Replaced by `PRICE_HISTORY_RETENTION_DAYS` in v3. |

## Feature Flag Sequence

The dual-write flags must be enabled in order:

```python
# Step 1: enable dual-write, run migration
PRICEMANAGER_DUAL_WRITE = True

# Step 2: verify consistency, then enable reads from CurrentPrice
PRICEMANAGER_READ_FROM_CURRENT = True

# Step 3: once stable, disable legacy writes (remove dual-write)
PRICEMANAGER_DUAL_WRITE = False
```

Never enable `PRICEMANAGER_READ_FROM_CURRENT` before running `migrate_to_current_price`. Reading from an empty `CurrentPrice` table will return no prices.

## Special Price Behaviour

`APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES` controls what happens when a `CurrentPrice` row has a `special_net_value` set but both `special_from_date` and `special_to_date` are `NULL`:

- `True` (default) — special price is active indefinitely. Operators can set a promotional price without specifying dates.
- `False` — dates are required. A special price with no dates is ignored.

The `is_eligible_for_special_price()` method on `CurrentPrice` applies this rule. Partial date ranges (only `from_date` set, or only `to_date` set) work as open-ended bounds regardless of this setting.
