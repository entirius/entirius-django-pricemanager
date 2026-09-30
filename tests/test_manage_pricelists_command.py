# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression: manage-pricelists must be a no-op when nothing exists."""

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_channels_is_noop_exit_zero():
    out = StringIO()
    call_command("manage-pricelists", stdout=out)
    assert "No Channels" in out.getvalue()


@pytest.mark.django_db
def test_unknown_channel_idx_is_noop_exit_zero():
    out = StringIO()
    call_command("manage-pricelists", channel_idx="does-not-exist", stdout=out)
    assert "No Channels" in out.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("celery_task", [False, True])
def test_channel_without_source_pricelist_is_noop_exit_zero(celery_task):
    from django_pricemanager.models import Channel

    Channel.objects.create(idx="empty-shop", name="Empty shop")
    out = StringIO()
    call_command("manage-pricelists", celery_task=celery_task, stdout=out)
    assert "No price list" in out.getvalue()
