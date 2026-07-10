# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django_regional.models import Country
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricemanager.api.admin.permissions import IsAdminUser
from django_pricemanager.models import Channel, CurrentPrice
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.schemas.requests.channel import ChannelCreateRequest, ChannelUpdateRequest
from django_pricemanager.schemas.responses.channel import ChannelListItemResponse, ChannelResponse, ChannelSyncResponse
from django_pricemanager.services.channel_sync_service import sync_channels_from_pim

DIRECTION_MAP = {
    "from_net_to_gross": CalculateDirectionEnum.FROM_NET_TO_GROSS,
    "from_gross_to_net": CalculateDirectionEnum.FROM_GROSS_TO_NET,
}

DIRECTION_LABEL_MAP = {
    CalculateDirectionEnum.FROM_NET_TO_GROSS: "from_net_to_gross",
    CalculateDirectionEnum.FROM_GROSS_TO_NET: "from_gross_to_net",
}


def _channel_list_item(channel: Channel) -> dict:
    return ChannelListItemResponse(
        id=channel.pk,
        idx=channel.idx,
        name=channel.name,
        calculate_direction=DIRECTION_LABEL_MAP[CalculateDirectionEnum(channel.calculate_direction)],
        country_count=channel.calculate_countries.count(),
        default_country=channel.default_country.iso2 if channel.default_country else None,
    ).model_dump()


def _channel_detail(channel: Channel) -> dict:
    calculate_countries = [{"iso2": c.iso2, "name": c.name_en} for c in channel.calculate_countries.all()]
    sale_channels_qs = channel.sale_channels.select_related("country", "customer_representation").all()
    sale_channels = []
    for sc in sale_channels_qs:
        price_count = CurrentPrice.objects.filter(channel=channel, country=sc.country).count()
        sale_channels.append(
            {
                "country": sc.country.iso2,
                "price_source": sc.price_source,
                "customer": sc.customer_representation.uid if sc.customer_representation else None,
                "price_count": price_count,
            }
        )

    total_products = CurrentPrice.objects.filter(channel=channel).values("product").distinct().count()
    country_count = CurrentPrice.objects.filter(channel=channel).values("country").distinct().count()
    currency_count = CurrentPrice.objects.filter(channel=channel).values("currency").distinct().count()

    return ChannelResponse(
        id=channel.pk,
        idx=channel.idx,
        name=channel.name,
        calculate_direction=DIRECTION_LABEL_MAP[CalculateDirectionEnum(channel.calculate_direction)],
        calculate_countries=calculate_countries,
        sale_channels=sale_channels,
        stats={"total_products": total_products, "countries": country_count, "currencies": currency_count},
        default_country=channel.default_country.iso2 if channel.default_country else None,
    ).model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Channels"]),
    retrieve=extend_schema(tags=["Channels"]),
    create=extend_schema(tags=["Channels"]),
    partial_update=extend_schema(tags=["Channels"]),
    destroy=extend_schema(tags=["Channels"]),
)
class ChannelViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List channels",
        description="Returns all price channels with calculate_direction and country count.",
        responses={200: ChannelListItemResponse},
    )
    def list(self, request) -> Response:
        channels = Channel.objects.prefetch_related("calculate_countries").order_by("idx")
        return Response([_channel_list_item(ch) for ch in channels])

    @extend_schema(
        summary="Retrieve channel",
        description="Returns channel detail including calculate_countries, sale_channel overview, and aggregate stats.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Channel slug identifier")],
        responses={200: ChannelResponse, 404: {"description": "Channel not found"}},
    )
    def retrieve(self, request, idx: str | None = None) -> Response:
        try:
            channel = Channel.objects.prefetch_related(
                "calculate_countries", "sale_channels__country", "sale_channels__customer_representation"
            ).get(idx=idx)
        except Channel.DoesNotExist:
            raise NotFound(f"Channel '{idx}' not found.") from None
        return Response(_channel_detail(channel))

    @extend_schema(
        summary="Create channel",
        description="Creates a new price channel and assigns calculate_countries by country code.",
        responses={201: ChannelResponse, 400: {"description": "Validation error"}},
    )
    def create(self, request) -> Response:
        try:
            data = ChannelCreateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        direction = DIRECTION_MAP.get(data.calculate_direction)
        if direction is None:
            raise DRFValidationError({"calculate_direction": "Must be 'from_net_to_gross' or 'from_gross_to_net'."})

        from idx_normalizator import normalize_idx

        channel = Channel.objects.create(idx=normalize_idx(data.name), name=data.name, calculate_direction=direction)

        if data.calculate_country_codes:
            countries = Country.objects.filter(iso2__in=data.calculate_country_codes)
            channel.calculate_countries.set(countries)

        if data.default_country_code:
            channel.default_country = Country.objects.filter(iso2=data.default_country_code.upper()).first()
            channel.save()

        channel.refresh_from_db()
        channel = Channel.objects.prefetch_related(
            "calculate_countries", "sale_channels__country", "sale_channels__customer_representation"
        ).get(pk=channel.pk)
        return Response(_channel_detail(channel), status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update channel",
        description="Partially updates channel name, calculate_direction, or calculate_countries.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Channel slug identifier")],
        responses={
            200: ChannelResponse,
            400: {"description": "Validation error"},
            404: {"description": "Channel not found"},
        },
    )
    def partial_update(self, request, idx: str | None = None) -> Response:
        try:
            channel = Channel.objects.prefetch_related(
                "calculate_countries", "sale_channels__country", "sale_channels__customer_representation"
            ).get(idx=idx)
        except Channel.DoesNotExist:
            raise NotFound(f"Channel '{idx}' not found.") from None

        try:
            data = ChannelUpdateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        if data.name is not None:
            channel.name = data.name

        if data.calculate_direction is not None:
            direction = DIRECTION_MAP.get(data.calculate_direction)
            if direction is None:
                raise DRFValidationError({"calculate_direction": "Must be 'from_net_to_gross' or 'from_gross_to_net'."})
            channel.calculate_direction = direction

        if data.default_country_code is not None:
            channel.default_country = Country.objects.filter(iso2=data.default_country_code.upper()).first()

        channel.save()

        if data.calculate_country_codes is not None:
            countries = Country.objects.filter(iso2__in=data.calculate_country_codes)
            channel.calculate_countries.set(countries)

        channel = Channel.objects.prefetch_related(
            "calculate_countries", "sale_channels__country", "sale_channels__customer_representation"
        ).get(pk=channel.pk)
        return Response(_channel_detail(channel))

    @extend_schema(
        summary="Delete channel",
        description="Deletes the channel. Returns 400 if the channel has active CurrentPrices.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Channel slug identifier")],
        responses={
            204: {"description": "Deleted successfully"},
            400: {"description": "Channel has active prices"},
            404: {"description": "Channel not found"},
        },
    )
    def destroy(self, request, idx: str | None = None) -> Response:
        try:
            channel = Channel.objects.get(idx=idx)
        except Channel.DoesNotExist:
            raise NotFound(f"Channel '{idx}' not found.") from None

        if CurrentPrice.objects.filter(channel=channel).exists():
            raise DRFValidationError(
                {"detail": "Cannot delete channel with active prices. Remove all CurrentPrice records first."}
            )

        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Sync channels from PIM",
        description="Syncs channel idx and name from django-pim. Idempotent — safe to call repeatedly.",
        responses={200: ChannelSyncResponse},
    )
    def sync(self, request) -> Response:
        result = sync_channels_from_pim()
        return Response(ChannelSyncResponse(**result).model_dump())
