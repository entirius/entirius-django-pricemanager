# Changelog

## [Unreleased]

- Access: the module declares its own access areas on its AppConfig and its admin views (copied from the
  entirius-django-access defaults; behaviour unchanged).

## 4.2.1 — 2026-09-30

- Fix `manage-pricelists` crashing (`SaleChannel.DoesNotExist`) when a channel has
  no source price list. It now skips such channels with a message and exits 0,
  also in `--celery-task` mode.
- Dev lock refresh for open advisories: sqlparse 0.6.0, djangorestframework 3.18.1,
  soupsieve 2.10.

## 4.2.0 — 2026-08-09

- Price write guard: per-source write policies (`PriceSourcePolicy`) with a
  precedence matrix and enforce modes, applied across admin edits, CSV import,
  price-list generation, and migration backfills.
- Price bounds: `PriceBoundsConfig` floors per (sku, channel, country) with
  clamp/reject outcomes surfaced in edit reports and `preview_price`.
- Baseline auto-pricing: `BaselineConfig` (markup + rounding) computes prices
  from purchase costs per channel, with tombstones and automatic recalc on
  cost changes and VAT recalculations.
- `stored_source` threaded through `edit_price`; `preview_price` predicts the
  guard/bounds save outcome without writing.
- Supplier-cost subscriber re-pointed to the `django_atlas` cost signal and
  projects primary-source costs into the dedicated `PurchaseCost` store
  (soft import — no-op when atlas is absent).
- Migrations 0025–0029 (source policies, bounds, baseline config, scope
  uniqueness, config base models).

## 4.1.0 — 2026-08-06

- Aggregated bundle pricing for ranged bundles.
- Fix the eligibility annotation.

## 4.0.1 — 2026-07-12

- Restore the `validate_access_to_price_list` re-export in `output.py`
  (a hard import of django-checkout lost in the 4.0.0 migration).

## 4.0.0 — 2026-07-10

- Initial public release: price lists, channels, current prices, and price
  history for the platform. `Currency` lives in django-regional — the
  duplicate table is gone.
- Migrations squashed into a single initial migration for the Entirius epoch.
