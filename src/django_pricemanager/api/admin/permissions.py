# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from rest_framework.permissions import IsAdminUser as DRFIsAdminUser


class IsAdminUser(DRFIsAdminUser):
    """Admin permission: is_staff or is_superuser."""

    def has_permission(self, request, view):
        return bool(request.user and (request.user.is_staff or request.user.is_superuser))
