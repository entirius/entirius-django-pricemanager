# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django.db.models import UniqueConstraint


class CustomerRepresentation(models.Model):
    uid = models.CharField(max_length=128, null=False)
    user_email = models.CharField(max_length=256, null=False)
    objects = models.Manager()

    def __str__(self):
        return f"{self.uid} ({self.user_email})"

    class Meta:
        verbose_name_plural = "customers representations"
        constraints = [UniqueConstraint("uid", name="unique_pricemanager_customer_uid")]
