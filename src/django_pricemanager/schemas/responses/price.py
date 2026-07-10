# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, ConfigDict, Field


class CountryPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str = Field(description="ISO2 country code", examples=["PL"])
    currency: str = Field(description="ISO 4217 currency code", examples=["PLN"])
    tax_rate: str = Field(description="Tax rate as decimal string", examples=["0.2300"])
    net: str = Field(description="Net price", examples=["100.00"])
    gross: str = Field(description="Gross price", examples=["123.00"])
    special_net: str | None = Field(
        None, description="Special net price, null when no promotion is active", examples=["80.00"]
    )
    special_gross: str | None = Field(
        None, description="Special gross price, null when no promotion is active", examples=["98.40"]
    )
    special_from_date: str | None = Field(
        None, description="Special price validity start date (ISO 8601)", examples=["2026-04-01"]
    )
    special_to_date: str | None = Field(
        None, description="Special price validity end date (ISO 8601)", examples=["2026-04-30"]
    )
    is_only_for_verified_user: bool = Field(
        False, description="When true, price is visible only to verified users", examples=[False]
    )
    modified_at: str | None = Field(
        None, description="ISO 8601 timestamp of the last modification", examples=["2026-03-20T14:30:00Z"]
    )
    source: str | None = Field(
        None,
        description="Identifier of what produced this row (admin_edit / csv_import / generation / ...)",
        examples=["admin_edit"],
    )


class PurchaseCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str = Field(description="ISO2 country code", examples=["PL"])
    currency: str = Field(description="ISO 4217 currency code", examples=["PLN"])
    net_cost: str = Field(description="Buy-side net cost (what we pay the supplier)", examples=["0.1300"])
    supplier_idx: str | None = Field(None, description="Supplier idx this cost came from", examples=["fortrade"])
    modified_at: str | None = Field(
        None, description="ISO 8601 timestamp of the last cost write", examples=["2026-06-02T10:00:00Z"]
    )


class PriceListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str = Field(description="Product SKU identifier", examples=["CHAIR-001"])
    tax_class: str = Field(description="Tax class identifier (idx)", examples=["standard"])
    countries: list[CountryPriceResponse] = Field(
        default_factory=list,
        description="Per-country price breakdown for this SKU",
    )


class PriceDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str = Field(description="Product SKU identifier", examples=["CHAIR-001"])
    tax_class: str = Field(description="Tax class identifier (idx)", examples=["standard"])
    calculate_direction: str = Field(
        description="Price calculation direction: from_net_to_gross or from_gross_to_net",
        examples=["from_net_to_gross"],
    )
    prices: list[CountryPriceResponse] = Field(
        default_factory=list,
        description="Per-country prices for this SKU",
    )
    purchase_costs: list[PurchaseCostResponse] = Field(
        default_factory=list,
        description="Per-country buy-side costs (independent of sell price; margin = net vs net_cost)",
    )


class PricePatchResponse(PriceDetailResponse):
    changes_logged: int = Field(
        description="Number of PriceHistory entries created as a result of this update",
        examples=[3],
    )


class PriceHistoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="History entry primary key", examples=[42])
    country: str = Field(description="ISO2 country code this entry applies to", examples=["PL"])
    currency: str = Field(description="ISO 4217 currency code at time of change", examples=["PLN"])
    gross_value: str = Field(description="Gross price at the time of the change", examples=["116.85"])
    net_value: str = Field(description="Net price at the time of the change", examples=["95.00"])
    special_gross_value: str | None = Field(
        None,
        description="Special gross price at the time of the change, null if not set",
        examples=["90.00"],
    )
    special_net_value: str | None = Field(
        None,
        description="Special net price at the time of the change, null if not set",
        examples=["73.17"],
    )
    tax_rate: str | None = Field(
        None,
        description="Tax rate decimal at the time of the change",
        examples=["0.2300"],
    )
    source: str = Field(
        description="Identifier of the system or action that triggered this change",
        examples=["admin_edit"],
    )
    changed_by: str | None = Field(
        None,
        description="Email address of the user who made the change, null for automated sources",
        examples=["admin@example.com"],
    )
    created_at: str = Field(
        description="ISO 8601 timestamp of when the change was recorded",
        examples=["2026-03-25T10:15:00Z"],
    )


class BulkPriceEditError(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sku: str = Field(description="SKU that failed", examples=["BAD-SKU"])
    error: str = Field(description="Error message", examples=["No TaxClass exists"])


class BulkPricePatchResponse(BaseModel):
    updated: int = Field(description="Number of SKUs successfully updated", examples=[3])
    changes_logged: int = Field(description="Total PriceHistory entries created", examples=[15])
    errors: list[BulkPriceEditError] = Field(default_factory=list, description="Per-SKU errors")
