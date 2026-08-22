# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-side services for CurrentPrice bounds, markets, costs — consumed by the write guard
(clamp/reject) and by the pricefighter engine (engine_inputs).

All bulk functions run in a constant number of queries regardless of item count — batch
callers MUST use them instead of looping the single-item variants.
"""

import logging
from decimal import Decimal

from django.db.models import Q
from django.db.models.functions import Lower

from django_pricemanager.models import Channel, CurrentPrice, ProductRepresentation, PurchaseCost, TaxRate
from django_pricemanager.models.baseline_config import BaselineConfig, apply_rounding
from django_pricemanager.models.price_bounds import PriceBoundsConfig

logger = logging.getLogger(__name__)


def bounds_for(bounds_map: dict, sku: str, channel_idx: str, country_iso2: str):
    """PriceBounds for one (sku, channel, country), looked up in a `get_price_bounds_bulk()`
    result — the single call site every writer of CurrentPrice uses to go from that map to the
    guard's `bounds=` argument, instead of repeating the map.get()/None-check inline.
    """
    from django_pricemanager.services.price_write_guard import PriceBounds

    bounds_entry = bounds_map.get((sku, channel_idx, country_iso2))
    return PriceBounds(floor=bounds_entry["floor"]) if bounds_entry else None


def resolve_countries(channel: Channel, tax_class_ids) -> dict[int, list]:
    """Countries per tax_class_id for `channel`: channel.calculate_countries if the channel
    scopes explicitly (same list for every tax_class), else every country with a TaxRate for
    that tax_class. Every write/preview path (edit_price, bulk_edit_prices, baseline recalc)
    MUST replicate this exact fallback, or bounds/baseline coverage silently diverges by SKU.
    """
    channel_countries = list(channel.calculate_countries.all())
    if channel_countries:
        return dict.fromkeys(tax_class_ids, channel_countries)

    countries_by_class: dict[int, list] = {}
    for tr in TaxRate.objects.filter(tax_class_id__in=tax_class_ids).select_related("country"):
        countries_by_class.setdefault(tr.tax_class_id, []).append(tr.country)
    return countries_by_class


def products_by_sku_lower(skus) -> dict:
    """Case-insensitive SKU -> ProductRepresentation, keyed by lowercased sku — mirrors the
    sku__iexact lookup single-item callers use, so a batch caller can't silently drop a
    differently-cased SKU (and lose bounds enforcement for it) the way a plain sku__in would."""
    return {
        p.sku.lower(): p
        for p in ProductRepresentation.objects.annotate(sku_lower=Lower("sku"))
        .filter(sku_lower__in={s.lower() for s in skus})
        .select_related("tax_class")
    }


def _max_optional(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _pick_most_specific(candidates: dict, product_id: int | None, channel_id: int | None):
    """sku+channel > sku > channel > global."""
    return (
        candidates.get((product_id, channel_id))
        or candidates.get((product_id, None))
        or candidates.get((None, channel_id))
        or candidates.get((None, None))
    )


def costs_by_product_channel(product_ids, channel_ids) -> dict[tuple[int, int], PurchaseCost]:
    """PurchaseCost keyed by (product_id, channel_id), deterministic when duplicates exist.

    v1 assumes one PurchaseCost row per (product, channel) pair (seeded channels are
    single-currency — see AGENTS.md). If more than one row exists for a pair, the most
    recently created row wins (ordered by pk) and a warning is logged — silent
    non-determinism would make bounds/baseline calculations flip between runs.
    """
    counts = {}
    result = {}
    for cost in (
        PurchaseCost.objects.filter(product_id__in=product_ids, channel_id__in=channel_ids)
        .select_related("currency")
        .order_by("pk")
    ):
        key = (cost.product_id, cost.channel_id)
        counts[key] = counts.get(key, 0) + 1
        result[key] = cost
    for (product_id, channel_id), count in counts.items():
        if count > 1:
            logger.warning(
                "Multiple PurchaseCost rows for product_id=%s channel_id=%s (%d) — using the "
                "most recently created row; bounds/baseline v1 assumes single-currency channels.",
                product_id,
                channel_id,
                count,
            )
    return result


def baseline_gross_value(
    cost: PurchaseCost | None, tax_rate: TaxRate | None, baseline_config: BaselineConfig | None
) -> Decimal | None:
    """Reference fair-value price (cost x (1+markup), rounded, GROSS).

    Shared by the read-side bounds lookup (informational, independent of whether the channel
    opted into auto-writing baseline prices) and baseline_service's actual write path — the
    formula must not drift between "what we show" and "what we write".
    """
    if cost is None or tax_rate is None or baseline_config is None:
        return None
    gross = tax_rate.gross_price(cost.net_cost * (1 + baseline_config.markup_percent))
    return apply_rounding(gross, baseline_config.rounding)


def _bounds_dict(
    bounds_row: PriceBoundsConfig | None,
    cost: PurchaseCost | None,
    tax_rate: TaxRate | None,
    baseline_config: BaselineConfig | None = None,
) -> dict:
    map_value = bounds_row.map_value if bounds_row else None
    min_margin = bounds_row.min_margin_percent if bounds_row else None

    cost_floor = None
    if min_margin is not None and cost is not None and tax_rate is not None:
        cost_floor = tax_rate.gross_price(cost.net_cost * (1 + min_margin))

    return {
        "floor": _max_optional(map_value, cost_floor),
        "ceiling": None,
        "baseline": baseline_gross_value(cost, tax_rate, baseline_config),
    }


def get_price_bounds(sku: str, channel: Channel, country) -> dict:
    """floor/ceiling/baseline for one (sku, channel, country). floor and baseline are GROSS."""
    product = ProductRepresentation.objects.select_related("tax_class").get(sku__iexact=sku)

    candidates = {
        (b.product_id, b.channel_id): b
        for b in PriceBoundsConfig.objects.filter(
            Q(product=product) | Q(product__isnull=True), Q(channel=channel) | Q(channel__isnull=True)
        )
    }
    bounds_row = _pick_most_specific(candidates, product.pk, channel.pk)
    cost = costs_by_product_channel({product.pk}, {channel.pk}).get((product.pk, channel.pk))
    tax_rate = TaxRate.objects.filter(tax_class=product.tax_class, country=country).first()
    baseline_config = BaselineConfig.objects.filter(channel=channel).first()
    return _bounds_dict(bounds_row, cost, tax_rate, baseline_config)


def get_price_bounds_bulk(pairs: list[tuple]) -> dict:
    """floor/ceiling/baseline for many (sku, channel, country) tuples — 5 queries total.

    Returns dict keyed by (sku, channel.idx, country.iso2).
    """
    skus = {sku for sku, _, _ in pairs}
    channel_ids = {channel.pk for _, channel, _ in pairs}
    country_ids = {country.pk for _, _, country in pairs}

    products_by_sku = products_by_sku_lower(skus)
    product_ids = {p.pk for p in products_by_sku.values()}
    tax_class_ids = {p.tax_class_id for p in products_by_sku.values() if p.tax_class_id}

    bounds_candidates = {}
    for b in PriceBoundsConfig.objects.filter(
        Q(product_id__in=product_ids) | Q(product__isnull=True), Q(channel_id__in=channel_ids) | Q(channel__isnull=True)
    ):
        bounds_candidates[(b.product_id, b.channel_id)] = b

    cost_by_product_channel = costs_by_product_channel(product_ids, channel_ids)
    tax_rate_by_class_country = {
        (t.tax_class_id, t.country_id): t
        for t in TaxRate.objects.filter(tax_class_id__in=tax_class_ids, country_id__in=country_ids)
    }
    baseline_config_by_channel = {c.channel_id: c for c in BaselineConfig.objects.filter(channel_id__in=channel_ids)}

    result = {}
    for sku, channel, country in pairs:
        key = (sku, channel.idx, country.iso2)
        product = products_by_sku.get(sku.lower())
        if product is None:
            result[key] = {"floor": None, "ceiling": None, "baseline": None}
            continue
        bounds_row = _pick_most_specific(bounds_candidates, product.pk, channel.pk)
        cost = cost_by_product_channel.get((product.pk, channel.pk))
        tax_rate = tax_rate_by_class_country.get((product.tax_class_id, country.pk))
        baseline_config = baseline_config_by_channel.get(channel.pk)
        result[key] = _bounds_dict(bounds_row, cost, tax_rate, baseline_config)
    return result


def get_markets() -> list[dict]:
    """Distinct (channel, country, currency) triples with at least one CurrentPrice row.

    A market without a price row does not exist — this is the enumeration seam for the
    pricefighter engine.
    """
    rows = (
        CurrentPrice.objects.filter(product_parent__isnull=True, customer_representation__isnull=True)
        .values("channel__idx", "country__iso2", "currency__iso3")
        .distinct()
        .order_by("channel__idx", "country__iso2", "currency__iso3")
    )
    return [
        {"channel_idx": row["channel__idx"], "country": row["country__iso2"], "currency": row["currency__iso3"]}
        for row in rows
    ]


def get_current_prices_bulk(pairs: list[tuple]) -> dict:
    """CurrentPrice per (sku, channel, country, currency) tuple — 1 query total.

    Returns dict keyed by (sku, channel.idx, country.iso2, currency.iso3); missing rows map to None.
    """
    skus_lower = {sku.lower() for sku, _, _, _ in pairs}
    channel_ids = {channel.pk for _, channel, _, _ in pairs}
    country_ids = {country.pk for _, _, country, _ in pairs}
    currency_ids = {currency.pk for _, _, _, currency in pairs}

    rows = {
        (cp.product.sku.lower(), cp.channel_id, cp.country_id, cp.currency_id): cp
        for cp in CurrentPrice.objects.annotate(product_sku_lower=Lower("product__sku"))
        .filter(
            product_sku_lower__in=skus_lower,
            channel_id__in=channel_ids,
            country_id__in=country_ids,
            currency_id__in=currency_ids,
            product_parent__isnull=True,
            customer_representation__isnull=True,
        )
        .select_related("product", "country", "currency", "tax_rate")
    }
    return {
        (sku, channel.idx, country.iso2, currency.iso3): rows.get((sku.lower(), channel.pk, country.pk, currency.pk))
        for sku, channel, country, currency in pairs
    }


def get_purchase_costs_bulk(skus: list[str], channel: Channel) -> dict:
    """PurchaseCost per sku within one channel — 1 query total. Missing skus map to None."""
    skus_lower = {s.lower() for s in skus}
    costs = {
        c.product.sku.lower(): c
        for c in PurchaseCost.objects.annotate(product_sku_lower=Lower("product__sku"))
        .filter(product_sku_lower__in=skus_lower, channel=channel)
        .select_related("product")
    }
    return {sku: costs.get(sku.lower()) for sku in skus}
