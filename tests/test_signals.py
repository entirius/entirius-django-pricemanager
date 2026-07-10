# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the signal-driven price→matrix sync infrastructure."""

from unittest.mock import MagicMock, patch

import pytest

from django_pricemanager.signals.killswitch import (
    is_matrix_signals_enabled,
    is_matrix_sync_suppressed,
    should_skip,
    suppress_price_matrix_signals,
)

# ---------------------------------------------------------------------------
# Kill-switch: suppress context manager
# ---------------------------------------------------------------------------


class TestSuppressContextManager:
    def test_single_suppress(self):
        assert not is_matrix_sync_suppressed()
        with suppress_price_matrix_signals():
            assert is_matrix_sync_suppressed()
        assert not is_matrix_sync_suppressed()

    def test_nested_suppress(self):
        with suppress_price_matrix_signals():
            assert is_matrix_sync_suppressed()
            with suppress_price_matrix_signals():
                assert is_matrix_sync_suppressed()
            # Still suppressed at depth=1
            assert is_matrix_sync_suppressed()
        # Fully unsuppressed
        assert not is_matrix_sync_suppressed()


# ---------------------------------------------------------------------------
# Kill-switch: DB toggle + cache
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMatrixSignalsEnabled:
    def test_enabled_when_db_true(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = True
        s.save()
        assert is_matrix_signals_enabled() is True

    def test_disabled_when_db_false(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = False
        s.save()
        assert is_matrix_signals_enabled() is False

    def test_cache_used_on_second_call(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = True
        s.save()

        # First call populates cache
        assert is_matrix_signals_enabled() is True

        # Change DB but don't clear cache
        s.matrix_signals_enabled = False
        PriceManagerSettings.objects.filter(pk=1).update(matrix_signals_enabled=False)

        # Still returns cached True
        assert is_matrix_signals_enabled() is True

        # After cache clear, returns fresh value
        cache.clear()
        assert is_matrix_signals_enabled() is False

    def test_db_error_returns_false(self):
        from django.core.cache import cache

        cache.clear()
        # PriceManagerSettings is imported lazily inside the killswitch function — patch at source.
        with patch(
            "django_pricemanager.models.pm_settings.PriceManagerSettings.load",
            side_effect=Exception("DB down"),
        ):
            assert is_matrix_signals_enabled() is False


# ---------------------------------------------------------------------------
# Kill-switch: should_skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestShouldSkip:
    def test_skip_when_suppressed(self):
        with suppress_price_matrix_signals():
            assert should_skip("any-channel") is True

    def test_skip_when_disabled(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = False
        s.save()
        assert should_skip("default-europe") is True

    @patch("django_pricemanager.signals.killswitch.PRICEMANAGER_MATRIX_SIGNALS_CHANNEL_DENYLIST", ("blocked-channel",))
    def test_skip_when_channel_denylisted(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = True
        s.save()
        assert should_skip("blocked-channel") is True
        assert should_skip("default-europe") is False

    def test_not_skip_when_enabled_and_clear(self):
        from django.core.cache import cache

        from django_pricemanager.models import PriceManagerSettings

        cache.clear()
        s = PriceManagerSettings.load()
        s.matrix_signals_enabled = True
        s.save()
        assert should_skip("default-europe") is False


# ---------------------------------------------------------------------------
# Dispatch: enqueue_price_sync
# ---------------------------------------------------------------------------


class TestEnqueuePriceSync:
    @patch("django_pricemanager.signals.dispatch.current_app")
    @patch("django_pricemanager.signals.dispatch.caches")
    def test_enqueues_to_redis_and_schedules_task(self, mock_caches, mock_celery):
        from django_pricemanager.signals.dispatch import enqueue_price_sync

        mock_redis = MagicMock()
        mock_redis.set.return_value = True  # Lock acquired
        mock_caches.__getitem__.return_value.client.get_client.return_value = mock_redis

        enqueue_price_sync("ENT-S001", "default-europe")

        mock_redis.zadd.assert_called_once()
        assert "ENT-S001:default-europe" in str(mock_redis.zadd.call_args)
        mock_redis.expire.assert_called_once()
        mock_celery.send_task.assert_called_once()
        assert "flush_pending_matrix_sync" in str(mock_celery.send_task.call_args)

    @patch("django_pricemanager.signals.dispatch.current_app")
    @patch("django_pricemanager.signals.dispatch.caches")
    def test_does_not_reschedule_when_lock_held(self, mock_caches, mock_celery):
        from django_pricemanager.signals.dispatch import enqueue_price_sync

        mock_redis = MagicMock()
        mock_redis.set.return_value = None  # Lock already held
        mock_caches.__getitem__.return_value.client.get_client.return_value = mock_redis

        enqueue_price_sync("ENT-S001", "default-europe")

        mock_redis.zadd.assert_called_once()
        mock_celery.send_task.assert_not_called()

    @patch("django_pricemanager.signals.dispatch.caches")
    def test_redis_failure_does_not_raise(self, mock_caches):
        from django_pricemanager.signals.dispatch import enqueue_price_sync

        mock_caches.__getitem__.return_value.client.get_client.side_effect = Exception("Redis down")
        # Should not raise
        enqueue_price_sync("ENT-S001", "default-europe")


# ---------------------------------------------------------------------------
# Signal handlers: integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSignalHandlerIntegration:
    def test_save_fires_enqueue(self, prices_populated, mocker):
        mock_enqueue = mocker.patch("django_pricemanager.signals.handlers.enqueue_price_sync")
        mocker.patch("django_pricemanager.signals.handlers.should_skip", return_value=False)

        ns = prices_populated
        cp = ns.prices[0]
        cp.net_value = cp.net_value + 1
        cp.save()

        mock_enqueue.assert_called_once_with(cp.product.sku, cp.channel.idx)

    def test_save_skipped_when_suppressed(self, prices_populated, mocker):
        mock_enqueue = mocker.patch("django_pricemanager.signals.handlers.enqueue_price_sync")
        mocker.patch("django_pricemanager.signals.handlers.should_skip", return_value=True)

        ns = prices_populated
        cp = ns.prices[0]
        cp.net_value = cp.net_value + 1
        cp.save()

        mock_enqueue.assert_not_called()

    def test_delete_fires_enqueue(self, prices_populated, mocker):
        mock_enqueue = mocker.patch("django_pricemanager.signals.handlers.enqueue_price_sync")
        mocker.patch("django_pricemanager.signals.handlers.should_skip", return_value=False)

        ns = prices_populated
        cp = ns.prices[0]
        sku, idx = cp.product.sku, cp.channel.idx
        cp.delete()

        mock_enqueue.assert_called_with(sku, idx)
