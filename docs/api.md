---
title: Admin API
description: Admin REST endpoints of the Price Manager module.
---

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
