# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, Field


class ChannelCreateRequest(BaseModel):
    name: str = Field(description="Channel display name shown in the admin UI.", examples=["B2C Europe"])
    calculate_direction: str = Field(
        description=(
            "Tax calculation direction for this channel. "
            "Use 'from_net_to_gross' when admins enter net prices, "
            "'from_gross_to_net' when admins enter gross prices."
        ),
        examples=["from_net_to_gross"],
    )
    calculate_country_codes: list[str] = Field(
        default_factory=list,
        description="ISO 3166-1 alpha-2 country codes this channel serves. Empty list means no country restriction.",
        examples=[["PL", "DE", "FR"]],
    )
    default_country_code: str | None = Field(None, description="ISO2 code for default country", examples=["PL"])


class ChannelUpdateRequest(BaseModel):
    name: str | None = Field(None, description="Channel display name shown in the admin UI.", examples=["B2C Europe"])
    calculate_direction: str | None = Field(
        None,
        description=(
            "Tax calculation direction for this channel. "
            "Use 'from_net_to_gross' when admins enter net prices, "
            "'from_gross_to_net' when admins enter gross prices."
        ),
        examples=["from_net_to_gross"],
    )
    calculate_country_codes: list[str] | None = Field(
        None,
        description="ISO 3166-1 alpha-2 country codes this channel serves. Null leaves the current list unchanged.",
        examples=[["PL", "DE", "FR"]],
    )
    default_country_code: str | None = Field(None, description="ISO2 code for default country", examples=["PL"])
