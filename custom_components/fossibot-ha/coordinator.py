"""Data update coordinator for Fossibot integration."""
import asyncio
import logging
import time
import json
from datetime import timedelta
from typing import Any, Dict, Optional, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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

        # Initialize our connector with the new modular code
        self.username = config.get("username")
        self.password = config.get("password")
        self.connector = SydpowerConnector(self.username, self.password)
        self._shutdown_event = asyncio.Event()
        self._failed_updates_count = 0
        self._last_successful_update = time.time()
        self._last_data_hash = None
        self._reconnection_in_progress = False
        
        # Initialize the health check task reference, but don't start it yet
        self._health_check_task = None

    async def async_added_to_hass(self) -> None:
        """When coordinator is added to hass."""
        await super().async_added_to_hass()
        
        # Start health check task only after we're added to HASS
        self._health_check_task = self.hass.async_create_task(self._health_check_loop())
        
        # Add proper error handler for the task
        self._health_check_task.add_done_callback(self._handle_health_check_done)
        
        _LOGGER.debug("Health check task started")

    @callback
    def _handle_health_check_done(self, task: asyncio.Task) -> None:
        """Handle health check task completion."""
        try:
            task.result()
        except asyncio.CancelledError:
            # This is expected when we cancel the task
            _LOGGER.debug("Health check task was properly cancelled")
        except Exception as err:  # pylint: disable=broad-except
            # This should not happen, but we want to log it if it does
            _LOGGER.exception("Unexpected error in health check task: %s", err)

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data via library."""
        try:
            # If reconnection is already in progress, don't try to fetch data
            if self._reconnection_in_progress:
                _LOGGER.debug("Reconnection in progress, skipping data update")
                # Return existing data if available
                return self.data if self.data else {}
            
            start = asyncio.get_event_loop().time()
            
            try:
                data = await asyncio.wait_for(self.connector.get_data(), timeout=30.0)
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for data")
                data = {}
            
            duration = asyncio.get_event_loop().time() - start
            _LOGGER.debug(
                "Finished fetching %s data in %.3f seconds (success: %s)",
                DOMAIN, duration, bool(data)
            )
            
            # Add detailed logging of the actual data received
            if data:
                try:
                    data_str = json.dumps(data, default=str, sort_keys=True)
                    current_data_hash = hash(data_str)
                    
                    if self._last_data_hash == current_data_hash:
                        _LOGGER.debug("Data unchanged from previous update")
                    else:
                        _LOGGER.debug("Data received with keys: %s", list(data.keys()))
                        self._last_data_hash = current_data_hash
                except Exception as err:
                    _LOGGER.warning("Error processing data for logging: %s", err)
            
            # Critical check: if data is empty, this is always a failure
            if not data:
                self._failed_updates_count += 1
                _LOGGER.warning(
                    "Data fetch took %.2f seconds but returned empty data. Failed updates: %d",
                    duration, self._failed_updates_count
                )
                
                # If we have multiple consecutive failures, trigger a reconnection
                if self._failed_updates_count >= 2 and not self._reconnection_in_progress:
                    await self._trigger_reconnection()
                
                # Use existing data if available to prevent entities from becoming unavailable
                if self.data:
                    _LOGGER.debug("Using cached data due to fetch failure")
                    return self.data
                    
                raise UpdateFailed("No data received from device")
            
            # Reset counters on successful updates
            self._failed_updates_count = 0
            self._last_successful_update = time.time()
            
            return data
            
        except Exception as err:
            # Log and increment failure counter
            self._failed_updates_count += 1
            _LOGGER.error("Error fetching %s data: %s (failed updates: %d)", 
                         DOMAIN, err, self._failed_updates_count)
            
            # If we have multiple consecutive failures, trigger a reconnection
            if self._failed_updates_count >= 2 and not self._reconnection_in_progress:
                await self._trigger_reconnection()
                
            # Use existing data if available to prevent entities from becoming unavailable
            if self.data:
                _LOGGER.debug("Using cached data due to fetch error")
                return self.data
                
            raise UpdateFailed(f"Error fetching {DOMAIN} data: {err}")
            
    async def _trigger_reconnection(self):
        """Trigger reconnection without blocking updates."""
        _LOGGER.warning("Multiple consecutive update failures, initiating reconnection")
        
        try:
            # Mark reconnection as in progress to prevent concurrent attempts
            self._reconnection_in_progress = True
            
            # Create task for reconnection
            self.hass.async_create_task(self._handle_reconnection())
                
        except Exception as reconnect_err:
            _LOGGER.error("Error initiating reconnection: %s", reconnect_err)
            self._reconnection_in_progress = False
            
    async def _handle_reconnection(self):
        """Handle reconnection in background without blocking updates."""
        try:
            _LOGGER.info("Starting background reconnection process")
            reconnection_success = await self.connector._handle_reconnection()
            
            if reconnection_success:
                _LOGGER.info("Reconnection successful")
                # Try to fetch data after reconnection
                await self.async_refresh()
            else:
                _LOGGER.error("Reconnection failed")
                
        except Exception as e:
            _LOGGER.error(f"Error during reconnection: {e}")
        finally:
            self._reconnection_in_progress = False

    async def _health_check_loop(self):
        """Periodically check connection health and reconnect if needed."""
        _LOGGER.info("Health check loop started")
        
        try:
            while not self._shutdown_event.is_set():
                try:
                    # Check time since last successful update
                    time_since_update = time.time() - self._last_successful_update
                    
                    # If it's been over 5 minutes and no reconnection is in progress,
                    # force a reconnection
                    if time_since_update > 300 and not self._reconnection_in_progress:  # 5 minutes
                        _LOGGER.warning(f"No successful updates in {time_since_update:.1f} seconds, forcing reconnection")
                        await self._trigger_reconnection()
                        
                    # Check listeners to see if they're receiving updates
                    self._log_listener_status()
                    
                    # Wait for shutdown event or timeout after 60 seconds
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=60)
                    except asyncio.TimeoutError:
                        # This is expected when the timeout is reached
                        pass
                        
                except asyncio.CancelledError:
                    # Propagate cancellation
                    _LOGGER.debug("Health check loop received cancellation")
                    raise
                except Exception as e:
                    _LOGGER.error(f"Error in health check loop: {e}")
                    # Brief pause before continuing the loop
                    await asyncio.sleep(10)
                    
        except asyncio.CancelledError:
            _LOGGER.debug("Health check loop cancelled")
        finally:
            _LOGGER.debug("Health check loop exited")

    def _log_listener_status(self):
        """Log current status of coordinator listeners."""
        listener_count = len(self._listeners)
        if listener_count == 0:
            _LOGGER.warning("Coordinator has NO listeners - entities may not be receiving updates")
        else:
            _LOGGER.debug("Coordinator has %d active listeners", listener_count)

    async def async_refresh(self):
        """Refresh data and log the process."""
        # Don't attempt a refresh if reconnection is in progress
        if self._reconnection_in_progress:
            _LOGGER.debug("Skipping manual refresh, reconnection in progress")
            return False
            
        _LOGGER.debug("Manual refresh requested for %s", DOMAIN)
        result = await super().async_refresh()
        _LOGGER.debug("Manual refresh completed for %s", DOMAIN)
        return result

    async def async_shutdown(self) -> None:
        """Shut down the coordinator."""
        _LOGGER.debug("Shutting down coordinator")
        self._shutdown_event.set()
        
        # Cancel and wait for health check task to complete
        if self._health_check_task:
            _LOGGER.debug("Cancelling health check task")
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            
        # Disconnect the connector
        if self.connector:
            await self.connector.disconnect()
            
        _LOGGER.debug("Coordinator shutdown complete")