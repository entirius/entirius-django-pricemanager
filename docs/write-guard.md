---
title: Write Guard and Bounds
description: Who may overwrite a current price, price bounds and the baseline auto-price.
---

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
