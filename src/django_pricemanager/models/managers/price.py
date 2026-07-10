# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db.models import BooleanField, Case, QuerySet, Value, When
from django.utils import timezone
from django_utils.managers.enhance_manager import EnhanceManager

from django_pricemanager.settings import APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES


class PriceQuerySet(QuerySet):
    def with_eligibility_for_special_price(self):
        current_date = timezone.now()
        return self.annotate(
            is_egible_for_special_price=Case(
                When(
                    special_from_date__isnull=False,
                    special_to_date__isnull=False,
                    special_from_date__lt=current_date,
                    special_to_date__gt=current_date,
                    then=Value(True),
                ),
                When(
                    special_from_date__isnull=False,
                    special_from_date__lt=current_date,
                    special_to_date__isnull=True,
                    then=Value(True),
                ),
                When(
                    special_from_date__isnull=True,
                    special_to_date__isnull=False,
                    special_to_date__gt=current_date,
                    then=Value(True),
                ),
                *(
                    [When(special_to_date__isnull=True, special_from_date__isnull=True, then=Value(True))]
                    if APPLIED_SPECIAL_PRICE_WHEN_NULL_VALIDITY_DATES
                    else []
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

    def only_products(self):
        """
        Only simple products, no components of bundles and no attributes
        """
        return self.filter(product__isnull=False, attrs__isnull=True, product_parent__isnull=True)


class PriceManager(EnhanceManager):
    def get_queryset(self):
        return PriceQuerySet(self.model, using=self._db)

    def with_eligibility_for_special_price(self):
        return self.get_queryset().with_eligibility_for_special_price()

    def only_products(self):
        return self.get_queryset().only_products()
