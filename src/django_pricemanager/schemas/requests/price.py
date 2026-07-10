# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from pydantic import BaseModel, Field


class PriceEditRequest(BaseModel):
    value: Decimal = Field(
        description="Price value (net or gross depending on channel calculate_direction)",
        examples=["95.00"],
    )
    currency_code: str | None = Field(
        None,
        description="ISO 4217 currency code. Required when creating the initial price for a product. "
        "Ignored on updates (uses existing currency).",
        examples=["EUR"],
    )
    special_value: Decimal | None = Field(
        None,
        description="Special/promotional price value. Pass null to clear the promotion.",
        examples=["80.00"],
    )
    special_from_date: str | None = Field(
        None,
        description="Special price start date in ISO 8601 format (YYYY-MM-DD). Null means no start restriction.",
        examples=["2026-04-01"],
    )
    special_to_date: str | None = Field(
        None,
        description="Special price end date in ISO 8601 format (YYYY-MM-DD). Null means no end restriction.",
        examples=["2026-04-30"],
    )


class BulkPriceEditItem(BaseModel):
    sku: str = Field(description="Product SKU", examples=["ENT-S001"])
    value: Decimal | None = Field(
        None, description="Price value (net or gross). Omit when editing only special fields.", examples=["95.00"]
    )
    special_value: Decimal | None = Field(
        None, description="Special price value. None clears promotion.", examples=["80.00"]
    )
    special_from_date: str | None = Field(None, description="Special price start (ISO 8601)", examples=["2026-04-01"])
    special_to_date: str | None = Field(None, description="Special price end (ISO 8601)", examples=["2026-04-30"])
    tax_class_idx: str | None = Field(
        None, description="Tax class for new products without ProductRepresentation", examples=["standard"]
    )


class BulkPriceEditRequest(BaseModel):
    items: list[BulkPriceEditItem] = Field(description="Price edits to apply")
    currency_code: str = Field(description="ISO 4217 currency code for all items", examples=["EUR"])
