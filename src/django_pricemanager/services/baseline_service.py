# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Baseline auto-price-from-cost: CurrentPrice = PurchaseCost.net_cost x (1+markup), rounded.

Fill-only by construction — writes go through guard_price_write with writer=BASELINE, which
only overwrites rows whose source is explicitly marked recalc_overwritable (default: none).
Opt-in per channel (Channel.baseline_enabled) and skipped entirely for tombstoned (product,
channel) pairs.
"""

import logging

from django.db import transaction

from django_pricemanager.models import Channel, CurrentPrice, PriceHistory, ProductRepresentation, TaxRate
from django_pricemanager.models.baseline_config import BaselineConfig
from django_pricemanager.models.baseline_tombstone import BaselineTombstone
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.services import price_bounds_service
from django_pricemanager.services.price_write_guard import guard_price_write, load_policy_map

logger = logging.getLogger(__name__)


def recalculate_baseline_for_product(product: ProductRepresentation, channel: Channel, user=None) -> dict:
    """Fill missing CurrentPrice rows for (product, channel) from cost x markup.

    No-op when the channel opted out, has no BaselineConfig, has no PurchaseCost for this
    product, or the pair is tombstoned. Returns {"applied": [...], "skipped": [...]}.
    Thin single-pair wrapper over `recalculate_baseline_bulk` — see there for the batched logic.
    """
    return recalculate_baseline_bulk([(product, channel)], user=user)


@transaction.atomic
def recalculate_baseline_bulk(
    pairs: list[tuple[ProductRepresentation, Channel]],
    user=None,
    countries_by_pair: dict[tuple[int, int], list] | None = None,
) -> dict:
    """Batched entrypoint over many (product, channel) pairs, deduplicated.

    Required call site for any writer using ``PurchaseCost.objects.bulk_create()`` — bulk_create
    never fires ``post_save``, so ``signals.baseline.on_purchase_cost_saved`` never sees those
    rows and a bulk cost import must trigger the recalc explicitly instead.

    Every read (tombstones, costs, configs, existing sources, bounds, policy) is prefetched once
    for the whole batch — looping the single-pair function here was ~15-20 queries per pair.

    `countries_by_pair` narrows recalculation to specific countries per (product.pk, channel.pk)
    — used by the VAT-recalc trigger, which only touched one country and shouldn't recompute
    baseline for the rest of the product's markets. Omit to resolve all of the channel's
    countries (the cost-change trigger case, where every country is potentially affected).
    """
    seen = {}
    for product, channel in pairs:
        seen.setdefault((product.pk, channel.pk), (product, channel))
    dedup = list(seen.values())
    if not dedup:
        return {"applied": [], "skipped": []}

    channel_ids = {channel.pk for _, channel in dedup}
    product_ids = {product.pk for product, _ in dedup}

    enabled_channel_ids = set(
        Channel.objects.filter(pk__in=channel_ids, baseline_enabled=True).values_list("pk", flat=True)
    )
    tombstoned = set(
        BaselineTombstone.objects.filter(channel_id__in=channel_ids, product_id__in=product_ids).values_list(
            "product_id", "channel_id"
        )
    )
    cost_by_pair = price_bounds_service.costs_by_product_channel(product_ids, channel_ids)
    config_by_channel = {c.channel_id: c for c in BaselineConfig.objects.filter(channel_id__in=channel_ids)}

    candidates = [
        (product, channel, cost_by_pair[(product.pk, channel.pk)], config_by_channel[channel.pk])
        for product, channel in dedup
        if channel.pk in enabled_channel_ids
        and (product.pk, channel.pk) not in tombstoned
        and (product.pk, channel.pk) in cost_by_pair
        and channel.pk in config_by_channel
    ]
    if not candidates:
        return {"applied": [], "skipped": []}

    from django_pricemanager.output import read_from_current

    if not read_from_current():
        logger.warning(
            "Baseline recalc ran with PRICEMANAGER_READ_FROM_CURRENT off for %d (product, channel) "
            "pair(s) — written prices will not reach consumers reading legacy PriceList.",
            len(candidates),
        )

    if countries_by_pair is None:
        channels_by_id = {channel.pk: channel for _, channel, _, _ in candidates}
        tax_class_ids_by_channel: dict[int, set] = {}
        for product, channel, _cost, _config in candidates:
            tax_class_ids_by_channel.setdefault(channel.pk, set()).add(product.tax_class_id)
        countries_by_channel = {
            channel_id: price_bounds_service.resolve_countries(channels_by_id[channel_id], tax_class_ids)
            for channel_id, tax_class_ids in tax_class_ids_by_channel.items()
        }

    rows = []  # (product, channel, cost, config, country)
    for product, channel, cost, config in candidates:
        if countries_by_pair is not None:
            countries = countries_by_pair.get((product.pk, channel.pk), [])
        else:
            countries = countries_by_channel[channel.pk].get(product.tax_class_id, [])
        for country in countries:
            rows.append((product, channel, cost, config, country))
    if not rows:
        return {"applied": [], "skipped": []}

    tax_class_ids = {product.tax_class_id for product, *_rest in rows}
    country_ids = {country.pk for *_rest, country in rows}
    tax_rates_by_class_country = {
        (t.tax_class_id, t.country_id): t
        for t in TaxRate.objects.filter(tax_class_id__in=tax_class_ids, country_id__in=country_ids)
    }

    policy_map = load_policy_map()
    bounds_by_key = price_bounds_service.get_price_bounds_bulk(
        [(product.sku, channel, country) for product, channel, _cost, _config, country in rows]
    )

    currency_ids = {cost.currency_id for _product, _channel, cost, _config in candidates}
    existing_by_key = {
        (cp.product_id, cp.channel_id, cp.country_id, cp.currency_id): cp
        for cp in CurrentPrice.objects.filter(
            product_id__in=product_ids,
            channel_id__in=channel_ids,
            currency_id__in=currency_ids,
            product_parent__isnull=True,
            customer_representation__isnull=True,
        )
    }

    from django_pricemanager.signals.dispatch import enqueue_price_sync
    from django_pricemanager.signals.killswitch import suppress_price_matrix_signals

    result = {"applied": [], "skipped": []}
    history_batch = []
    touched = set()
    to_create = []
    to_update_with_specials = []
    to_update_without_specials = []
    with suppress_price_matrix_signals():
        for product, channel, cost, config, country in rows:
            tax_rate = tax_rates_by_class_country.get((product.tax_class_id, country.pk))
            if not tax_rate:
                continue

            gross_rounded = price_bounds_service.baseline_gross_value(cost, tax_rate, config)
            net_final = tax_rate.net_price(gross_rounded)
            existing_cp = existing_by_key.get((product.pk, channel.pk, country.pk, cost.currency_id))
            existing_source = existing_cp.source if existing_cp else None

            new_values = {"net_value": net_final, "gross_value": gross_rounded, "tax_rate": tax_rate}
            # A baseline recalc must never clobber a special-price promo layered on an
            # existing row — neither on its own prior row (stored_source stays "baseline"
            # for special-only edits) nor on a foreign row it overwrites via
            # PriceSourcePolicy.recalc_overwritable (e.g. csv_import with a live promo).
            # Only a brand-new row gets its specials explicitly nulled.
            if existing_cp is None:
                new_values["special_net_value"] = None
                new_values["special_gross_value"] = None
            bounds = price_bounds_service.bounds_for(bounds_by_key, product.sku, channel.idx, country.iso2)

            decision = guard_price_write(
                existing_source=existing_source,
                new_values=new_values,
                writer=PriceSource.BASELINE,
                policy_map=policy_map,
                bounds=bounds,
            )
            if decision.status == "skipped":
                result["skipped"].append(
                    {
                        "sku": product.sku,
                        "channel": channel.idx,
                        "country": country.iso2,
                        "reason": decision.reason,
                    }
                )
                continue

            writes_specials = "special_net_value" in decision.values
            if existing_cp is not None:
                cp = existing_cp
                cp.net_value = decision.values["net_value"]
                cp.gross_value = decision.values["gross_value"]
                cp.tax_rate = tax_rate
                cp.source = decision.source
                if writes_specials:
                    cp.special_net_value = decision.values["special_net_value"]
                    cp.special_gross_value = decision.values["special_gross_value"]
                    to_update_with_specials.append(cp)
                else:
                    to_update_without_specials.append(cp)
            else:
                cp = CurrentPrice(
                    product=product,
                    channel=channel,
                    country=country,
                    currency=cost.currency,
                    customer_representation=None,
                    product_parent=None,
                    net_value=decision.values["net_value"],
                    gross_value=decision.values["gross_value"],
                    special_net_value=decision.values.get("special_net_value"),
                    special_gross_value=decision.values.get("special_gross_value"),
                    tax_rate=tax_rate,
                    source=decision.source,
                    is_only_for_verified_user=False,
                )
                to_create.append(cp)

            result["applied"].append(cp)
            touched.add((product.sku, channel.idx))
            history_batch.append(
                PriceHistory(
                    product=product,
                    channel=channel,
                    country=country,
                    currency=cost.currency,
                    gross_value=cp.gross_value,
                    net_value=cp.net_value,
                    tax_rate=tax_rate,
                    source=decision.source,
                    changed_by=user,
                )
            )

        if to_create:
            CurrentPrice.objects.bulk_create(to_create, batch_size=500)
        if to_update_with_specials:
            CurrentPrice.objects.bulk_update(
                to_update_with_specials,
                fields=[
                    "net_value",
                    "gross_value",
                    "special_net_value",
                    "special_gross_value",
                    "tax_rate",
                    "source",
                ],
                batch_size=500,
            )
        if to_update_without_specials:
            CurrentPrice.objects.bulk_update(
                to_update_without_specials,
                fields=["net_value", "gross_value", "tax_rate", "source"],
                batch_size=500,
            )

    if history_batch:
        PriceHistory.objects.bulk_create(history_batch, batch_size=500)
    for sku, channel_idx in touched:
        enqueue_price_sync(sku, channel_idx)

    return result
