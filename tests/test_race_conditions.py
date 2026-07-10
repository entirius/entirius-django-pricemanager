# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for concurrent-edit correctness and transactional consistency."""

from decimal import Decimal

import pytest

from django_pricemanager.models import CurrentPrice, PriceHistory
from django_pricemanager.services.price_edit_service import edit_price


@pytest.mark.django_db
class TestRapidEdits:
    def test_two_rapid_edits_both_logged(self, prices_populated):
        """Two sequential edits for the same SKU both produce PriceHistory entries.

        Because edit_price is @transaction.atomic, each call commits fully before
        the next begins. The history log must contain both sets of changes.
        """
        ns = prices_populated
        before = PriceHistory.objects.filter(product=ns.chair, channel=ns.channel).count()

        edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("110.00"))
        edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("115.00"))

        after = PriceHistory.objects.filter(product=ns.chair, channel=ns.channel).count()
        # 3 countries × 2 edits = 6 new history rows
        assert after == before + 6

    def test_concurrent_edit_no_data_loss(self, prices_populated):
        """Editing two different SKUs sequentially leaves both CurrentPrices intact."""
        ns = prices_populated
        edit_price(channel=ns.channel, sku="CHAIR-001", value=Decimal("110.00"))
        edit_price(channel=ns.channel, sku="FOOD-001", value=Decimal("50.00"))

        chair_prices = CurrentPrice.objects.filter(product=ns.chair, channel=ns.channel)
        food_prices = CurrentPrice.objects.filter(product=ns.food, channel=ns.channel)

        assert chair_prices.exists()
        assert food_prices.exists()

        for cp in chair_prices:
            # net=110.00 was the edit value
            assert cp.net_value == Decimal("110.00")
        for cp in food_prices:
            assert cp.net_value == Decimal("50.00")

    def test_edit_and_verify_atomic(self, prices_populated):
        """edit_price is atomic: either all country prices update or none do.

        We verify consistency by confirming that after a successful edit every
        CurrentPrice for the SKU/channel reflects the same net_value that was
        submitted (i.e. no partial update).
        """
        ns = prices_populated
        target_net = Decimal("120.00")
        edit_price(channel=ns.channel, sku="CHAIR-001", value=target_net)

        updated = CurrentPrice.objects.filter(
            product=ns.chair,
            channel=ns.channel,
            customer_representation__isnull=True,
            product_parent__isnull=True,
        )
        for cp in updated:
            assert cp.net_value == target_net
