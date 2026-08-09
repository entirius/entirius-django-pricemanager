---
title: Commands
description: Management commands for the Price Manager module.
---

## migrate_to_current_price

Migrates data from legacy `PriceList`/`Price` snapshots to the `CurrentPrice` + `PriceHistory` architecture. Run once during the v3 upgrade. Safe to re-run — uses `bulk_create` with `update_conflicts`.

```bash
# Populate CurrentPrice from the latest READY snapshots (default)
python manage.py migrate_to_current_price

# Populate CurrentPrice and backfill 90 days of PriceHistory
python manage.py migrate_to_current_price --backfill-days=90

# Migrate only the attribute pricing M2M (CurrentPriceAttribute rows)
python manage.py migrate_to_current_price --attrs-only

# Compare CurrentPrice values against legacy snapshots — no writes
python manage.py migrate_to_current_price --verify-only

# Log what would happen without writing to the database
python manage.py migrate_to_current_price --dry-run

# Override batch size (default: PRICEMANAGER_BULK_CREATE_BATCH_SIZE)
python manage.py migrate_to_current_price --batch-size=1000
```

| Argument | Default | Description |
|---|---|---|
| `--backfill-days` | `0` | Number of days of historical `PriceHistory` to backfill from snapshots. `0` skips backfill. |
| `--attrs-only` | `False` | Migrate only `PriceAttribute` → `CurrentPriceAttribute` M2M rows. Skip `CurrentPrice` population. |
| `--verify-only` | `False` | Compare `CurrentPrice` values against latest snapshots. Prints mismatches, exits non-zero on any. |
| `--dry-run` | `False` | Log all actions without writing to the database. |
| `--batch-size` | `5000` | Batch size for `bulk_create` calls. |

Run `--verify-only` after migration to confirm consistency before enabling `PRICEMANAGER_READ_FROM_CURRENT`.

---

## import-pricelist-from-csv

Imports product prices from a CSV file into the legacy `PriceList`/`Price` models. When `PRICEMANAGER_DUAL_WRITE` is enabled, writes also propagate to `CurrentPrice`.

```bash
python manage.py import-pricelist-from-csv <sale_channel_idx> <file_path> [--currency_code CODE] [-t]
```

| Argument | Required | Description |
|---|---|---|
| `sale_channel_idx` | Yes | `SaleChannel.idx` to import prices for. |
| `file_path` | Yes | Path to the CSV file, e.g. `pricelists/pricelist.csv`. |
| `--currency_code` | No | Currency code for the import. Defaults to `PLN`. |
| `-t` / `--celery-task` | No | Queue the import as a Celery task instead of running synchronously. |

Example:

```bash
python manage.py import-pricelist-from-csv my-channel pricelists/products.csv --currency_code EUR
```

---

## import-taxclass-from-csv

Imports tax rates from a CSV file for the specified tax class. Always runs as a Celery task.

```bash
python manage.py import-taxclass-from-csv <tax_class_name> [--file_path PATH]
```

| Argument | Required | Description |
|---|---|---|
| `tax_class_name` | Yes | Name of the `TaxClass` to import rates for. |
| `--file_path` | No | Path to the CSV file. Defaults to `{MEDIA_ROOT}/pricelists/tax_class.csv`. |

Example:

```bash
python manage.py import-taxclass-from-csv "Standard" --file_path /data/tax_rates.csv
```

---

## manage-pricelists

Generates `PriceList` records for all countries associated with each channel. Uses a thread pool (`CREATE_PRICELIST_MAX_WORKERS_MULTITHREADING`) to parallelize country generation. Legacy command — applies to the snapshot model.

```bash
python manage.py manage-pricelists [--channel_idx IDX] [--price_source SOURCE] [-t]
```

| Argument | Required | Description |
|---|---|---|
| `--channel_idx` | No | Limit generation to one channel. Omit to process all channels. |
| `--price_source` | No | Starting `PriceList` source type: `api` or `csv`. Defaults to `csv`. |
| `-t` / `--celery-task` | No | Queue each channel as a separate Celery task. |

Example:

```bash
# Generate for a single channel via Celery
python manage.py manage-pricelists --channel_idx my-shop -t
```

---

## pricemanager-garbage-collector

**Deprecated.** Deletes old `PriceList` records based on status retention counts (`SUCCES_PRICELIST_TO_SAVE`, `ERROR_PRICELIST_TO_SAVE`). Replaced by `PRICE_HISTORY_RETENTION_DAYS` in v3, which handles `PriceHistory` retention instead.

Do not schedule this command on new installations. Existing deployments can keep it running until the snapshot model is fully retired.
