# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from pydantic import BaseModel, Field


class TaxClassCreateRequest(BaseModel):
    name: str = Field(
        description="Human-readable tax class name displayed in the admin UI.",
        examples=["Standard"],
    )


class TaxRateCreateRequest(BaseModel):
    country_code: str = Field(
        description="ISO 3166-1 alpha-2 country code the rate applies to.",
        examples=["PL"],
    )
    rate: Decimal = Field(
        description="Tax rate as a decimal fraction (e.g. 0.2300 for 23%). Must be >= 0.",
        examples=["0.2300"],
    )


class TaxRateUpdateRequest(BaseModel):
    rate: Decimal = Field(
        description="New tax rate as a decimal fraction (e.g. 0.2500 for 25%). Triggers price recalculation for affected CurrentPrice records.",
        examples=["0.2500"],
    )
