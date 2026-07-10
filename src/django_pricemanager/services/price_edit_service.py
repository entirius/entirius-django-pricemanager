# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""D1 FULL VATOSS price edit flow.

Admin edits one SKU in one channel -> propagates to ALL countries.
"""

import logging
from decimal import Decimal

from django.db import transaction

from django_pricemanager.models import Channel, CurrentPrice, PriceHistory, ProductRepresentation, TaxRate
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.models.choices import PriceSource

logger = logging.getLogger(__name__)


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
    """Preview per-country breakdown without saving. Returns list of dicts."""
    product = ProductRepresentation.objects.get(sku__iexact=sku)
    countries = channel.calculate_countries.all()
    if not countries.exists():
        countries = TaxRate.objects.filter(tax_class=product.tax_class).values_list("country", flat=True)
        from django_regional.models import Country

        countries = Country.objects.filter(pk__in=countries)

    # Prefetch TaxRates (1 query instead of N)
    tax_rates_by_country = {
        tr.country_id: tr
        for tr in TaxRate.objects.filter(tax_class=product.tax_class, country__in=countries).select_related("country")
    }

    result = []
    for country in countries:
        tax_rate = tax_rates_by_country.get(country.pk)
        if not tax_rate:
            continue
        net, gross = _calculate_price_pair(value, tax_rate, channel.calculate_direction)
        entry = {"country": country.iso2, "tax_rate": str(tax_rate.rate), "net": str(net), "gross": str(gross)}
        if special_value is not None:
            sp_net, sp_gross = _calculate_price_pair(special_value, tax_rate, channel.calculate_direction)
            entry.update({"special_net": str(sp_net), "special_gross": str(sp_gross)})
        else:
            entry.update({"special_net": None, "special_gross": None})
        entry["special_from_date"] = special_from
        entry["special_to_date"] = special_to
        result.append(entry)
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
) -> list[CurrentPrice]:
    """Edit price for one SKU, propagate to all countries. Returns updated CurrentPrices.

    When currency_code is provided, only that currency is updated.
    When currency_code is omitted, all existing currencies are updated (bulk recalc use case).
    """
    try:
        product = ProductRepresentation.objects.get(sku__iexact=sku)
    except ProductRepresentation.DoesNotExist:
        from django_pricemanager.models import TaxClass

        default_tax_class = TaxClass.objects.first()
        if not default_tax_class:
            raise ValueError("No TaxClass exists. Create one before setting prices.")
        product = ProductRepresentation.objects.create(sku=sku, tax_class=default_tax_class)
        logger.info("Auto-created ProductRepresentation for SKU=%s with tax_class=%s", sku, default_tax_class.idx)
    countries = channel.calculate_countries.all()
    if not countries.exists():
        countries = TaxRate.objects.filter(tax_class=product.tax_class).values_list("country", flat=True)
        from django_regional.models import Country

        countries = Country.objects.filter(pk__in=countries)

    # Prefetch: TaxRates for this product's tax class (1 query instead of N)
    tax_rates_by_country = {
        tr.country_id: tr
        for tr in TaxRate.objects.filter(tax_class=product.tax_class, country__in=countries).select_related("country")
    }

    # Prefetch: existing currency_ids per country (1 query instead of N)
    existing_currencies = {}
    for cp in (
        CurrentPrice.objects.filter(
            product=product,
            channel=channel,
            product_parent__isnull=True,
        )
        .values("country_id", "currency_id")
        .distinct()
    ):
        existing_currencies.setdefault(cp["country_id"], []).append(cp["currency_id"])

    # Fallback currency: explicit currency_code > channel's existing > empty
    if currency_code:
        from django_regional.models import Currency

        try:
            fallback_currency_ids = [Currency.objects.get(iso3__iexact=currency_code).pk]
        except Currency.DoesNotExist:
            raise ValueError(f"Currency '{currency_code}' not found")
    else:
        fallback_currency_ids = list(
            CurrentPrice.objects.filter(channel=channel).values_list("currency_id", flat=True).distinct()[:1]
        )

    from django_pricemanager.signals.dispatch import enqueue_price_sync
    from django_pricemanager.signals.killswitch import suppress_price_matrix_signals

    updated = []
    history_batch = []

    # Suppress per-save signals — enqueue once after the loop
    with suppress_price_matrix_signals():
        for country in countries:
            tax_rate = tax_rates_by_country.get(country.pk)
            if not tax_rate:
                logger.warning("No TaxRate for %s/%s — skipping", product.tax_class.idx, country.iso2)
                continue

            net, gross = _calculate_price_pair(value, tax_rate, channel.calculate_direction)
            sp_net, sp_gross = (None, None)
            if special_value is not None:
                sp_net, sp_gross = _calculate_price_pair(special_value, tax_rate, channel.calculate_direction)

            if currency_code:
                currency_ids = fallback_currency_ids
            else:
                currency_ids = existing_currencies.get(country.pk, fallback_currency_ids)

            for cid in currency_ids:
                cp, _ = CurrentPrice.objects.update_or_create(
                    product=product,
                    channel=channel,
                    country=country,
                    currency_id=cid,
                    customer_representation=None,
                    product_parent=None,
                    defaults={
                        "net_value": net,
                        "gross_value": gross,
                        "special_net_value": sp_net,
                        "special_gross_value": sp_gross,
                        "special_from_date": special_from,
                        "special_to_date": special_to,
                        "tax_rate": tax_rate,
                        "source": PriceSource.ADMIN_EDIT,
                        "is_only_for_verified_user": False,
                    },
                )
                updated.append(cp)
                history_batch.append(_log_price_history(cp, PriceSource.ADMIN_EDIT, user))

    if history_batch:
        PriceHistory.objects.bulk_create(history_batch, batch_size=500)

    # Single enqueue after all countries updated
    if updated:
        enqueue_price_sync(sku, channel.idx)

    logger.info("Edited price for %s in %s: %d countries updated", sku, channel.idx, len(updated))
    return updated


def bulk_edit_prices(channel: Channel, items: list[dict], currency_code: str, user=None) -> dict:
    """Bulk-edit prices for multiple SKUs. Each SKU uses savepoint for partial success."""
    from django_pricemanager.signals.dispatch import enqueue_price_sync
    from django_pricemanager.signals.killswitch import suppress_price_matrix_signals

    updated = 0
    changes_logged = 0
    errors = []
    synced_skus = []

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
                    result = edit_price(
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
                    )
                else:
                    from django_regional.models import Currency

                    currency = Currency.objects.get(iso3__iexact=currency_code)
                    prices = CurrentPrice.objects.filter(
                        product__sku__iexact=sku,
                        channel=channel,
                        currency=currency,
                        product_parent__isnull=True,
                        customer_representation__isnull=True,
                    )
                    sp_val = Decimal(str(item["special_value"])) if item.get("special_value") is not None else None
                    history_batch = []
                    result = []
                    for cp in prices:
                        if sp_val is not None:
                            sp_net, sp_gross = _calculate_price_pair(sp_val, cp.tax_rate, channel.calculate_direction)
                        else:
                            sp_net, sp_gross = None, None
                        cp.special_net_value = sp_net
                        cp.special_gross_value = sp_gross
                        cp.special_from_date = item.get("special_from_date")
                        cp.special_to_date = item.get("special_to_date")
                        cp.save()
                        result.append(cp)
                        history_batch.append(_log_price_history(cp, PriceSource.ADMIN_EDIT, user))
                    if history_batch:
                        PriceHistory.objects.bulk_create(history_batch, batch_size=500)
                transaction.savepoint_commit(sid)
                updated += 1
                changes_logged += len(result)
                synced_skus.append(sku)
            except (ValueError, ProductRepresentation.DoesNotExist) as exc:
                transaction.savepoint_rollback(sid)
                errors.append({"sku": sku, "error": str(exc)})
                logger.warning("Bulk edit failed for SKU=%s: %s", sku, exc)
            except Exception:
                transaction.savepoint_rollback(sid)
                import uuid

                error_id = uuid.uuid4().hex[:8]
                logger.exception("Bulk edit unexpected error for SKU=%s [%s]", sku, error_id)
                errors.append({"sku": sku, "error": f"Internal error [{error_id}]"})

    # Enqueue successfully edited SKUs for matrix sync (outside suppress block)
    for sku in synced_skus:
        enqueue_price_sync(sku, channel.idx)

    return {"updated": updated, "changes_logged": changes_logged, "errors": errors}


@transaction.atomic
def flush_special_prices(channel: Channel, sku: str, currency_code: str | None = None, user=None) -> int:
    """Clear special price fields for a SKU in a channel. Optionally scoped to one currency."""
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
    """Delete CurrentPrice rows for a SKU in a channel. Optionally scoped to one currency."""
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
    # Manual enqueue — queryset .delete() fires per-row signals but we want one enqueue
    from django_pricemanager.signals.dispatch import enqueue_price_sync

    enqueue_price_sync(sku, channel.idx)
    return len(prices)
