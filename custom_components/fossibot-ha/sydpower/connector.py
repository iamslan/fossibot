"""Main connector for Fossibot/Sydpower integration."""

import asyncio
import time
from typing import Any, Dict, Optional

from .logger import SmartLogger
from .api_client import APIClient
from .mqtt_client import MQTTClient
from .modbus import (
    REGRequestSettings, REGDisableUSBOutput, REGEnableUSBOutput,
    REGDisableDCOutput, REGEnableDCOutput, REGDisableACOutput,
    REGEnableACOutput, REGDisableLED, REGEnableLEDAlways,
    REGEnableLEDSOS, REGEnableLEDFlash, REGDisableACSilentChg,
    REGEnableACSilentChg, get_write_modbus, ModbusValidationError,
)
from .const import (
    REGISTER_MODBUS_ADDRESS, MQTT_HOST_PROD, MQTT_HOST_DEV,
)

COMMANDS = {
    "REGRequestSettings": REGRequestSettings,
    "REGDisableUSBOutput": REGDisableUSBOutput,
    "REGEnableUSBOutput": REGEnableUSBOutput,
    "REGDisableDCOutput": REGDisableDCOutput,
    "REGEnableDCOutput": REGEnableDCOutput,
    "REGDisableACOutput": REGDisableACOutput,
    "REGEnableACOutput": REGEnableACOutput,
    "REGDisableLED": REGDisableLED,
    "REGEnableLEDAlways": REGEnableLEDAlways,
    "REGEnableLEDSOS": REGEnableLEDSOS,
    "REGEnableLEDFlash": REGEnableLEDFlash,
    "REGDisableACSilentChg": REGDisableACSilentChg,
    "REGEnableACSilentChg": REGEnableACSilentChg,
}


class SydpowerConnector:
    """Main class for Fossibot/Sydpower API connection."""

    def __init__(self, username: str, password: str, developer_mode: bool = False):
        self.username = username
        self.password = password
        self.developer_mode = developer_mode
        self._logger = SmartLogger(__name__)

        self.api_client: Optional[APIClient] = None
        self.mqtt_client: Optional[MQTTClient] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Connection management
        self._connection_lock = asyncio.Lock()
        self._reconnection_in_progress = False
        self._reconnection_event = asyncio.Event()
        self._reconnection_event.set()  # Initially set so get_data doesn't block
        self._last_reconnection_attempt = 0
        self._min_reconnection_interval = 5

        # Device data
        self.devices: Dict[str, Any] = {}

        # Last successful connection timestamp
        self._last_successful_communication = 0

    async def connect(self) -> bool:
        """Connect to the API and MQTT broker. Returns True if successful."""
        mqtt_host = MQTT_HOST_DEV if self.developer_mode else MQTT_HOST_PROD

        if self._reconnection_in_progress:
            self._logger.debug(
                "Connection attempt while reconnection in progress, waiting..."
            )
            try:
                await asyncio.wait_for(
                    self._reconnection_event.wait(), timeout=15.0
                )
            except asyncio.TimeoutError:
                self._logger.error("Timeout waiting for reconnection")
                return False

            if self.mqtt_client and self.mqtt_client.connected.is_set():
                return True

        # Already connected
        if self.mqtt_client and self.mqtt_client.connected.is_set():
            return True

        # Acquire lock to prevent concurrent connection attempts
        try:
            lock_acquired = await asyncio.wait_for(
                self._connection_lock.acquire(), timeout=10.0
            )
        except asyncio.TimeoutError:
            self._logger.error("Timeout acquiring connection lock")
            return False

        if not lock_acquired:
            return False

        try:
            if self.loop is None:
                self.loop = asyncio.get_running_loop()

            if self.api_client is None:
                self.api_client = APIClient()

            if self.mqtt_client is None:
                self.mqtt_client = MQTTClient(self.loop)
                self.mqtt_client.on_disconnect_callback = (
                    self._handle_mqtt_disconnect
                )

            # Step 1: Authenticate with API
            self._logger.info("Authenticating with API")
            await asyncio.wait_for(
                self.api_client.authenticate(self.username, self.password),
                timeout=30.0,
            )

            # Step 2: Get MQTT token
            self._logger.info("Getting MQTT token")
            mqtt_token = await asyncio.wait_for(
                self.api_client.get_mqtt_token(), timeout=15.0
            )

            # Step 3: Get devices
            self._logger.info("Getting device list")
            self.devices = await asyncio.wait_for(
                self.api_client.get_devices(), timeout=15.0
            )

            device_ids = list(self.devices.keys())

            if not device_ids:
                self._logger.error("No devices returned from API")
                raise ValueError("No devices returned from API")

            self._logger.info(
                "Found %d devices: %s", len(device_ids), device_ids
            )

            # Step 4: Connect to MQTT
            self._logger.info("Connecting to MQTT broker")
            await self.mqtt_client.connect(mqtt_token, device_ids, mqtt_host)

            try:
                await asyncio.wait_for(
                    self.mqtt_client.connected.wait(), timeout=15.0
                )
            except asyncio.TimeoutError:
                self._logger.error("Timeout waiting for MQTT connection")
                await self._cleanup()
                return False

            # Step 5: Verify connection works
            try:
                if not await asyncio.wait_for(
                    self._verify_connection(), timeout=10.0
                ):
                    self._logger.error("Connection verification failed")
                    await self._cleanup()
                    return False
            except asyncio.TimeoutError:
                self._logger.error("Timeout during connection verification")
                await self._cleanup()
                return False

            self._last_successful_communication = time.time()
            self._logger.info("Connection successful and verified")
            return True

        except asyncio.CancelledError:
            self._logger.warning("Connect operation was cancelled")
            raise
        except Exception as e:
            self._logger.error("Error during connection: %s", e)
            await self._cleanup()
            return False
        finally:
            if self._connection_lock.locked():
                self._connection_lock.release()

    async def _verify_connection(self) -> bool:
        """Verify the connection is working by attempting to get data."""
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            return False

        device_ids = list(self.devices.keys())
        if not device_ids:
            return False

        try:
            self.mqtt_client.data_updated.clear()

            for device_id in device_ids:
                self.mqtt_client.request_data_update(device_id)

            await asyncio.wait_for(
                self.mqtt_client.data_updated.wait(), timeout=5.0
            )
            self._logger.info("Connection verification successful")
            return True
        except asyncio.TimeoutError:
            self._logger.warning(
                "Connection verification timed out - no data received"
            )
            return False
        except Exception as e:
            self._logger.error("Error during connection verification: %s", e)
            return False

    async def get_data(self) -> Dict[str, Any]:
        """Get the latest data from devices."""
        # Wait for any in-progress reconnection
        if self._reconnection_in_progress:
            self._logger.debug(
                "Reconnection in progress, waiting before getting data..."
            )
            try:
                await asyncio.wait_for(
                    self._reconnection_event.wait(), timeout=30.0
                )
            except asyncio.TimeoutError:
                self._logger.warning("Timeout waiting for reconnection")
                return {}

        # Ensure connected
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            self._logger.debug("MQTT client not connected, calling connect()")
            try:
                if not await asyncio.wait_for(self.connect(), timeout=30.0):
                    self._logger.error("Failed to connect")
                    return {}
            except asyncio.TimeoutError:
                self._logger.error("Connection timeout")
                return {}
            except Exception as e:
                self._logger.error("Connection error: %s", e)
                return {}

        if self.mqtt_client:
            self.mqtt_client.data_updated.clear()

        if not self.devices:
            self._logger.warning("No devices available to request data from")
            return {}

        num_devices = len(self.devices)
        self._logger.debug(
            "Publishing data request for %d device(s)", num_devices
        )

        for device_mac in self.devices:
            if self.mqtt_client:
                self.mqtt_client.request_data_update(device_mac)
            else:
                self._logger.error("MQTT client became None unexpectedly")
                return {}

        try:
            if not self.mqtt_client:
                raise RuntimeError("MQTT client is None")

            await asyncio.wait_for(
                self.mqtt_client.data_updated.wait(), timeout=30.0
            )

            # Grace period for remaining devices to respond
            if num_devices > 1:
                await asyncio.sleep(2)

            if not self.mqtt_client.devices:
                self._logger.warning(
                    "Data update event triggered but no device data received"
                )
                return {}

            self._last_successful_communication = time.time()
            self.devices = {**self.devices, **self.mqtt_client.devices}
            return self.devices

        except asyncio.TimeoutError:
            self._logger.warning(
                "Timeout waiting for device data update after 30 seconds. "
                "Devices: %s",
                list(self.devices.keys()),
            )
            return {}
        except Exception as e:
            self._logger.error(
                "Error waiting for device data update: %s", e
            )
            return {}

    async def run_command(
        self, device_id: str, command: str, value=None
    ) -> bool:
        """Run a command on a device. Returns True if successful."""
        # Wait for reconnection if in progress
        if self._reconnection_in_progress:
            self._logger.debug(
                "Reconnection in progress, waiting before running command..."
            )
            try:
                await asyncio.wait_for(
                    self._reconnection_event.wait(), timeout=30.0
                )
            except asyncio.TimeoutError:
                self._logger.warning("Timeout waiting for reconnection")
                return False

        # Ensure connected
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            try:
                if not await asyncio.wait_for(self.connect(), timeout=30.0):
                    self._logger.error(
                        "Failed to connect for command execution"
                    )
                    return False
            except asyncio.TimeoutError:
                self._logger.error("Connection timeout for command execution")
                return False
            except Exception as e:
                self._logger.error(
                    "Connection error for command execution: %s", e
                )
                return False

        # Resolve command bytes
        if command in COMMANDS:
            command_bytes = COMMANDS[command]
        elif command == "write_register" and value is not None:
            register, reg_value = value
            try:
                command_bytes = get_write_modbus(
                    REGISTER_MODBUS_ADDRESS, register, reg_value,
                )
            except ModbusValidationError as e:
                self._logger.error("Refused to write: %s", e)
                return False
        else:
            self._logger.error("Unknown command: %s", command)
            return False

        if not self.mqtt_client:
            self._logger.error("MQTT client is None")
            return False

        try:
            self._logger.debug("Sending command: %s", command)
            self.mqtt_client.publish_command(device_id, command_bytes)
            self._last_successful_communication = time.time()
            await asyncio.sleep(1)  # Allow device to process
            return True
        except Exception as e:
            self._logger.error("Error publishing command: %s", e)
            return False

    async def reconnect(self) -> bool:
        """Reconnect to the API and MQTT broker (public API)."""
        return await self._handle_reconnection()

    async def _handle_mqtt_disconnect(self, rc):
        """Handle MQTT disconnection events."""
        self._logger.warning("MQTT disconnected with code %s", rc)
        time_since_last = time.time() - self._last_successful_communication

        if time_since_last > 60:
            self._logger.warning(
                "No successful communication in %.1f seconds, "
                "forcing reconnection",
                time_since_last,
            )
            self._last_reconnection_attempt = 0

        self.loop.create_task(self._handle_reconnection())

    async def _handle_reconnection(self):
        """Handle reconnection with proper backoff and state management."""
        current_time = time.time()

        # Apply minimum interval between reconnection attempts
        if (
            current_time - self._last_reconnection_attempt
            < self._min_reconnection_interval
        ):
            await asyncio.sleep(self._min_reconnection_interval)
            current_time = time.time()

        # If reconnection already in progress, wait for it
        if self._reconnection_in_progress:
            self._logger.debug(
                "Reconnection already in progress, waiting..."
            )
            try:
                await asyncio.wait_for(
                    self._reconnection_event.wait(), timeout=30.0
                )
            except asyncio.TimeoutError:
                self._logger.error(
                    "Timeout waiting for existing reconnection"
                )
            return self.is_connected()

        # Acquire connection lock
        try:
            lock_acquired = await asyncio.wait_for(
                self._connection_lock.acquire(), timeout=10.0
            )
        except asyncio.TimeoutError:
            self._logger.error(
                "Timeout acquiring connection lock for reconnection"
            )
            return False

        if not lock_acquired:
            return False

        try:
            self._reconnection_in_progress = True
            self._reconnection_event.clear()
            self._last_reconnection_attempt = current_time
            self._logger.info("Starting reconnection process...")

            # Clean up existing connections
            try:
                await asyncio.wait_for(self._cleanup(), timeout=10.0)
            except asyncio.TimeoutError:
                self._logger.error("Cleanup timeout during reconnection")

            self.api_client = None
            self.mqtt_client = None
            await asyncio.sleep(2)

            # Retry loop with exponential backoff
            max_attempts = 10
            base_delay = 3

            for attempt in range(max_attempts):
                self._logger.info(
                    "Reconnection attempt %d/%d", attempt + 1, max_attempts
                )
                try:
                    if await asyncio.wait_for(self.connect(), timeout=45.0):
                        self._logger.info(
                            "Successfully reconnected on attempt %d",
                            attempt + 1,
                        )
                        self._last_successful_communication = time.time()
                        return True
                    else:
                        self._logger.warning(
                            "Reconnection attempt %d failed verification",
                            attempt + 1,
                        )
                except asyncio.TimeoutError:
                    self._logger.error(
                        "Timeout during reconnection attempt %d", attempt + 1
                    )
                except Exception as e:
                    self._logger.error(
                        "Reconnection attempt %d failed: %s", attempt + 1, e
                    )

                if attempt < max_attempts - 1:
                    delay = min(base_delay * (1.5 ** attempt), 30)
                    self._logger.warning(
                        "Waiting %.0f seconds before next reconnection attempt",
                        delay,
                    )
                    await asyncio.sleep(delay)

            self._logger.error(
                "Failed to reconnect after %d attempts", max_attempts
            )
            return False

        except asyncio.CancelledError:
            self._logger.warning("Reconnection process was cancelled")
            raise
        except Exception as e:
            self._logger.error(
                "Unexpected error in reconnection handler: %s", e
            )
            return False
        finally:
            self._reconnection_in_progress = False
            self._reconnection_event.set()
            if self._connection_lock.locked():
                self._connection_lock.release()

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self.mqtt_client:
            try:
                await asyncio.wait_for(
                    self.mqtt_client.disconnect(), timeout=5.0
                )
            except asyncio.TimeoutError:
                self._logger.warning("MQTT client disconnect timeout")
            except Exception as e:
                self._logger.warning(
                    "Error during MQTT client cleanup: %s", e
                )
            finally:
                self.mqtt_client = None

        if self.api_client:
            try:
                await asyncio.wait_for(
                    self.api_client.close(), timeout=5.0
                )
            except asyncio.TimeoutError:
                self._logger.warning("API client close timeout")
            except Exception as e:
                self._logger.warning(
                    "Error during API client cleanup: %s", e
                )
            finally:
                self.api_client = None

    async def disconnect(self) -> None:
        """Disconnect from the API and MQTT broker."""
        await self._cleanup()
        self._logger.info("Disconnected from all services")

    def is_connected(self) -> bool:
        """Check if the connector is connected."""
        return bool(self.mqtt_client and self.mqtt_client.connected.is_set())
