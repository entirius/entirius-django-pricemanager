# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django_regional.models import Country
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from idx_normalizator import normalize_idx
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricemanager.api.admin.permissions import IsAdminUser
from django_pricemanager.models import ProductRepresentation, TaxClass, TaxRate
from django_pricemanager.schemas.requests.tax_class import (
    TaxClassCreateRequest,
    TaxRateCreateRequest,
    TaxRateUpdateRequest,
)
from django_pricemanager.schemas.responses.tax_class import TaxClassListItemResponse, TaxClassResponse, TaxRateResponse
from django_pricemanager.tasks import recalculate_prices_for_tax_change


def _tax_rate_response(rate: TaxRate) -> dict:
    return TaxRateResponse(
        country=rate.country.iso2,
        country_name=rate.country.name_en,
        rate=str(rate.rate),
        percent=f"{rate.percent_rate:.2f}%",
    ).model_dump()


def _tax_class_detail(tax_class: TaxClass) -> dict:
    rates = [_tax_rate_response(r) for r in tax_class.tax_rates.select_related("country").all()]
    product_count = ProductRepresentation.objects.filter(tax_class=tax_class).count()
    return TaxClassResponse(
        id=tax_class.pk, idx=tax_class.idx, name=tax_class.name, rates=rates, product_count=product_count
    ).model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Tax Classes"]),
    retrieve=extend_schema(tags=["Tax Classes"]),
    create=extend_schema(tags=["Tax Classes"]),
    partial_update=extend_schema(tags=["Tax Classes"]),
    destroy=extend_schema(tags=["Tax Classes"]),
)
class TaxClassViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List tax classes",
        description="Returns all tax classes with per-country rate count.",
        responses={200: TaxClassListItemResponse},
    )
    def list(self, request) -> Response:
        tax_classes = TaxClass.objects.prefetch_related("tax_rates").order_by("name")
        items = [
            TaxClassListItemResponse(id=tc.pk, idx=tc.idx, name=tc.name, rate_count=tc.tax_rates.count()).model_dump()
            for tc in tax_classes
        ]
        return Response(items)

    @extend_schema(
        summary="Retrieve tax class",
        description="Returns tax class detail with inline per-country rates and product count.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Tax class slug identifier")],
        responses={200: TaxClassResponse, 404: {"description": "Tax class not found"}},
    )
    def retrieve(self, request, idx: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.prefetch_related("tax_rates__country").get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None
        return Response(_tax_class_detail(tax_class))

    @extend_schema(
        summary="Create tax class",
        description="Creates a new tax class. The idx is auto-generated from the name.",
        responses={201: TaxClassResponse, 400: {"description": "Validation error"}},
    )
    def create(self, request) -> Response:
        try:
            data = TaxClassCreateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        idx = normalize_idx(data.name)
        tax_class = TaxClass.objects.create(name=data.name, idx=idx)
        return Response(_tax_class_detail(tax_class), status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update tax class",
        description="Updates the tax class name.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Tax class slug identifier")],
        responses={
            200: TaxClassResponse,
            400: {"description": "Validation error"},
            404: {"description": "Tax class not found"},
        },
    )
    def partial_update(self, request, idx: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.prefetch_related("tax_rates__country").get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None

        try:
            data = TaxClassCreateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        tax_class.name = data.name
        tax_class.save()
        return Response(_tax_class_detail(tax_class))

    @extend_schema(
        summary="Delete tax class",
        description="Deletes the tax class. Returns 400 if any ProductRepresentations reference it.",
        parameters=[OpenApiParameter(name="idx", location="path", description="Tax class slug identifier")],
        responses={
            204: {"description": "Deleted successfully"},
            400: {"description": "Tax class has associated products"},
            404: {"description": "Tax class not found"},
        },
    )
    def destroy(self, request, idx: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None

        if ProductRepresentation.objects.filter(tax_class=tax_class).exists():
            raise DRFValidationError(
                {"detail": "Cannot delete tax class with associated products. Reassign products first."}
            )

        tax_class.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Create tax rate",
        description="Adds a per-country tax rate to the tax class.",
        tags=["Tax Classes"],
        parameters=[OpenApiParameter(name="idx", location="path", description="Tax class slug identifier")],
        responses={
            201: TaxRateResponse,
            400: {"description": "Validation error or rate already exists for country"},
            404: {"description": "Tax class or country not found"},
        },
    )
    def create_rate(self, request, idx: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None

        try:
            data = TaxRateCreateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        try:
            country = Country.objects.get(iso2=data.country_code.upper())
        except Country.DoesNotExist:
            raise NotFound(f"Country '{data.country_code}' not found.") from None

        if TaxRate.objects.filter(tax_class=tax_class, country=country).exists():
            raise DRFValidationError(
                {"detail": f"Tax rate for country '{data.country_code}' already exists on this tax class."}
            )

        rate = TaxRate.objects.create(tax_class=tax_class, country=country, rate=data.rate)
        return Response(_tax_rate_response(rate), status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update tax rate",
        description="Updates the tax rate for a country and triggers price recalculation via Celery.",
        tags=["Tax Classes"],
        parameters=[
            OpenApiParameter(name="idx", location="path", description="Tax class slug identifier"),
            OpenApiParameter(name="country_iso2", location="path", description="ISO 3166-1 alpha-2 country code"),
        ],
        responses={
            200: TaxRateResponse,
            400: {"description": "Validation error"},
            404: {"description": "Tax class, country, or rate not found"},
        },
    )
    def update_rate(self, request, idx: str | None = None, country_iso2: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None

        try:
            country = Country.objects.get(iso2=country_iso2.upper())
        except Country.DoesNotExist:
            raise NotFound(f"Country '{country_iso2}' not found.") from None

        try:
            rate = TaxRate.objects.select_related("country").get(tax_class=tax_class, country=country)
        except TaxRate.DoesNotExist:
            raise NotFound(f"Tax rate for country '{country_iso2}' not found on tax class '{idx}'.") from None

        try:
            data = TaxRateUpdateRequest(**request.data)
        except ValidationError as exc:
            raise DRFValidationError(exc.errors()) from exc

        rate.rate = data.rate
        rate.save()

        recalculate_prices_for_tax_change.delay(tax_class_idx=idx, country_iso2=country_iso2.upper())

        return Response(_tax_rate_response(rate))

    @extend_schema(
        summary="Delete tax rate",
        description="Removes the per-country tax rate from the tax class.",
        tags=["Tax Classes"],
        parameters=[
            OpenApiParameter(name="idx", location="path", description="Tax class slug identifier"),
            OpenApiParameter(name="country_iso2", location="path", description="ISO 3166-1 alpha-2 country code"),
        ],
        responses={
            204: {"description": "Deleted successfully"},
            404: {"description": "Tax class, country, or rate not found"},
        },
    )
    def destroy_rate(self, request, idx: str | None = None, country_iso2: str | None = None) -> Response:
        try:
            tax_class = TaxClass.objects.get(idx=idx)
        except TaxClass.DoesNotExist:
            raise NotFound(f"Tax class '{idx}' not found.") from None

        try:
            country = Country.objects.get(iso2=country_iso2.upper())
        except Country.DoesNotExist:
            raise NotFound(f"Country '{country_iso2}' not found.") from None

        try:
            rate = TaxRate.objects.get(tax_class=tax_class, country=country)
        except TaxRate.DoesNotExist:
            raise NotFound(f"Tax rate for country '{country_iso2}' not found on tax class '{idx}'.") from None

        rate.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
