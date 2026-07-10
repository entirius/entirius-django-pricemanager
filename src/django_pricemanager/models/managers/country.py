# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class CountryAwareQuerySet(models.QuerySet):
    """
    QuerySet który automatycznie obsługuje wyszukiwanie po country jako string (iso2)
    lub jako obiekt Country.
    """

    def get(self, *args, **kwargs):
        if "country" in kwargs and isinstance(kwargs["country"], str):
            country_code = kwargs.pop("country")
            kwargs["country__iso2"] = country_code

        return super().get(*args, **kwargs)

    def filter(self, *args, **kwargs):
        if "country" in kwargs and isinstance(kwargs["country"], str):
            country_code = kwargs.pop("country")
            kwargs["country__iso2"] = country_code

        return super().filter(*args, **kwargs)

    def exclude(self, *args, **kwargs):
        if "country" in kwargs and isinstance(kwargs["country"], str):
            country_code = kwargs.pop("country")
            kwargs["country__iso2"] = country_code

        return super().exclude(*args, **kwargs)


class CountryAwareManager(models.Manager):
    """
    Manager który używa CountryAwareQuerySet do obsługi wyszukiwania
    po country jako string (iso2) lub jako obiekt Country.
    """

    def get_queryset(self):
        return CountryAwareQuerySet(self.model, using=self._db)
