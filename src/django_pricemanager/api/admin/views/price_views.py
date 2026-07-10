# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from itertools import groupby

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricemanager.api.admin.pagination import AdminPageNumberPagination
from django_pricemanager.api.admin.permissions import IsAdminUser
from django_pricemanager.models import Channel, CurrentPrice, PriceHistory, ProductRepresentation, PurchaseCost
from django_pricemanager.schemas.requests.price import BulkPriceEditRequest, PriceEditRequest
from django_pricemanager.schemas.responses.price import (
    BulkPricePatchResponse,
    CountryPriceResponse,
    PriceDetailResponse,
    PriceHistoryEntryResponse,
    PriceListItemResponse,
    PricePatchResponse,
    PurchaseCostResponse,
)
from django_pricemanager.services import price_edit_service

_CHANNEL_IDX_PARAM = OpenApiParameter(
    name="channel_idx", location=OpenApiParameter.PATH, description="Channel identifier (idx)"
)
_SKU_PARAM = OpenApiParameter(name="sku", location=OpenApiParameter.PATH, description="Product SKU identifier")


def _current_price_to_country_response(cp: CurrentPrice) -> CountryPriceResponse:
    return CountryPriceResponse(
        country=cp.country.iso2,
        currency=cp.currency.iso3,
        tax_rate=str(cp.tax_rate.rate) if cp.tax_rate else "0.0000",
        net=str(cp.net_value),
        gross=str(cp.gross_value),
        special_net=str(cp.special_net_value) if cp.special_net_value is not None else None,
        special_gross=str(cp.special_gross_value) if cp.special_gross_value is not None else None,
        special_from_date=cp.special_from_date.date().isoformat() if cp.special_from_date else None,
        special_to_date=cp.special_to_date.date().isoformat() if cp.special_to_date else None,
        is_only_for_verified_user=cp.is_only_for_verified_user,
        modified_at=cp.modified_at.isoformat() if cp.modified_at else None,
        source=cp.source or None,
    )


def _purchase_cost_to_response(pc: PurchaseCost) -> PurchaseCostResponse:
    return PurchaseCostResponse(
        country=pc.country.iso2,
        currency=pc.currency.iso3,
        net_cost=str(pc.net_cost),
        supplier_idx=pc.supplier_idx or None,
        modified_at=pc.modified_at.isoformat() if pc.modified_at else None,
    )


def _build_price_list_item(sku: str, prices: list[CurrentPrice]) -> PriceListItemResponse:
    tax_class = prices[0].product.tax_class.idx if prices else ""
    return PriceListItemResponse(
        sku=sku, tax_class=tax_class, countries=[_current_price_to_country_response(cp) for cp in prices]
    )


def _history_entry_to_response(entry: PriceHistory) -> PriceHistoryEntryResponse:
    return PriceHistoryEntryResponse(
        id=entry.pk,
        country=entry.country.iso2,
        currency=entry.currency.iso3,
        gross_value=str(entry.gross_value),
        net_value=str(entry.net_value),
        special_gross_value=str(entry.special_gross_value) if entry.special_gross_value is not None else None,
        special_net_value=str(entry.special_net_value) if entry.special_net_value is not None else None,
        tax_rate=str(entry.tax_rate.rate) if entry.tax_rate else None,
        source=entry.source,
        changed_by=entry.changed_by.email if entry.changed_by else None,
        created_at=entry.created_at.isoformat(),
    )


def _parse_price_edit_request(data: dict) -> PriceEditRequest:
    try:
        return PriceEditRequest(**data)
    except ValidationError as exc:
        from django_utils.api.v2_errors import raise_pydantic_as_drf

        raise_pydantic_as_drf(exc)


@extend_schema_view(
    list=extend_schema(tags=["Prices"]),
    retrieve=extend_schema(tags=["Prices"]),
    partial_update=extend_schema(tags=["Prices"]),
    bulk_update=extend_schema(tags=["Prices"]),
)
class PriceViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = AdminPageNumberPagination

    @extend_schema(
        summary="List prices",
        description=(
            "Returns prices grouped by SKU for the given channel. "
            "Each item contains per-country price breakdown. "
            "Supports filtering by SKU substring, country ISO2 code, and currency code."
        ),
        parameters=[
            _CHANNEL_IDX_PARAM,
            OpenApiParameter(name="search", description="Filter by SKU substring (case-insensitive)", required=False),
            OpenApiParameter(name="country", description="Filter by ISO2 country code (e.g. PL)", required=False),
            OpenApiParameter(
                name="currency", description="Filter by ISO 4217 currency code (e.g. PLN)", required=False
            ),
            OpenApiParameter(name="page", description="Page number", required=False),
            OpenApiParameter(name="page_size", description="Items per page (max 100)", required=False),
        ],
        responses={
            200: PriceListItemResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel not found"},
        },
    )
    def list(self, request, channel_idx: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        base_filters = {
            "channel__idx": channel_idx,
            "product_parent__isnull": True,
            "customer_representation__isnull": True,
        }
        search = request.query_params.get("search")
        if search:
            base_filters["product__sku__icontains"] = search
        country = request.query_params.get("country")
        if country:
            base_filters["country__iso2__iexact"] = country
        currency = request.query_params.get("currency")
        # Support comma-separated currencies: ?currency=EUR,PLN,GBP
        currency_list = [c.strip().upper() for c in currency.split(",")] if currency else []

        paginator = self.pagination_class()

        if currency_list:
            # Flat mode: one row per SKU+currency, default country, sorted by SKU then currency
            if not country and channel.default_country:
                base_filters["country__iso2__iexact"] = channel.default_country.iso2

            if len(currency_list) == 1:
                base_filters["currency__iso3__iexact"] = currency_list[0]
            else:
                base_filters["currency__iso3__in"] = currency_list

            prices = (
                CurrentPrice.objects.filter(**base_filters)
                .select_related("product__tax_class", "country", "currency", "tax_rate")
                .order_by("product__sku", "currency__iso3")
            )
            page = paginator.paginate_queryset(prices, request)
            items = []
            for cp in page:
                items.append(
                    {
                        "sku": cp.product.sku,
                        "tax_class": cp.product.tax_class.idx if cp.product.tax_class else None,
                        "net": str(cp.net_value),
                        "gross": str(cp.gross_value),
                        "special_net": str(cp.special_net_value) if cp.special_net_value is not None else None,
                        "special_gross": str(cp.special_gross_value) if cp.special_gross_value is not None else None,
                        "special_from_date": cp.special_from_date.date().isoformat() if cp.special_from_date else None,
                        "special_to_date": cp.special_to_date.date().isoformat() if cp.special_to_date else None,
                        "country": cp.country.iso2,
                        "currency": cp.currency.iso3,
                        "tax_rate": str(cp.tax_rate.rate) if cp.tax_rate else "0.0000",
                    }
                )
            return paginator.get_paginated_response(items)

        # Grouped mode: paginate on distinct SKUs, return per-country breakdown
        sku_qs = (
            CurrentPrice.objects.filter(**base_filters)
            .values_list("product__sku", flat=True)
            .distinct()
            .order_by("product__sku")
        )
        page_skus = paginator.paginate_queryset(sku_qs, request)

        # Fetch prices only for current page's SKUs
        prices = (
            CurrentPrice.objects.filter(**base_filters, product__sku__in=page_skus)
            .select_related("product__tax_class", "country", "currency", "tax_rate")
            .order_by("product__sku", "country__iso2")
        )
        grouped = {sku: list(grp) for sku, grp in groupby(prices, key=lambda cp: cp.product.sku)}
        items = [_build_price_list_item(sku, grouped.get(sku, [])) for sku in page_skus]
        return paginator.get_paginated_response([item.model_dump() for item in items])

    @extend_schema(
        summary="Retrieve price detail by SKU",
        description=(
            "Returns the full per-country price breakdown for a single SKU within the given channel, "
            "including the channel's calculate_direction."
        ),
        parameters=[_CHANNEL_IDX_PARAM, _SKU_PARAM],
        responses={
            200: PriceDetailResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel or product not found"},
        },
    )
    def retrieve(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        prices = (
            CurrentPrice.objects.filter(
                channel=channel,
                product__sku__iexact=sku,
                product_parent__isnull=True,
                customer_representation__isnull=True,
            )
            .select_related("product__tax_class", "country", "currency", "tax_rate")
            .order_by("country__iso2")
        )
        if not prices.exists():
            product = get_object_or_404(ProductRepresentation, sku__iexact=sku)
            tax_class = product.tax_class.idx
        else:
            tax_class = prices[0].product.tax_class.idx

        purchase_costs = (
            PurchaseCost.objects.filter(channel=channel, product__sku__iexact=sku)
            .select_related("country", "currency")
            .order_by("country__iso2")
        )

        direction_map = {0: "from_net_to_gross", 1: "from_gross_to_net"}
        response = PriceDetailResponse(
            sku=sku,
            tax_class=tax_class,
            calculate_direction=direction_map.get(channel.calculate_direction, "from_net_to_gross"),
            prices=[_current_price_to_country_response(cp) for cp in prices],
            purchase_costs=[_purchase_cost_to_response(pc) for pc in purchase_costs],
        )
        return Response(response.model_dump())

    @extend_schema(
        tags=["Prices"],
        summary="Preview price change",
        description=(
            "Calculates the per-country price breakdown for the given value without saving any data. "
            "Uses the channel's calculate_direction (net→gross or gross→net) and each country's tax rate."
        ),
        parameters=[_CHANNEL_IDX_PARAM, _SKU_PARAM],
        request=PriceEditRequest,
        responses={
            200: {"description": "Preview result with per-country net/gross breakdown"},
            400: {"description": "Validation error"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel or product not found"},
        },
    )
    def preview(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        data = _parse_price_edit_request(request.data)
        result = price_edit_service.preview_price(
            channel=channel,
            sku=sku,
            value=data.value,
            special_value=data.special_value,
            special_from=data.special_from_date,
            special_to=data.special_to_date,
        )
        return Response({"sku": sku, "preview": result})

    @extend_schema(
        summary="Update price for SKU",
        description=(
            "Saves a price change for the given SKU across all countries in the channel. "
            "Propagates net/gross values using each country's tax rate. "
            "Creates PriceHistory entries for every updated CurrentPrice row."
        ),
        parameters=[_CHANNEL_IDX_PARAM, _SKU_PARAM],
        request=PriceEditRequest,
        responses={
            200: PricePatchResponse,
            400: {"description": "Validation error"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel or product not found"},
        },
    )
    def partial_update(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        data = _parse_price_edit_request(request.data)
        if data is None:
            return Response(status=400)

        def _parse_date(val):
            if not val:
                return None
            try:
                dt = datetime.fromisoformat(val)
            except (ValueError, TypeError):
                raise DRFValidationError({"special_from_date": ["Invalid date format."]})
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

        updated = price_edit_service.edit_price(
            channel=channel,
            sku=sku,
            value=data.value,
            currency_code=data.currency_code,
            special_value=data.special_value,
            special_from=_parse_date(data.special_from_date),
            special_to=_parse_date(data.special_to_date),
            user=request.user,
        )
        direction_map = {0: "from_net_to_gross", 1: "from_gross_to_net"}
        tax_class = updated[0].product.tax_class.idx if updated else ""
        response = PricePatchResponse(
            sku=sku,
            tax_class=tax_class,
            calculate_direction=direction_map.get(channel.calculate_direction, "from_net_to_gross"),
            prices=[_current_price_to_country_response(cp) for cp in updated],
            changes_logged=len(updated),
        )
        return Response(response.model_dump())

    @extend_schema(
        tags=["Prices"],
        summary="Flush special prices for SKU",
        description="Clears all special price values and promo dates for the given SKU in this channel. History is preserved.",
        parameters=[_CHANNEL_IDX_PARAM, _SKU_PARAM],
        responses={
            200: {"description": "Special prices cleared"},
            404: {"description": "Channel or product not found"},
        },
    )
    def flush_special(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        currency = request.query_params.get("currency")
        count = price_edit_service.flush_special_prices(channel, sku, currency_code=currency, user=request.user)
        if not count:
            return Response({"detail": "No prices found for this SKU."}, status=404)
        return Response({"flushed": count})

    @extend_schema(
        tags=["Prices"],
        summary="Delete all prices for SKU",
        description="Removes all CurrentPrice rows for the given SKU in this channel. History is preserved.",
        parameters=[_CHANNEL_IDX_PARAM, _SKU_PARAM],
        responses={
            204: {"description": "Prices deleted"},
            404: {"description": "Channel or product not found"},
        },
    )
    def destroy(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        currency = request.query_params.get("currency")
        price_edit_service.delete_prices(channel, sku, currency_code=currency, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Prices"],
        summary="List price history for SKU",
        description=(
            "Returns paginated price history entries for the given SKU and channel. "
            "Supports filtering by country ISO2 code and date range."
        ),
        parameters=[
            _CHANNEL_IDX_PARAM,
            _SKU_PARAM,
            OpenApiParameter(name="country", description="Filter by ISO2 country code (e.g. PL)", required=False),
            OpenApiParameter(
                name="from", description="Filter entries from this date (YYYY-MM-DD, inclusive)", required=False
            ),
            OpenApiParameter(
                name="to", description="Filter entries up to this date (YYYY-MM-DD, inclusive)", required=False
            ),
            OpenApiParameter(name="page", description="Page number", required=False),
            OpenApiParameter(name="page_size", description="Items per page (max 100)", required=False),
        ],
        responses={
            200: PriceHistoryEntryResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel not found"},
        },
    )
    def history(self, request, channel_idx: str | None = None, sku: str | None = None) -> Response:
        get_object_or_404(Channel, idx=channel_idx)
        qs = (
            PriceHistory.objects.filter(channel__idx=channel_idx, product__sku__iexact=sku)
            .select_related("country", "currency", "tax_rate", "changed_by")
            .order_by("-created_at")
        )
        country = request.query_params.get("country")
        if country:
            qs = qs.filter(country__iso2__iexact=country)
        from_date = request.query_params.get("from")
        if from_date:
            qs = qs.filter(created_at__date__gte=from_date)
        to_date = request.query_params.get("to")
        if to_date:
            qs = qs.filter(created_at__date__lte=to_date)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        items = [_history_entry_to_response(entry) for entry in page]
        return paginator.get_paginated_response([item.model_dump() for item in items])

    @extend_schema(
        tags=["Prices"],
        summary="Bulk update prices",
        description=(
            "Saves prices for multiple SKUs in one request. Each SKU propagates to all countries. "
            "Errors per SKU are collected without stopping the batch."
        ),
        parameters=[_CHANNEL_IDX_PARAM],
        request=BulkPriceEditRequest,
        responses={
            200: BulkPricePatchResponse,
            400: {"description": "Validation error"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel not found"},
        },
    )
    def bulk_update(self, request, channel_idx: str | None = None) -> Response:
        channel = get_object_or_404(Channel, idx=channel_idx)
        try:
            data = BulkPriceEditRequest(**request.data)
        except ValidationError as exc:
            from django_utils.api.v2_errors import raise_pydantic_as_drf

            raise_pydantic_as_drf(exc)

        def _parse_date(val):
            if not val:
                return None
            dt = datetime.fromisoformat(val)
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

        items = []
        for item in data.items:
            items.append(
                {
                    "sku": item.sku,
                    "value": item.value,
                    "special_value": item.special_value,
                    "special_from_date": _parse_date(item.special_from_date),
                    "special_to_date": _parse_date(item.special_to_date),
                    "tax_class_idx": item.tax_class_idx,
                }
            )

        result = price_edit_service.bulk_edit_prices(
            channel=channel, items=items, currency_code=data.currency_code, user=request.user
        )
        return Response(BulkPricePatchResponse(**result).model_dump())

    @extend_schema(
        tags=["Prices"],
        summary="List products with price status",
        description="Returns all ProductRepresentations with has_price flag for the given channel and currency.",
        parameters=[
            _CHANNEL_IDX_PARAM,
            OpenApiParameter(name="currency", description="Filter by currency code", required=True),
            OpenApiParameter(
                name="has_price", description="Filter: true=with price, false=without price", required=False
            ),
            OpenApiParameter(name="search", description="Search by SKU substring", required=False),
            OpenApiParameter(name="page", description="Page number", required=False),
            OpenApiParameter(name="page_size", description="Items per page (max 100)", required=False),
        ],
        responses={
            200: {"description": "Paginated list of products with has_price flag"},
            400: {"description": "currency query param is required"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Channel not found"},
        },
    )
    def products(self, request, channel_idx: str | None = None) -> Response:
        from django.db.models import Exists, OuterRef

        channel = get_object_or_404(Channel, idx=channel_idx)
        currency_code = request.query_params.get("currency")
        if not currency_code:
            return Response({"detail": "currency query param is required"}, status=400)

        qs = ProductRepresentation.objects.all().order_by("sku")
        qs = qs.annotate(
            has_price=Exists(
                CurrentPrice.objects.filter(
                    product=OuterRef("pk"),
                    channel=channel,
                    currency__iso3__iexact=currency_code,
                    customer_representation__isnull=True,
                    product_parent__isnull=True,
                )
            )
        )

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(sku__icontains=search)

        has_price_filter = request.query_params.get("has_price")
        if has_price_filter == "true":
            qs = qs.filter(has_price=True)
        elif has_price_filter == "false":
            qs = qs.filter(has_price=False)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        results = [
            {"sku": p.sku, "tax_class": p.tax_class.idx if p.tax_class else None, "has_price": p.has_price}
            for p in page
        ]
        return paginator.get_paginated_response(results)
