"""Data update coordinator for Fossibot integration."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN
from .sydpower.connector import SydpowerConnector

_LOGGER = logging.getLogger(__name__)


class FossibotDataUpdateCoordinator(DataUpdateCoordinator):
    """Fossibot data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: Dict[str, Any],
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

        self.connector = SydpowerConnector(
            config.get("username"),
            config.get("password"),
            developer_mode=config.get("developer_mode", False),
        )
        self._shutdown_event = asyncio.Event()
        self._failed_updates_count = 0
        self._last_successful_update = time.time()
        self._reconnection_in_progress = False
        self._health_check_task = None

    def start_health_check(self) -> None:
        """Start the health check background task.

        Must be called after the coordinator is registered with hass
        (i.e. after async_config_entry_first_refresh).
        """
        self._health_check_task = self.hass.async_create_task(
            self._health_check_loop()
        )
        self._health_check_task.add_done_callback(
            self._handle_health_check_done
        )
        _LOGGER.debug("Health check task started")

    @callback
    def _handle_health_check_done(self, task: asyncio.Task) -> None:
        """Handle health check task completion."""
        try:
            task.result()
        except asyncio.CancelledError:
            _LOGGER.debug("Health check task was properly cancelled")
        except Exception:
            _LOGGER.exception("Unexpected error in health check task")

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data via library."""
        if self._reconnection_in_progress:
            _LOGGER.debug("Reconnection in progress, skipping data update")
            return self.data if self.data else {}

        try:
            start = asyncio.get_event_loop().time()

            try:
                data = await asyncio.wait_for(
                    self.connector.get_data(), timeout=30.0
                )
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for data")
                data = {}

            duration = asyncio.get_event_loop().time() - start
            _LOGGER.debug(
                "Data fetch completed in %.3f seconds (success: %s)",
                duration,
                bool(data),
            )

            if not data:
                self._failed_updates_count += 1
                _LOGGER.warning(
                    "Empty data after %.2fs. Consecutive failures: %d",
                    duration,
                    self._failed_updates_count,
                )

                if (
                    self._failed_updates_count >= 2
                    and not self._reconnection_in_progress
                ):
                    self._trigger_reconnection()

                if self.data:
                    return self.data

                raise UpdateFailed("No data received from device")

            self._failed_updates_count = 0
            self._last_successful_update = time.time()
            return data

        except UpdateFailed:
            raise
        except Exception as err:
            self._failed_updates_count += 1
            _LOGGER.error(
                "Error fetching data: %s (consecutive failures: %d)",
                err,
                self._failed_updates_count,
            )

            if (
                self._failed_updates_count >= 2
                and not self._reconnection_in_progress
            ):
                self._trigger_reconnection()

            if self.data:
                return self.data

            raise UpdateFailed(f"Error fetching data: {err}") from err

    def _trigger_reconnection(self):
        """Trigger reconnection without blocking updates."""
        _LOGGER.warning(
            "Multiple consecutive failures, initiating reconnection"
        )
        self._reconnection_in_progress = True
        self.hass.async_create_task(self._handle_reconnection())

    async def _handle_reconnection(self):
        """Handle reconnection in background."""
        try:
            _LOGGER.info("Starting background reconnection")
            success = await self.connector.reconnect()

            if success:
                _LOGGER.info("Reconnection successful")
                await self.async_refresh()
            else:
                _LOGGER.error("Reconnection failed")
        except Exception:
            _LOGGER.exception("Error during reconnection")
        finally:
            self._reconnection_in_progress = False

    async def _health_check_loop(self):
        """Periodically check connection health and reconnect if needed."""
        _LOGGER.info("Health check loop started")

        try:
            while not self._shutdown_event.is_set():
                try:
                    time_since_update = (
                        time.time() - self._last_successful_update
                    )

                    if (
                        time_since_update > 300
                        and not self._reconnection_in_progress
                    ):
                        _LOGGER.warning(
                            "No successful updates in %.1f seconds, "
                            "forcing reconnection",
                            time_since_update,
                        )
                        self._trigger_reconnection()

                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(), timeout=60
                        )
                    except asyncio.TimeoutError:
                        pass

                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("Error in health check loop")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            _LOGGER.debug("Health check loop cancelled")

    async def async_shutdown(self) -> None:
        """Shut down the coordinator."""
        _LOGGER.debug("Shutting down coordinator")
        self._shutdown_event.set()

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self.connector:
            await self.connector.disconnect()

        _LOGGER.debug("Coordinator shutdown complete")
