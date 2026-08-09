# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Single choke-point for CurrentPrice writes.

Every writer of CurrentPrice funnels its intended new values through
guard_price_write(), which resolves two independent questions:
  1. Precedence — is `writer` allowed to overwrite the row's current `source`?
  2. Bounds — do the new values respect the configured price floor?

Django admin is intentionally NOT wired through this guard — it is the
emergency root tool and overwrites unconditionally (see AGENTS.md). The
same applies to price_edit_service.flush_special_prices/delete_prices,
which log audit-only source strings outside the PriceSource enum.
"""

from dataclasses import dataclass
from decimal import Decimal

from django_pricemanager.models.choices import PriceSource
from django_pricemanager.models.price_write_policy import PriceSourcePolicy, PriceWriteEnforceMode

_DEFAULT_ENFORCE_MODE = {
    PriceSource.ADMIN_EDIT: PriceWriteEnforceMode.REJECT,
}


@dataclass(frozen=True)
class PriceBounds:
    """Floor for one (sku, channel, country), GROSS."""

    floor: Decimal | None


@dataclass(frozen=True)
class GuardDecision:
    status: str  # "applied" | "clamped" | "skipped"
    values: dict
    source: str | None
    reason: str | None = None


def load_policy_map() -> dict[str, PriceSourcePolicy]:
    """Preload all policy rows — call once per batch operation, reuse across rows."""
    return {p.source: p for p in PriceSourcePolicy.objects.all()}


def _recalc_overwritable(existing_source: str, policy_map: dict[str, PriceSourcePolicy]) -> bool:
    policy = policy_map.get(existing_source)
    if policy is None:
        return False  # fill-only default
    return policy.recalc_overwritable


def _enforce_mode(writer: str, policy_map: dict[str, PriceSourcePolicy]) -> str:
    if writer == PriceSource.TAX_RATE_CHANGE:
        return PriceWriteEnforceMode.CLAMP  # VAT recalc is mandatory — never rejects
    policy = policy_map.get(writer)
    if policy is not None:
        return policy.enforce_mode
    return _DEFAULT_ENFORCE_MODE.get(writer, PriceWriteEnforceMode.CLAMP)


def _precedence_allows(writer: str, existing_source: str | None, policy_map: dict[str, PriceSourcePolicy]) -> bool:
    if existing_source is None:
        return True
    if writer == PriceSource.PRICEFIGHTER:
        return existing_source != PriceSource.ADMIN_EDIT
    if writer == PriceSource.BASELINE:
        if existing_source == PriceSource.BASELINE:
            return True  # a recalc may always refresh its own prior value (cost/VAT change)
        return _recalc_overwritable(existing_source, policy_map)
    return True  # admin_edit/csv_import/generation/migration/.../api — today's behavior: overwrite everything


def _clamp_pair(values: dict, gross_field: str, net_field: str, floor: Decimal, tax_rate) -> None:
    values[gross_field] = floor
    if tax_rate is not None and net_field in values:
        values[net_field] = tax_rate.net_price(floor)


def _apply_bounds(
    values: dict, writer: str, bounds: PriceBounds | None, policy_map: dict[str, PriceSourcePolicy]
) -> tuple[dict, str, str | None]:
    if bounds is None or bounds.floor is None:
        return values, "applied", None

    tax_rate = values.get("tax_rate")
    violations = [
        (gross_field, net_field)
        for gross_field, net_field in (("gross_value", "net_value"), ("special_gross_value", "special_net_value"))
        if values.get(gross_field) is not None and values[gross_field] < bounds.floor
    ]
    if not violations:
        return values, "applied", None

    fields_desc = ",".join(g for g, _ in violations)
    if _enforce_mode(writer, policy_map) == PriceWriteEnforceMode.REJECT:
        return {}, "skipped", f"below floor {bounds.floor}: {fields_desc}"

    clamped = dict(values)
    for gross_field, net_field in violations:
        _clamp_pair(clamped, gross_field, net_field, bounds.floor, tax_rate)
    return clamped, "clamped", f"clamped to floor {bounds.floor}: {fields_desc}"


def guard_price_write(
    *,
    existing_source: str | None,
    new_values: dict,
    writer: str,
    stored_source: str | None = None,
    bounds: PriceBounds | None = None,
    policy_map: dict[str, PriceSourcePolicy] | None = None,
) -> GuardDecision:
    """Decide whether `writer` may write `new_values` over a row currently stamped `existing_source`.

    `new_values` carries CurrentPrice field values plus an optional `tax_rate` instance
    used to recompute the paired net value when a gross value gets clamped. Never raises
    for policy violations — a reject is reported as a "skipped" decision.
    """
    if policy_map is None:
        policy_map = load_policy_map()

    if not _precedence_allows(writer, existing_source, policy_map):
        return GuardDecision(
            status="skipped", values={}, source=None, reason=f"{writer} may not overwrite source={existing_source}"
        )

    values, status, reason = _apply_bounds(new_values, writer, bounds, policy_map)
    if status == "skipped":
        return GuardDecision(status="skipped", values={}, source=None, reason=reason)

    return GuardDecision(status=status, values=values, source=stored_source or writer, reason=reason)
