# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, ConfigDict, Field


class SaleChannelOverview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str = Field(description="ISO2 country code this sale channel targets", examples=["PL"])
    price_source: str = Field(
        description="Identifier of the price source used by this sale channel", examples=["default-europe"]
    )
    customer: str | None = Field(
        None,
        description="Customer group identifier when the sale channel is customer-specific, null for default",
        examples=["wholesale"],
    )
    price_count: int = Field(
        0, description="Number of active price entries served by this sale channel", examples=[1240]
    )


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Channel primary key", examples=[1])
    idx: str = Field(description="Unique channel slug used in API paths", examples=["default-europe"])
    name: str = Field(description="Human-readable channel name", examples=["Default Europe"])
    calculate_direction: str = Field(
        description="Price calculation direction for this channel: from_net_to_gross or from_gross_to_net",
        examples=["from_net_to_gross"],
    )
    calculate_countries: list[dict] = Field(
        default_factory=list,
        description="List of country objects used for price calculation, each with iso2 and name keys",
        examples=[[{"iso2": "PL", "name": "Poland"}, {"iso2": "DE", "name": "Germany"}]],
    )
    sale_channels: list[SaleChannelOverview] = Field(
        default_factory=list, description="Sale channel configurations attached to this channel"
    )
    stats: dict = Field(
        default_factory=dict,
        description="Aggregate counts for this channel: total_products, countries, currencies",
        examples=[{"total_products": 850, "countries": 4, "currencies": 2}],
    )
    default_country: str | None = Field(None, description="ISO2 code of default country", examples=["PL"])


class ChannelListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Channel primary key", examples=[1])
    idx: str = Field(description="Unique channel slug used in API paths", examples=["default-europe"])
    name: str = Field(description="Human-readable channel name", examples=["Default Europe"])
    calculate_direction: str = Field(
        description="Price calculation direction: from_net_to_gross or from_gross_to_net",
        examples=["from_net_to_gross"],
    )
    country_count: int = Field(0, description="Number of calculate_countries assigned to this channel", examples=[4])
    default_country: str | None = Field(None, description="ISO2 code of default country", examples=["PL"])


class ChannelSyncResponse(BaseModel):
    synced: int = Field(description="Total number of channels processed during sync", examples=[3])
    created: int = Field(description="Number of new channel records created", examples=[1])
    updated: int = Field(description="Number of existing channel records updated", examples=[2])
