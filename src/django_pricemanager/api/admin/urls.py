# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.urls import path

from django_pricemanager.api.admin.views.channel_views import ChannelViewSet
from django_pricemanager.api.admin.views.price_views import PriceViewSet
from django_pricemanager.api.admin.views.tax_class_views import TaxClassViewSet

channel_list = ChannelViewSet.as_view({"get": "list", "post": "create"})
channel_detail = ChannelViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})
channel_sync = ChannelViewSet.as_view({"post": "sync"})

tax_class_list = TaxClassViewSet.as_view({"get": "list", "post": "create"})
tax_class_detail = TaxClassViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})
tax_rate_create = TaxClassViewSet.as_view({"post": "create_rate"})
tax_rate_detail = TaxClassViewSet.as_view({"patch": "update_rate", "delete": "destroy_rate"})

price_list = PriceViewSet.as_view({"get": "list"})
price_bulk = PriceViewSet.as_view({"patch": "bulk_update"})
price_products = PriceViewSet.as_view({"get": "products"})
price_detail = PriceViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})
price_flush_special = PriceViewSet.as_view({"post": "flush_special"})
price_preview = PriceViewSet.as_view({"post": "preview"})
price_history = PriceViewSet.as_view({"get": "history"})

urlpatterns = [
    # Channels (global)
    path("channels/", channel_list, name="pricemanager-channel-list"),
    path("channels/sync/", channel_sync, name="pricemanager-channel-sync"),
    path("channels/<str:idx>/", channel_detail, name="pricemanager-channel-detail"),
    # Tax Classes (global)
    path("tax-classes/", tax_class_list, name="pricemanager-taxclass-list"),
    path("tax-classes/<str:idx>/", tax_class_detail, name="pricemanager-taxclass-detail"),
    path("tax-classes/<str:idx>/rates/", tax_rate_create, name="pricemanager-taxrate-create"),
    path("tax-classes/<str:idx>/rates/<str:country_iso2>/", tax_rate_detail, name="pricemanager-taxrate-detail"),
    # Prices (channel-scoped)
    path("<str:channel_idx>/prices/", price_list, name="pricemanager-price-list"),
    path("<str:channel_idx>/prices/bulk/", price_bulk, name="pricemanager-price-bulk"),
    path("<str:channel_idx>/prices/products/", price_products, name="pricemanager-price-products"),
    # <path:sku> matches slashes (slash-suffixed SKUs like "1C01/N"); the price sub-routes
    # MUST precede the bare detail or a greedy detail match would swallow "<sku>/preview" etc.
    path(
        "<str:channel_idx>/prices/<path:sku>/flush-special/",
        price_flush_special,
        name="pricemanager-price-flush-special",
    ),
    path("<str:channel_idx>/prices/<path:sku>/preview/", price_preview, name="pricemanager-price-preview"),
    path("<str:channel_idx>/prices/<path:sku>/history/", price_history, name="pricemanager-price-history"),
    path("<str:channel_idx>/prices/<path:sku>/", price_detail, name="pricemanager-price-detail"),
]
