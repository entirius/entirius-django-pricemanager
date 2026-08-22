# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Data-path test for migration 0025: Channel.idx dedupe before the unique constraint.

No prior migration enforced Channel.idx uniqueness, so a duplicate row would otherwise
abort the deploy the moment AddConstraint runs. Roll back to 0024 (pre-constraint), seed
two Channels sharing an idx, migrate forward, and assert the constraint is now enforced
and the duplicate was renamed rather than the migration crashing.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

APP = "django_pricemanager"
BEFORE = "0001_squashed_0024_remove_currentprice_supplier_cost_fields"
AFTER = "0027_channel_baseline_enabled_baselineconfig_and_more"

pytestmark = pytest.mark.django_db(transaction=True)


def _migrate_to(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    state = executor.loader.project_state((APP, target)).apps
    executor.loader.build_graph()  # reset graph for the next migrate() call
    return state


def _leaf_migration():
    """Resolve the current HEAD migration name, so cleanup tracks it as later migrations land."""
    executor = MigrationExecutor(connection)
    ((_, leaf_name),) = executor.loader.graph.leaf_nodes(APP)
    return leaf_name


def test_0025_dedupes_duplicate_channel_idx_before_constraint():
    try:
        old = _migrate_to(BEFORE)
        Channel = old.get_model(APP, "Channel")
        first = Channel.objects.create(idx="mig-test-dup", name="First")
        second = Channel.objects.create(idx="mig-test-dup", name="Second")

        new = _migrate_to(AFTER)
        ChannelNew = new.get_model(APP, "Channel")

        idxs = set(ChannelNew.objects.filter(pk__in=[first.pk, second.pk]).values_list("idx", flat=True))
        assert len(idxs) == 2  # no longer collide
        assert ChannelNew.objects.get(pk=first.pk).idx == "mig-test-dup"  # lowest pk keeps its idx
        assert ChannelNew.objects.get(pk=second.pk).idx != "mig-test-dup"
    finally:
        _migrate_to(_leaf_migration())  # leave the schema at HEAD for the rest of the suite
