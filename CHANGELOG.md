# Changelog

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
