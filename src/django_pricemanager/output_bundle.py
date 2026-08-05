# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django_pricemanager.services.pricelist_service import get_latest_pricelist


def _fetch_bundle_component_prices(
    channel_idx: str,
    country_code: str,
    currency_code: str,
    bundle_sku: str,
    components_sku: list | None = None,
    uid: str | None = None,
) -> tuple[list | None, bool]:
    """Internal: resolve pricelist + fetch annotated component Price rows.

    Returns (price_list | None, is_only_for_verified_user). `None` means no
    pricelist exists for the (channel, country, currency, uid) tuple. Empty
    list means pricelist exists but no component prices are available — the
    uid-fallback already happened.

    Annotation `with_eligibility_for_special_price()` is applied so callers
    can read `price.is_egible_for_special_price` as a real boolean. This was
    previously missed by `get_product_bundle_components_price` — fixing here.
    """
    prl = get_latest_pricelist(channel_idx=channel_idx, country=country_code, currency=currency_code, uid=uid)
    if not prl:
        return None, False
    is_only_for_verified_user = prl.sale_channel.is_only_for_verified_user

    qs = (
        prl.prices.filter(attrs__isnull=True, product_parent__sku=bundle_sku)
        .select_related("product", "tax_rate")
        .with_eligibility_for_special_price()
    )
    if components_sku:
        qs = qs.filter(product__sku__in=components_sku)
    prices = list(qs)

    if not prices and uid:
        return _fetch_bundle_component_prices(
            channel_idx=channel_idx,
            country_code=country_code,
            currency_code=currency_code,
            bundle_sku=bundle_sku,
            components_sku=components_sku,
            uid=None,
        )
    return prices, is_only_for_verified_user


# Used by:
# django-matrix
def get_product_bundle_components_price(
    channel_idx: str,
    country_code: str,
    currency_code: str,
    bundle_sku: str,
    components_sku: list | None = None,
    uid: str | None = None,
) -> tuple[list, bool]:
    prices, is_only_for_verified_user = _fetch_bundle_component_prices(
        channel_idx=channel_idx,
        country_code=country_code,
        currency_code=currency_code,
        bundle_sku=bundle_sku,
        components_sku=components_sku,
        uid=uid,
    )
    if prices is None:
        return [], False
    return prices, is_only_for_verified_user


# Used by:
# django-matrix (read-model worker for ranged bundles)
# django-checkout (cart price aggregation for ranged bundles)
def get_aggregated_bundle_price(
    channel_idx: str,
    country_code: str,
    currency_code: str,
    bundle_sku: str,
    components_quantities: dict | None = None,
    uid: str | None = None,
    is_customer_verified: bool = False,
) -> tuple[dict | None, bool]:
    """Aggregate bundle subproduct prices into a single bundle-level snapshot.

    Two modes:
    - components_quantities=None → aggregate ALL components in the pricelist
      (each contributes 1×). Used for legacy bundles without min/max limits.
    - components_quantities={sub_sku: qty, ...} → aggregate only listed SKUs,
      each multiplied by its quantity. Used for ranged bundles where only
      default-selected subproducts contribute. Returns (None, ...) if any
      listed SKU is missing from the active pricelist.

    On a sale channel flagged `is_only_for_verified_user`, no snapshot is
    returned unless `is_customer_verified=True`. The default is fail-closed:
    a caller that does not know the customer's verification status must not
    receive B2B-only pricing it might publish to anonymous visitors.

    Returns (snapshot_dict | None, is_only_for_verified_user). Snapshot dict:

        {
            "bundle_sku": str,
            "gross": Decimal,
            "net": Decimal,
            "final_gross": Decimal,           # gross with eligible specials applied
            "final_net": Decimal,
            "has_special_price": bool,
            "special_gross": Decimal | None,  # None when no component has a special
            "special_net": Decimal | None,
            "promo_badge": str | None,        # e.g. "15%"
            "special_from_date": datetime | None,  # earliest among contributing specials
            "special_to_date": datetime | None,    # latest
            "tax_rate": Decimal | None,       # from cheapest contributing component
        }
    """
    components_sku = list(components_quantities.keys()) if components_quantities is not None else None
    prices, is_only_for_verified_user = _fetch_bundle_component_prices(
        channel_idx=channel_idx,
        country_code=country_code,
        currency_code=currency_code,
        bundle_sku=bundle_sku,
        components_sku=components_sku,
        uid=uid,
    )
    if prices is None:
        return None, False
    if is_only_for_verified_user and not is_customer_verified:
        return None, is_only_for_verified_user
    if not prices:
        return None, is_only_for_verified_user

    if components_quantities is not None:
        present_skus = {p.product.sku for p in prices}
        missing = set(components_quantities.keys()) - present_skus
        if missing:
            return None, is_only_for_verified_user

    snapshot = _aggregate_components(bundle_sku, prices, components_quantities)
    return snapshot, is_only_for_verified_user


def _aggregate_components(bundle_sku: str, prices: list, components_quantities: dict | None) -> dict:
    total_gross = Decimal(0)
    total_net = Decimal(0)
    total_final_gross = Decimal(0)
    total_final_net = Decimal(0)
    total_special_gross = Decimal(0)
    total_special_net = Decimal(0)
    has_any_special = False
    earliest_special_from = None
    latest_special_to = None
    cheapest_unit_gross: Decimal | None = None
    cheapest_tax_rate: Decimal | None = None
    cheapest_sku_tiebreak: str | None = None

    for p in prices:
        sku = p.product.sku
        qty = (
            Decimal(components_quantities[sku])
            if components_quantities is not None and sku in components_quantities
            else Decimal(1)
        )
        gross = Decimal(p.gross_value) if p.gross_value is not None else Decimal(0)
        net = Decimal(p.net_value) if p.net_value is not None else Decimal(0)
        # Annotated by `_fetch_bundle_component_prices`
        is_eligible = bool(p.is_egible_for_special_price)
        has_special = bool(p.special_gross_value) and is_eligible

        total_gross += gross * qty
        total_net += net * qty

        if has_special:
            has_any_special = True
            sg = Decimal(p.special_gross_value)
            sn = Decimal(p.special_net_value) if p.special_net_value is not None else Decimal(0)
            total_final_gross += sg * qty
            total_final_net += sn * qty
            total_special_gross += sg * qty
            total_special_net += sn * qty
            if p.special_from_date and (earliest_special_from is None or p.special_from_date < earliest_special_from):
                earliest_special_from = p.special_from_date
            if p.special_to_date and (latest_special_to is None or p.special_to_date > latest_special_to):
                latest_special_to = p.special_to_date
        else:
            total_final_gross += gross * qty
            total_final_net += net * qty
            total_special_gross += gross * qty
            total_special_net += net * qty

        is_cheaper = (
            cheapest_unit_gross is None
            or gross < cheapest_unit_gross
            or (gross == cheapest_unit_gross and (cheapest_sku_tiebreak is None or sku < cheapest_sku_tiebreak))
        )
        if is_cheaper:
            cheapest_unit_gross = gross
            cheapest_tax_rate = Decimal(p.tax_rate.rate) if p.tax_rate is not None else None
            cheapest_sku_tiebreak = sku

    if has_any_special and total_gross > 0:
        badge = round(Decimal(100) - (total_special_gross / total_gross * Decimal(100)), 0)
        promo_badge = f"{badge}%" if badge > 0 else None
    else:
        promo_badge = None

    return {
        "bundle_sku": bundle_sku,
        "gross": total_gross,
        "net": total_net,
        "final_gross": total_final_gross,
        "final_net": total_final_net,
        "has_special_price": has_any_special,
        "special_gross": total_special_gross if has_any_special else None,
        "special_net": total_special_net if has_any_special else None,
        "promo_badge": promo_badge,
        "special_from_date": earliest_special_from,
        "special_to_date": latest_special_to,
        "tax_rate": cheapest_tax_rate,
    }
