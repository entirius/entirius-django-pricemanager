# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import csv

from django.contrib import admin
from django.http import HttpResponse

from django_pricemanager.services.pricelist_service import read_from_file
from django_pricemanager.services.tax_class_service import read_from_csv

from .models import (
    AttributeRepresentation,
    Channel,
    CurrentPrice,
    CustomerRepresentation,
    Price,
    PriceHistory,
    PriceList,
    ProductRepresentation,
    PurchaseCost,
    SaleChannel,
    TaxClass,
    TaxRate,
)


class PriceAdmin(admin.ModelAdmin):
    list_display = (
        "pricelist",
        "get_channel",
        "created_at",
        "updated_at",
        "product",
        "product_parent",
        "list_attrs",
        "net_value",
        "gross_value",
        "special_net_value",
        "special_gross_value",
        "special_from_date",
        "special_to_date",
        "get_taxrate",
    )
    search_fields = ("product__sku", "attrs__idx", "product_parent__sku")
    autocomplete_fields = ("product", "product_parent")

    readonly_fields = ("created_at",)
    list_filter = (
        "pricelist",
        "pricelist__sale_channel",
        "pricelist__sale_channel__channel",
        "pricelist__sale_channel__country",
        "pricelist__currency",
        "pricelist__status",
        ("product", admin.EmptyFieldListFilter),
        ("product_parent", admin.EmptyFieldListFilter),
    )

    def list_attrs(self, obj):
        return ", ".join(obj.attrs.all().values_list("idx", flat=True))

    @admin.display(description="Tax Rate")
    def get_taxrate(self, obj):
        if obj.tax_rate:
            return obj.tax_rate.rate
        else:
            return None

    @admin.display(description="Channel")
    def get_channel(self, obj):
        if obj.pricelist.sale_channel and obj.pricelist.sale_channel.channel:
            return obj.pricelist.sale_channel.channel
        return None


class PricelistAdmin(admin.ModelAdmin):
    list_display = ("sale_channel", "currency", "country", "name", "status", "created_on")
    # readonly_fields = ('channel', 'currency', 'country', 'name', 'status','created_on' )
    readonly_fields = ["created_on"]
    # inlines = [PriceInline] # to zabija
    list_filter = (
        "sale_channel__channel",
        "sale_channel__customer_representation",
        "sale_channel__country",
        "currency",
        "status",
    )
    actions = ["export_as_csv"]

    def save_model(self, request, obj: PriceList, form, change):
        it = super().save_model(request, obj, form, change)
        if obj.source_file:
            path = obj.source_file.path
            if not change:
                result = read_from_file(obj)
                obj.status = result
                obj.save()

    def export_as_csv(self, request, rset):
        if rset.count() > 1:
            request.messages.error("Cannot export more than one pricelist")
        else:
            item = rset.first()
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = "attachment; filename=pricelist_%s.csv" % item.id

            headers, lines = item.get_as_csv()
            writer = csv.DictWriter(response, fieldnames=headers)
            writer.writeheader()
            writer.writerows(lines)

            return response


class TaxRateInline(admin.TabularInline):
    model = TaxRate


class TaxClassAdmin(admin.ModelAdmin):
    inlines = [TaxRateInline]

    def save_model(self, request, obj: TaxClass, form, change):
        item = super().save_model(request, obj, form, change)
        if obj.source_file:
            read_from_csv(obj)


class ChannelAdmin(admin.ModelAdmin):
    list_display = ("idx", "name", "default_country")
    filter_horizontal = ("calculate_countries",)
    raw_id_fields = ("default_country",)


class SaleChannelAdmin(admin.ModelAdmin):
    list_display = (
        "channel",
        "idx",
        "name",
        "price_source",
        "country",
        "is_only_for_verified_user",
        "customer_representation",
    )
    search_fields = ("idx", "name")
    list_filter = ("channel", "customer_representation", "price_source")


class ProductRepresentationAdmin(admin.ModelAdmin):
    list_display = ("tax_class", "sku")
    search_fields = ("sku",)


class AttributeRepresentationAdmin(admin.ModelAdmin):
    list_display = ("tax_class", "idx")
    search_fields = ("idx",)


class TaxRateAdmin(admin.ModelAdmin):
    list_display = ("tax_class", "country", "rate")
    search_fields = ("country",)


class CustomerRepresentationAdmin(admin.ModelAdmin):
    list_display = ("uid", "user_email")
    search_fields = ("uid", "user_email")


admin.site.register(ProductRepresentation, ProductRepresentationAdmin)
admin.site.register(AttributeRepresentation, AttributeRepresentationAdmin)
admin.site.register(Price, PriceAdmin)
admin.site.register(PriceList, PricelistAdmin)
admin.site.register(TaxClass, TaxClassAdmin)
admin.site.register(TaxRate, TaxRateAdmin)
admin.site.register(Channel, ChannelAdmin)
admin.site.register(SaleChannel, SaleChannelAdmin)
admin.site.register(CustomerRepresentation, CustomerRepresentationAdmin)


class CurrentPriceAdmin(admin.ModelAdmin):
    list_display = ("product", "channel", "country", "currency", "net_value", "gross_value", "source", "modified_at")
    search_fields = ("product__sku",)
    list_filter = ("channel", "country", "currency", "source")
    readonly_fields = ("created_at", "modified_at")


class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "channel", "country", "currency", "gross_value", "net_value", "source", "created_at")
    search_fields = ("product__sku",)
    list_filter = ("channel", "country", "source")
    readonly_fields = ("product", "channel", "country", "currency", "gross_value", "net_value", "source", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PurchaseCostAdmin(admin.ModelAdmin):
    list_display = ("product", "channel", "country", "currency", "net_cost", "supplier_idx", "modified_at")
    search_fields = ("product__sku", "supplier_idx")
    list_filter = ("channel", "country", "currency", "supplier_idx")
    readonly_fields = ("created_at", "modified_at")


admin.site.register(CurrentPrice, CurrentPriceAdmin)
admin.site.register(PurchaseCost, PurchaseCostAdmin)
admin.site.register(PriceHistory, PriceHistoryAdmin)


from .models import PriceManagerSettings


class PriceManagerSettingsAdmin(admin.ModelAdmin):
    list_display = ("matrix_signals_enabled", "read_from_current")

    def has_add_permission(self, request):
        return not PriceManagerSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    # Cache invalidation handled in PriceManagerSettings.save()


admin.site.register(PriceManagerSettings, PriceManagerSettingsAdmin)
