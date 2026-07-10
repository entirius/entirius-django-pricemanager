# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, ConfigDict, Field


class TaxRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str = Field(description="ISO2 country code", examples=["PL"])
    country_name: str = Field(description="Full country name", examples=["Poland"])
    rate: str = Field(description="Tax rate as a decimal string", examples=["0.2300"])
    percent: str = Field(description="Tax rate expressed as a percentage string", examples=["23.00%"])


class TaxClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Tax class primary key", examples=[1])
    idx: str = Field(description="Unique tax class slug used in API paths", examples=["standard"])
    name: str = Field(description="Human-readable tax class name", examples=["Standard VAT"])
    rates: list[TaxRateResponse] = Field(
        default_factory=list,
        description="Per-country tax rates belonging to this tax class",
    )
    product_count: int = Field(
        0,
        description="Number of products currently assigned to this tax class",
        examples=[342],
    )


class TaxClassListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Tax class primary key", examples=[1])
    idx: str = Field(description="Unique tax class slug used in API paths", examples=["standard"])
    name: str = Field(description="Human-readable tax class name", examples=["Standard VAT"])
    rate_count: int = Field(
        0,
        description="Number of per-country rate entries defined for this tax class",
        examples=[4],
    )
