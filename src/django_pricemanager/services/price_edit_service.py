# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""D1 FULL VATOSS price edit flow.

Admin edits one SKU in one channel -> propagates to ALL countries (or one, with `country`).
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from django_pricemanager.models import Channel, CurrentPrice, PriceHistory, ProductRepresentation, TaxRate
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.services.price_write_guard import guard_price_write, load_policy_map

logger = logging.getLogger(__name__)

_AUTOMATED_SOURCES = frozenset({PriceSource.BASELINE, PriceSource.PRICEFIGHTER})


@dataclass
class EditPriceReport:
    """Partial-skip result of edit_price(): a source can win some countries and lose others."""

    sku: str | None = None  # canonical product.sku, resolved — never the request's raw casing
    applied: list[CurrentPrice] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # [{"country": iso2, "currency": iso3, "reason": str}]
    clamped: list[dict] = field(default_factory=list)  # subset of `applied` written below the requested value

    def __iter__(self):
        return iter(self.applied)

    def __len__(self):
        return len(self.applied)

    def __getitem__(self, idx):
        return self.applied[idx]

    def __bool__(self):
        return bool(self.applied)


@dataclass
class EditPricePrefetch:
    """Batch-computed inputs for edit_price(), built once by bulk_edit_prices for a whole
    value-branch batch — replaces the ~5 queries edit_price otherwise runs per SKU (product
    lookup, channel countries, tax rates, existing rows, currency) with a handful of queries
    for the entire batch. Keyed by lowercased sku, matching price_bounds_service's
    case-insensitive convention.
    """

    products_by_sku_lower: dict
    countries_by_sku_lower: dict
    tax_rates_by_class_country: dict  # (tax_class_id, country_id) -> TaxRate
    existing_by_product: dict  # product_id -> {country_id: {currency_id: source}}
    currency: object  # django_regional.Currency — one currency_code covers the whole bulk call


def _calculate_price_pair(value: Decimal, tax_rate: TaxRate, direction: int) -> tuple[Decimal, Decimal]:
    """Return (net, gross) based on channel direction."""
    if direction == CalculateDirectionEnum.FROM_NET_TO_GROSS:
        return value, tax_rate.gross_price(value)
    return tax_rate.net_price(value), value


def _log_price_history(cp: CurrentPrice, source: str, user=None) -> PriceHistory:
    """Create PriceHistory from a CurrentPrice."""
    return PriceHistory(
        product=cp.product,
        channel=cp.channel,
        country=cp.country,
        currency=cp.currency,
        customer_representation=cp.customer_representation,
        gross_value=cp.gross_value,
        net_value=cp.net_value,
        special_gross_value=cp.special_gross_value,
        special_net_value=cp.special_net_value,
        tax_rate=cp.tax_rate,
        source=source,
        changed_by=user,
    )


def preview_price(
    channel: Channel,
    sku: str,
    value: Decimal,
    special_value: Decimal | None = None,
    special_from: str | None = None,
    special_to: str | None = None,
) -> list[dict]:
    """Preview per-country breakdown without saving. Returns list of dicts.

    Runs the same guard/bounds decision edit_price makes on save (writer=admin_edit),
    so the preview predicts the save outcome instead of showing a clean amount that a
    later PATCH rejects or clamps. Each entry carries `would_be`
    ("applied" | "clamped" | "skipped"), the guard `reason` and the bounds `floor`;
    a clamped entry's net/gross are the clamped values that would actually be persisted.
    """
    from django_pricemanager.services import price_bounds_service

    product = ProductRepresentation.objects.get(sku__iexact=sku)
    countries = price_bounds_service.resolve_countries(channel, {product.tax_class_id}).get(product.tax_class_id, [])

    # Prefetch TaxRates (1 query instead of N)
    tax_rates_by_country = {
        tr.country_id: tr
        for tr in TaxRate.objects.filter(tax_class=product.tax_class, country__in=countries).select_related("country")
    }
    bounds_by_country = price_bounds_service.get_price_bounds_bulk([(product.sku, channel, c) for c in countries])
    policy_map = load_policy_map()

    result = []
    for country in countries:
        tax_rate = tax_rates_by_country.get(country.pk)
        if not tax_rate:
            continue
        net, gross = _calculate_price_pair(value, tax_rate, channel.calculate_direction)
        sp_net, sp_gross = (None, None)
        if special_value is not None:
            sp_net, sp_gross = _calculate_price_pair(special_value, tax_rate, channel.calculate_direction)

        bounds = price_bounds_service.bounds_for(bounds_by_country, product.sku, channel.idx, country.iso2)
        # Same decision edit_price will make on save. existing_source=None is exact for
        # writer=admin_edit — its precedence overwrites any existing source, so only the
        # bounds/enforce-mode dimension can skip or clamp.
        decision = guard_price_write(
            existing_source=None,
            new_values={
                "net_value": net,
                "gross_value": gross,
                "special_net_value": sp_net,
                "special_gross_value": sp_gross,
                "tax_rate": tax_rate,
            },
            writer=PriceSource.ADMIN_EDIT,
            policy_map=policy_map,
            bounds=bounds,
        )
        # For applied/clamped show what WILL be persisted; a skipped write persists nothing,
        # so show the requested amounts alongside the rejection reason.
        shown = decision.values or {
            "net_value": net,
            "gross_value": gross,
            "special_net_value": sp_net,
            "special_gross_value": sp_gross,
        }
        result.append(
            {
                "country": country.iso2,
                "tax_rate": str(tax_rate.rate),
                "net": str(shown["net_value"]),
                "gross": str(shown["gross_value"]),
                "special_net": str(shown["special_net_value"]) if shown.get("special_net_value") is not None else None,
                "special_gross": str(shown["special_gross_value"])
                if shown.get("special_gross_value") is not None
                else None,
                "special_from_date": special_from,
                "special_to_date": special_to,
                "would_be": decision.status,
                "reason": decision.reason,
                "floor": str(bounds.floor) if bounds is not None and bounds.floor is not None else None,
            }
        )
    return result


@transaction.atomic
def edit_price(
    channel: Channel,
    sku: str,
    value: Decimal,
    currency_code: str | None = None,
    special_value: Decimal | None = None,
    special_from=None,
    special_to=None,
    user=None,
    source: str = PriceSource.ADMIN_EDIT,
    country=None,
    policy_map: dict | None = None,
    bounds_by_country: dict | None = None,
    prefetch: EditPricePrefetch | None = None,
    stored_source: str | None = None,
) -> EditPriceReport:
    """Edit price for one SKU. Returns an EditPriceReport (applied + skipped, partial-skip contract).

    When currency_code is provided, only that currency is updated.
    When currency_code is omitted, all existing currencies are updated (bulk recalc use case).
    When `country` is provided, only that market is written (pricefighter apply scope).
    When omitted, propagates to all countries in the channel (legacy behavior).
    `source` sets the writer identity for guard_price_write precedence.
    `stored_source`, if given, overrides the label written to CurrentPrice/PriceHistory instead
    of `source` (e.g. a pricefighter revert-to-baseline apply: writer=pricefighter so it may
    overwrite its own prior row, but the label written back is `source=baseline`).
    `policy_map`/`bounds_by_country` let a batch caller (bulk_edit_prices) prefetch both once
    for the whole operation instead of every SKU reloading them — pass a dict keyed the same
    way as `load_policy_map()`/`price_bounds_service.get_price_bounds_bulk()` return.
    `prefetch` (EditPricePrefetch) additionally short-circuits the product/countries/tax-rates/
    existing-rows/currency resolution below — a batch caller builds it once per whole batch
    instead of this function re-querying all five per SKU. Falls back to the normal per-call
    resolution for any SKU missing from the prefetch (e.g. just auto-created this same batch).
    """
    product = prefetch.products_by_sku_lower.get(sku.lower()) if prefetch else None
    used_prefetch = product is not None
    if product is None:
        try:
            product = ProductRepresentation.objects.get(sku__iexact=sku)
        except ProductRepresentation.DoesNotExist:
            if source in _AUTOMATED_SOURCES:
                raise ValueError(
                    f"Unknown SKU={sku} — refusing to auto-create ProductRepresentation for source={source}"
                ) from None
            from django_pricemanager.models import TaxClass

            default_tax_class = TaxClass.objects.first()
            if not default_tax_class:
                raise ValueError("No TaxClass exists. Create one before setting prices.")
            product = ProductRepresentation.objects.create(sku=sku, tax_class=default_tax_class)
            logger.info("Auto-created ProductRepresentation for SKU=%s with tax_class=%s", sku, default_tax_class.idx)

    from django_pricemanager.services import price_bounds_service

    if country is not None:
        countries = [country]
    elif used_prefetch and sku.lower() in prefetch.countries_by_sku_lower:
        countries = prefetch.countries_by_sku_lower[sku.lower()]
    else:
        countries = price_bounds_service.resolve_countries(channel, {product.tax_class_id}).get(
            product.tax_class_id, []
        )

    # Prefetch: bounds per country (constant queries regardless of country count), unless the
    # caller already prefetched them for the whole batch (bulk_edit_prices).
    if bounds_by_country is None:
        bounds_by_country = price_bounds_service.get_price_bounds_bulk([(product.sku, channel, c) for c in countries])

    if used_prefetch:
        # Prefetch: TaxRates for this product's tax class, sliced from the whole batch's map.
        tax_rates_by_country = {
            c.pk: prefetch.tax_rates_by_class_country[(product.tax_class_id, c.pk)]
            for c in countries
            if (product.tax_class_id, c.pk) in prefetch.tax_rates_by_class_country
        }
        # Prefetch: existing currency_ids + source per country, sliced from the whole batch's map.
        existing_rows = prefetch.existing_by_product.get(product.pk, {})
    else:
        # Prefetch: TaxRates for this product's tax class (1 query instead of N)
        tax_rates_by_country = {
            tr.country_id: tr
            for tr in TaxRate.objects.filter(tax_class=product.tax_class, country__in=countries).select_related(
                "country"
            )
        }
        # Prefetch: existing currency_ids + source per country (1 query instead of N)
        existing_rows = {}
        for row in CurrentPrice.objects.filter(
            product=product,
            channel=channel,
            product_parent__isnull=True,
            customer_representation__isnull=True,
        ).values("country_id", "currency_id", "source"):
            existing_rows.setdefault(row["country_id"], {})[row["currency_id"]] = row["source"]

    # Fallback currency: explicit currency_code > channel's existing > empty
    from django_regional.models import Currency

    if prefetch is not None and currency_code:
        fallback_currency_ids = [prefetch.currency.pk]
    elif currency_code:
        try:
            fallback_currency_ids = [Currency.objects.get(iso3__iexact=currency_code).pk]
        except Currency.DoesNotExist:
            raise ValueError(f"Currency '{currency_code}' not found")
    else:
        fallback_currency_ids = list(
            CurrentPrice.objects.filter(channel=channel).values_list("currency_id", flat=True).distinct()[:1]
        )

    # Prefetch Currency instances once — update_or_create() below is given currency_id=int, so the
    # returned CurrentPrice has no cached `currency` FK; the caller (partial_update) serializes
    # cp.currency.iso3 per row, which would otherwise re-query per country.
    all_currency_ids = set(fallback_currency_ids)
    for row in existing_rows.values():
        all_currency_ids.update(row.keys())
    if prefetch is not None:
        currency_by_id = {prefetch.currency.pk: prefetch.currency}
        missing_currency_ids = all_currency_ids - currency_by_id.keys()
        if missing_currency_ids:
            currency_by_id.update({cur.pk: cur for cur in Currency.objects.filter(pk__in=missing_currency_ids)})
    else:
        currency_by_id = {cur.pk: cur for cur in Currency.objects.filter(pk__in=all_currency_ids)}

    from django_pricemanager.signals.dispatch import enqueue_price_sync
    from django_pricemanager.signals.killswitch import suppress_price_matrix_signals

    report = EditPriceReport(sku=product.sku)
    history_batch = []
    if policy_map is None:
        policy_map = load_policy_map()

    # Suppress per-save signals — enqueue once after the loop
    with suppress_price_matrix_signals():
        for c in countries:
            tax_rate = tax_rates_by_country.get(c.pk)
            if not tax_rate:
                logger.warning("No TaxRate for %s/%s — skipping", product.tax_class.idx, c.iso2)
                continue

            net, gross = _calculate_price_pair(value, tax_rate, channel.calculate_direction)
            sp_net, sp_gross = (None, None)
            if special_value is not None:
                sp_net, sp_gross = _calculate_price_pair(special_value, tax_rate, channel.calculate_direction)

            if currency_code:
                currency_ids = fallback_currency_ids
            else:
                currency_ids = list(existing_rows.get(c.pk, {}).keys()) or fallback_currency_ids

            bounds = price_bounds_service.bounds_for(bounds_by_country, product.sku, channel.idx, c.iso2)

            for cid in currency_ids:
                existing_source = existing_rows.get(c.pk, {}).get(cid)
                new_values = {
                    "net_value": net,
                    "gross_value": gross,
                    "special_net_value": sp_net,
                    "special_gross_value": sp_gross,
                    "tax_rate": tax_rate,
                }
                decision = guard_price_write(
                    existing_source=existing_source,
                    new_values=new_values,
                    writer=source,
                    stored_source=stored_source,
                    policy_map=policy_map,
                    bounds=bounds,
                )
                if decision.status == "skipped":
                    report.skipped.append({"country": c.iso2, "currency_id": cid, "reason": decision.reason})
                    continue

                cp, _ = CurrentPrice.objects.update_or_create(
                    product=product,
                    channel=channel,
                    country=c,
                    currency_id=cid,
                    customer_representation=None,
                    product_parent=None,
                    defaults={
                        "net_value": decision.values["net_value"],
                        "gross_value": decision.values["gross_value"],
                        "special_net_value": decision.values.get("special_net_value"),
                        "special_gross_value": decision.values.get("special_gross_value"),
                        "special_from_date": special_from,
                        "special_to_date": special_to,
                        "tax_rate": tax_rate,
                        "source": decision.source,
                        "is_only_for_verified_user": False,
                    },
                )
                # Cache FKs we already hold in memory — update_or_create()'s "existing row" path
                # fetches via a plain .get() with no select_related, so callers serializing
                # cp.currency.iso3/cp.country.iso2/cp.tax_rate.rate would otherwise re-query per
                # row, and _log_price_history() below (cp.product/cp.channel) would too —
                # the common bulk-edit case (updating already-priced SKUs) hits this path for
                # every row.
                cp.product = product
                cp.channel = channel
                cp.country = c
                cp.tax_rate = tax_rate
                if cid in currency_by_id:
                    cp.currency = currency_by_id[cid]
                report.applied.append(cp)
                if decision.status == "clamped":
                    report.clamped.append({"country": c.iso2, "currency_id": cid, "reason": decision.reason})
                    logger.info(
                        "Clamped price for %s in %s/%s: %s",
                        sku,
                        channel.idx,
                        c.iso2,
                        decision.reason,
                    )
                history_batch.append(_log_price_history(cp, decision.source, user))

    if history_batch:
        PriceHistory.objects.bulk_create(history_batch, batch_size=500)

    # Single enqueue after all countries updated
    if report.applied:
        enqueue_price_sync(sku, channel.idx)

    logger.info(
        "Edited price for %s in %s: %d applied, %d skipped",
        sku,
        channel.idx,
        len(report.applied),
        len(report.skipped),
    )
    return report


def _prefetch_value_branch_context(channel: Channel, skus: list[str], currency_code: str) -> EditPricePrefetch:
    """One-shot batch prefetch feeding edit_price()'s `prefetch` param for bulk_edit_prices'
    value branch — without it, edit_price re-runs ~5 queries (product, countries, tax rates,
    existing rows, currency) for every SKU in the batch.

    `products_by_sku_lower` on the returned prefetch is also the single normalization point
    every downstream bounds lookup (edit_price, bulk_edit_prices) keys against — mixing raw and
    canonical SKU casing across builder/lookup sites is exactly what let a differently-cased SKU
    silently miss its bounds entry (floor=None) in the special-only bulk-edit branch.

    Raises ValueError (not Currency.DoesNotExist) on an unknown currency_code — same per-item
    error contract as `_prefetch_special_only_context`.
    """
    from django_regional.models import Currency

    from django_pricemanager.services import price_bounds_service
    from django_pricemanager.services.price_bounds_service import products_by_sku_lower

    try:
        currency = Currency.objects.get(iso3__iexact=currency_code)
    except Currency.DoesNotExist:
        raise ValueError(f"Currency '{currency_code}' not found") from None

    products = products_by_sku_lower(skus)

    tax_class_ids = {p.tax_class_id for p in products.values()}
    countries_by_tax_class = price_bounds_service.resolve_countries(channel, tax_class_ids)
    countries_by_sku_lower = {
        sku_lower: countries_by_tax_class.get(product.tax_class_id, []) for sku_lower, product in products.items()
    }

    all_country_ids = {c.pk for countries in countries_by_sku_lower.values() for c in countries}
    tax_rates_by_class_country = {
        (t.tax_class_id, t.country_id): t
        for t in TaxRate.objects.filter(tax_class_id__in=tax_class_ids, country_id__in=all_country_ids).select_related(
            "country"
        )
    }

    product_ids = [p.pk for p in products.values()]
    existing_by_product: dict = {}
    for row in CurrentPrice.objects.filter(
        product_id__in=product_ids,
        channel=channel,
        product_parent__isnull=True,
        customer_representation__isnull=True,
    ).values("product_id", "country_id", "currency_id", "source"):
        existing_by_product.setdefault(row["product_id"], {}).setdefault(row["country_id"], {})[row["currency_id"]] = (
            row["source"]
        )

    return EditPricePrefetch(
        products_by_sku_lower=products,
        countries_by_sku_lower=countries_by_sku_lower,
        tax_rates_by_class_country=tax_rates_by_class_country,
        existing_by_product=existing_by_product,
        currency=currency,
    )


def _prefetch_special_only_context(channel: Channel, skus: list[str], currency_code: str) -> tuple[dict, dict]:
    """Prefetch existing CurrentPrice rows (grouped by sku) + bounds once for the whole
    special-only batch, instead of every SKU re-fetching both inside the per-item loop.

    Raises ValueError (not Currency.DoesNotExist) on an unknown currency_code — this runs once
    before the per-item try/except loop in bulk_edit_prices, so the caller must be able to catch
    it and route to per-item errors instead of 500ing the whole batch.
    """
    from django.db.models.functions import Lower
    from django_regional.models import Currency

    from django_pricemanager.services import price_bounds_service

    try:
        currency = Currency.objects.get(iso3__iexact=currency_code)
    except Currency.DoesNotExist:
        raise ValueError(f"Currency '{currency_code}' not found") from None

    skus_lower = {s.lower() for s in skus}
    prices = list(
        CurrentPrice.objects.annotate(product_sku_lower=Lower("product__sku"))
        .filter(
            product_sku_lower__in=skus_lower,
            channel=channel,
            currency=currency,
            product_parent__isnull=True,
            customer_representation__isnull=True,
        )
        .select_related("country", "product", "tax_rate")
    )
    prices_by_sku_lower: dict[str, list] = {}
    for cp in prices:
        prices_by_sku_lower.setdefault(cp.product.sku.lower(), []).append(cp)
    bounds_by_country = price_bounds_service.get_price_bounds_bulk(
        [(cp.product.sku, channel, cp.country) for cp in prices]
    )
    return prices_by_sku_lower, bounds_by_country


def bulk_edit_prices(channel: Channel, items: list[dict], currency_code: str, user=None) -> dict:
    """Bulk-edit prices for multiple SKUs. Each SKU uses savepoint for partial success."""
    from django_pricemanager.signals.dispatch import enqueue_price_sync
    from django_pricemanager.signals.killswitch import suppress_price_matrix_signals

    updated = 0
    changes_logged = 0
    errors = []
    skipped = []
    clamped = []
    synced_skus = []
    policy_map = load_policy_map()

    # Prefetch bounds + product/countries/tax-rates/existing-rows/currency once for the whole
    # batch (the item_value branch below otherwise has each SKU reload all of that from scratch
    # inside edit_price — see AGENTS.md write guard section). Covers both the explicit-channel-
    # countries case and the fallback (empty calculate_countries, resolved per-SKU via tax_class).
    # An unknown currency_code is caught here and re-raised per item below, same contract as the
    # special-only branch.
    skus_with_value = [item["sku"] for item in items if item.get("value") is not None]
    bulk_bounds = None
    value_prefetch = None
    value_prefetch_error = None
    if skus_with_value:
        try:
            value_prefetch = _prefetch_value_branch_context(channel, skus_with_value, currency_code)
        except ValueError as exc:
            value_prefetch_error = str(exc)
        if value_prefetch is not None:
            # Bounds pairs are derived from the prefetch's own product/country resolution
            # (never re-resolved) — resolving countries twice for the same batch is exactly
            # the kind of drift that let a differently-cased SKU miss its bounds entry.
            from django_pricemanager.services import price_bounds_service

            value_pairs = [
                (product.sku, channel, c)
                for sku_lower, product in value_prefetch.products_by_sku_lower.items()
                for c in value_prefetch.countries_by_sku_lower.get(sku_lower, [])
            ]
            if value_pairs:
                bulk_bounds = price_bounds_service.get_price_bounds_bulk(value_pairs)

    # Same prefetch for the special-only branch (item has no `value`) — one Currency lookup,
    # one CurrentPrice fetch, one bounds batch for the whole set of SKUs instead of per-SKU.
    # An unknown currency_code affects every special-only item identically, so it's caught here
    # (not left to blow up the whole request) and re-raised per item below — same per-item
    # error contract as a bad value in the `value` branch.
    special_only_skus = [item["sku"] for item in items if item.get("value") is None]
    special_context = None
    special_context_error = None
    if special_only_skus:
        try:
            special_context = _prefetch_special_only_context(channel, special_only_skus, currency_code)
        except ValueError as exc:
            special_context_error = str(exc)

    with suppress_price_matrix_signals():
        for item in items:
            sku = item["sku"]
            sid = transaction.savepoint()
            try:
                tax_class_idx = item.get("tax_class_idx")
                if tax_class_idx:
                    from django_pricemanager.models import TaxClass

                    product_qs = ProductRepresentation.objects.filter(sku__iexact=sku)
                    if not product_qs.exists():
                        tax_class = TaxClass.objects.get(idx=tax_class_idx)
                        ProductRepresentation.objects.create(sku=sku, tax_class=tax_class)

                item_value = item.get("value")

                if item_value is not None:
                    if value_prefetch_error:
                        raise ValueError(value_prefetch_error)
                    edit_report = edit_price(
                        channel=channel,
                        sku=sku,
                        value=Decimal(str(item_value)),
                        currency_code=currency_code,
                        special_value=Decimal(str(item["special_value"]))
                        if item.get("special_value") is not None
                        else None,
                        special_from=item.get("special_from_date"),
                        special_to=item.get("special_to_date"),
                        user=user,
                        policy_map=policy_map,
                        bounds_by_country=bulk_bounds,
                        prefetch=value_prefetch,
                    )
                    result = edit_report.applied
                    if not result and edit_report.skipped:
                        reasons = "; ".join(f"{s['country']}: {s['reason']}" for s in edit_report.skipped)
                        raise ValueError(f"Rejected by write guard: {reasons}")
                    # Partial skip (some countries applied, some rejected/clamped): the item
                    # still counts as updated below, but the rejected/clamped countries must
                    # not vanish from the bulk response — surface them per-SKU like the single
                    # partial_update PATCH already does via PricePatchResponse.
                    skipped.extend({"sku": edit_report.sku, **s} for s in edit_report.skipped)
                    clamped.extend({"sku": edit_report.sku, **c} for c in edit_report.clamped)
                else:
                    if special_context_error:
                        raise ValueError(special_context_error)
                    from django_pricemanager.services import price_bounds_service

                    prices_by_sku_lower, bounds_by_country = special_context
                    prices = prices_by_sku_lower.get(sku.lower(), [])
                    sp_val = Decimal(str(item["special_value"])) if item.get("special_value") is not None else None
                    history_batch = []
                    result = []
                    item_skipped = []
                    item_clamped = []
                    for cp in prices:
                        if sp_val is not None:
                            sp_net, sp_gross = _calculate_price_pair(sp_val, cp.tax_rate, channel.calculate_direction)
                        else:
                            sp_net, sp_gross = None, None
                        new_values = {
                            "special_net_value": sp_net,
                            "special_gross_value": sp_gross,
                            "tax_rate": cp.tax_rate,
                        }
                        # Bounds are keyed by the resolved product's canonical sku (see
                        # _prefetch_value_branch_context / _prefetch_special_only_context) — look
                        # up with cp.product.sku, never the request's raw `sku`, or a differently-
                        # cased request silently misses its bounds entry (floor=None, MAP bypassed).
                        bounds = price_bounds_service.bounds_for(
                            bounds_by_country, cp.product.sku, channel.idx, cp.country.iso2
                        )
                        # stored_source=cp.source: touching only the special price must not seize
                        # permanent admin_edit ownership of a row a pricefighter/baseline automation owns.
                        decision = guard_price_write(
                            existing_source=cp.source,
                            new_values=new_values,
                            writer=PriceSource.ADMIN_EDIT,
                            stored_source=cp.source,
                            policy_map=policy_map,
                            bounds=bounds,
                        )
                        if decision.status == "skipped":
                            item_skipped.append(
                                {
                                    "sku": cp.product.sku,
                                    "country": cp.country.iso2,
                                    "currency_id": cp.currency_id,
                                    "reason": decision.reason,
                                }
                            )
                            continue
                        cp.special_net_value = decision.values.get("special_net_value")
                        cp.special_gross_value = decision.values.get("special_gross_value")
                        cp.special_from_date = item.get("special_from_date")
                        cp.special_to_date = item.get("special_to_date")
                        cp.source = decision.source
                        result.append(cp)
                        if decision.status == "clamped":
                            item_clamped.append(
                                {
                                    "sku": cp.product.sku,
                                    "country": cp.country.iso2,
                                    "currency_id": cp.currency_id,
                                    "reason": decision.reason,
                                }
                            )
                        history_batch.append(_log_price_history(cp, decision.source, user))
                    if result:
                        CurrentPrice.objects.bulk_update(
                            result,
                            fields=[
                                "special_net_value",
                                "special_gross_value",
                                "special_from_date",
                                "special_to_date",
                                "source",
                            ],
                            batch_size=500,
                        )
                    if history_batch:
                        PriceHistory.objects.bulk_create(history_batch, batch_size=500)
                    if not result and item_skipped:
                        reasons = "; ".join(f"{s['country']}: {s['reason']}" for s in item_skipped)
                        raise ValueError(f"Rejected by write guard: {reasons}")
                    # Partial skip (some countries applied, some rejected/clamped): surface every
                    # rejected/clamped country on the bulk response, mirroring the `value` branch —
                    # this is the plan's "partial-skip is a contract, not optional" requirement.
                    skipped.extend(item_skipped)
                    clamped.extend(item_clamped)
                transaction.savepoint_commit(sid)
                updated += 1
                changes_logged += len(result)
                synced_skus.append(sku)
            except (ValueError, ProductRepresentation.DoesNotExist) as exc:
                transaction.savepoint_rollback(sid)
                errors.append({"sku": sku, "error": str(exc)})
                logger.warning("Bulk edit failed for SKU=%s: %s", sku, exc)
            except Exception as exc:
                transaction.savepoint_rollback(sid)
                import uuid

                error_id = uuid.uuid4().hex[:8]
                logger.exception("Bulk edit unexpected error for SKU=%s [%s]", sku, error_id)
                errors.append({"sku": sku, "error": f"Internal error [{error_id}]"})

    # Enqueue successfully edited SKUs for matrix sync (outside suppress block)
    for sku in synced_skus:
        enqueue_price_sync(sku, channel.idx)

    return {
        "updated": updated,
        "changes_logged": changes_logged,
        "errors": errors,
        "skipped": skipped,
        "clamped": clamped,
    }


@transaction.atomic
def flush_special_prices(channel: Channel, sku: str, currency_code: str | None = None, user=None) -> int:
    """Clear special price fields for a SKU in a channel. Optionally scoped to one currency.

    Admin-only emergency action — intentionally outside guard_price_write (see module AGENTS.md).
    """
    filters = {
        "channel": channel,
        "product__sku__iexact": sku,
        "product_parent__isnull": True,
        "customer_representation__isnull": True,
    }
    if currency_code:
        filters["currency__iso3__iexact"] = currency_code
    prices = list(CurrentPrice.objects.filter(**filters).select_related("product", "country", "currency", "tax_rate"))
    if not prices:
        return 0

    # Log history before clearing
    history_batch = [_log_price_history(cp, "admin_flush_special", user) for cp in prices]
    PriceHistory.objects.bulk_create(history_batch, batch_size=500)

    # Bulk update — single query
    CurrentPrice.objects.filter(pk__in=[cp.pk for cp in prices]).update(
        special_net_value=None,
        special_gross_value=None,
        special_from_date=None,
        special_to_date=None,
    )
    logger.info("Flushed special prices for %s in %s: %d rows", sku, channel.idx, len(prices))
    # Manual enqueue — .update() doesn't fire Django signals
    from django_pricemanager.signals.dispatch import enqueue_price_sync

    enqueue_price_sync(sku, channel.idx)
    return len(prices)


@transaction.atomic
def delete_prices(channel: Channel, sku: str, currency_code: str | None = None, user=None) -> int:
    """Delete CurrentPrice rows for a SKU in a channel. Optionally scoped to one currency.

    Admin-only emergency action — intentionally outside guard_price_write (see module AGENTS.md).
    """
    filters = {
        "channel": channel,
        "product__sku__iexact": sku,
        "product_parent__isnull": True,
        "customer_representation__isnull": True,
    }
    if currency_code:
        filters["currency__iso3__iexact"] = currency_code
    prices = list(CurrentPrice.objects.filter(**filters).select_related("product", "country", "currency", "tax_rate"))
    if not prices:
        return 0

    # Log history before deletion
    history_batch = [_log_price_history(cp, "admin_delete", user) for cp in prices]
    PriceHistory.objects.bulk_create(history_batch, batch_size=500)

    CurrentPrice.objects.filter(pk__in=[cp.pk for cp in prices]).delete()
    logger.info("Deleted prices for %s in %s: %d rows", sku, channel.idx, len(prices))

    if channel.baseline_enabled and not currency_code:
        # Scoped to one currency, BaselineTombstone has no currency dimension — a partial
        # delete must not exclude the whole (product, channel) pair from baseline recalc.
        from django_pricemanager.models import BaselineTombstone

        BaselineTombstone.objects.get_or_create(product=prices[0].product, channel=channel)

    # Manual enqueue — queryset .delete() fires per-row signals but we want one enqueue
    from django_pricemanager.signals.dispatch import enqueue_price_sync

    enqueue_price_sync(sku, channel.idx)
    return len(prices)
