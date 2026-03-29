"""Main connector for Fossibot/Sydpower integration via local MQTT broker."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from .logger import SmartLogger
from .api_client import APIClient
from .mqtt_client import MQTTClient
from .modbus import (
    REGRequestSettings, REGDisableUSBOutput, REGEnableUSBOutput,
    REGDisableDCOutput, REGEnableDCOutput, REGDisableACOutput,
    REGEnableACOutput, REGDisableLED, REGEnableLEDAlways,
    REGEnableLEDSOS, REGEnableLEDFlash, REGDisableACSilentChg,
    REGEnableACSilentChg, get_read_modbus,
    get_write_modbus, ModbusValidationError,
)
from .const import REGISTER_MODBUS_ADDRESS, DEFAULT_MQTT_PORT

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
    """Main class for Fossibot/Sydpower connection via local MQTT broker."""

    def __init__(
        self,
        api_token: str,
        mqtt_host: str,
        mqtt_port: int = DEFAULT_MQTT_PORT,
        mqtt_username: str = "",
    ):
        self.api_token = api_token
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_username = mqtt_username
        self._logger = SmartLogger(__name__)

        self.api_client: Optional[APIClient] = None
        self.mqtt_client: Optional[MQTTClient] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Connection management
        self._connection_lock = asyncio.Lock()
        self._reconnection_in_progress = False
        self._reconnection_event = asyncio.Event()
        self._reconnection_event.set()
        self._last_reconnection_attempt = 0
        self._min_reconnection_interval = 5

        # Device data
        self.devices: Dict[str, Any] = {}

        # Last successful connection timestamp
        self._last_successful_communication = 0

        # Callback fired when new device data arrives (for real-time updates)
        self.on_data_received_callback: Optional[Callable] = None

    async def connect(self) -> bool:
        """Connect to the API and local MQTT broker. Returns True if successful."""
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
                self.api_client = APIClient(self.api_token)

            if self.mqtt_client is None:
                self.mqtt_client = MQTTClient(self.loop)
                self.mqtt_client.on_disconnect_callback = (
                    self._handle_mqtt_disconnect
                )
                self.mqtt_client.on_device_state_callback = (
                    self._handle_device_state
                )
                self.mqtt_client.on_data_received_callback = (
                    self._handle_data_received
                )

            # Step 1: Get device list from API
            self._logger.info("Getting device list from API")
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

            # Step 2: Connect to local MQTT broker
            self._logger.info(
                "Connecting to MQTT broker at %s:%d",
                self.mqtt_host, self.mqtt_port,
            )

            await self.mqtt_client.connect(
                device_ids, self.mqtt_host, self.mqtt_port, self.mqtt_username
            )

            try:
                await asyncio.wait_for(
                    self.mqtt_client.connected.wait(), timeout=15.0
                )
            except asyncio.TimeoutError:
                self._logger.error("Timeout waiting for MQTT connection")
                await self._cleanup()
                return False

            # Step 3: Verify connection (get initial data)
            try:
                if await asyncio.wait_for(
                    self._verify_connection(), timeout=15.0
                ):
                    self._last_successful_communication = time.time()
                    self._logger.info(
                        "Connected to local MQTT broker at %s:%d",
                        self.mqtt_host, self.mqtt_port,
                    )
                    return True
            except asyncio.TimeoutError:
                self._logger.warning("Connection verification timed out")

            # Verification failed but broker is connected — device may be
            # offline/sleeping. Accept the connection; polls will recover.
            if self.mqtt_client and self.mqtt_client.connected.is_set():
                self._logger.warning(
                    "Device not responding — accepting broker connection. "
                    "Integration will recover when device is reachable.",
                )
                self._last_successful_communication = time.time()
                return True

            self._logger.error("Failed to connect to MQTT broker")
            await self._cleanup()
            return False

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
        """Verify the connection by testing device responsiveness."""
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            return False

        self._logger.debug("Stage 1: waiting for initial func 03 response...")

        try:
            await asyncio.wait_for(
                self.mqtt_client.data_updated.wait(), timeout=5.0
            )
            self._logger.debug(
                "Initial response received, waiting 1s for settings..."
            )
            await asyncio.sleep(1.0)

            if self.mqtt_client.devices:
                for mac, fields in self.mqtt_client.devices.items():
                    if mac in self.devices:
                        self.devices[mac].update(fields)
                    else:
                        self.devices[mac] = fields

            field_count = sum(
                len(v) for v in self.mqtt_client.devices.values()
            ) if self.mqtt_client.devices else 0

            for mac, fields in (self.mqtt_client.devices or {}).items():
                self._logger.debug(
                    "Verify stage 1: %s returned %d fields — %s",
                    mac, len(fields), sorted(fields.keys()),
                )

            if field_count == 0:
                self._logger.warning("Stage 1 received no fields, failing")
                return False

            self._logger.debug(
                "Stage 1 complete: %d fields. Starting stage 2 (fresh poll)...",
                field_count,
            )

            # Stage 2: Fresh poll
            self.mqtt_client.clear_message_cache()
            self.mqtt_client.data_updated.clear()

            for device_mac in list(self.devices.keys()):
                self._send_read_request(device_mac)

            await asyncio.wait_for(
                self.mqtt_client.data_updated.wait(), timeout=5.0
            )
            await asyncio.sleep(1.0)

            fresh_field_count = sum(
                len(v) for v in self.mqtt_client.devices.values()
            ) if self.mqtt_client.devices else 0

            if fresh_field_count == 0:
                self._logger.warning(
                    "Stage 2 failed: device did not respond to fresh poll"
                )
                return False

            self._logger.info(
                "Connection verified — stage 1: %d fields, stage 2: %d fields",
                field_count, fresh_field_count,
            )
            return True

        except asyncio.TimeoutError:
            self._logger.warning(
                "Connection verification timed out (device not responding)"
            )
            return False
        except Exception as e:
            self._logger.error("Error during connection verification: %s", e)
            return False

    async def _handle_data_received(self, device_mac: str, device_update: dict):
        """Handle real-time data from MQTT — merge and notify coordinator."""
        if device_mac in self.devices and isinstance(self.devices[device_mac], dict):
            self.devices[device_mac].update(device_update)
        else:
            self.devices[device_mac] = device_update

        self._last_successful_communication = time.time()

        if self.on_data_received_callback:
            try:
                await self.on_data_received_callback(self.devices)
            except Exception as e:
                self._logger.error("Error in data received callback: %s", e)

    async def _handle_device_state(self, device_mac: str, online: bool):
        """Handle device state changes — sync with platform API."""
        # Look up the raw device_id (with colons) for the API call
        device_info = self.devices.get(device_mac, {})
        raw_device_id = device_info.get("_raw_device_id")

        if not raw_device_id:
            # Reconstruct MAC with colons from the stripped version
            if len(device_mac) == 12:
                raw_device_id = ":".join(
                    device_mac[i:i+2] for i in range(0, 12, 2)
                )
            else:
                self._logger.warning(
                    "Cannot determine raw device_id for %s", device_mac
                )
                return

        if self.api_client:
            await self.api_client.update_mqtt_state(raw_device_id, online)

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

        if not self.devices:
            self._logger.warning("No devices available to request data from")
            return {}

        data = await self._poll_devices()
        if data:
            return data

        # Poll timed out — return cached data so the coordinator stays alive
        if self.devices:
            cached_fields = {
                mac: len([k for k in d if not k.startswith("_")])
                for mac, d in self.devices.items()
                if isinstance(d, dict)
            }
            self._logger.warning(
                "Poll timed out, returning cached data: %s", cached_fields
            )
            return self.devices

        self._logger.warning("Poll timed out and no cached data available")
        return {}

    async def _poll_devices(self) -> Dict[str, Any]:
        """Send func 03 read and wait for sensor + settings responses."""
        if not self.mqtt_client:
            return {}

        self.mqtt_client.clear_message_cache()
        self.mqtt_client.data_updated.clear()
        self._logger.debug(
            "Poll: cache cleared, sending func 03 to %s",
            list(self.devices.keys()),
        )

        for device_mac in self.devices:
            if not self.mqtt_client:
                return {}
            self._send_read_request(device_mac)

        try:
            await asyncio.wait_for(
                self.mqtt_client.data_updated.wait(), timeout=5.0
            )
            self._logger.debug(
                "Poll: first response arrived, waiting 1s for settings..."
            )
            await asyncio.sleep(1.0)

            if self.mqtt_client.devices:
                self._last_successful_communication = time.time()
                for mac, fields in self.mqtt_client.devices.items():
                    if mac in self.devices:
                        self.devices[mac].update(fields)
                    else:
                        self.devices[mac] = fields

                for mac in self.devices:
                    data = self.devices.get(mac, {})
                    user_fields = [
                        k for k in data if not k.startswith("_")
                    ]
                    self._logger.debug(
                        "Poll result %s: %d fields — %s",
                        mac, len(user_fields), sorted(user_fields),
                    )
                return self.devices

        except asyncio.TimeoutError:
            self._logger.debug(
                "Poll: no response within 5s (device may be offline)"
            )
        except Exception as e:
            self._logger.error("Error during poll: %s", e)

        return {}

    def _send_read_request(self, device_mac: str) -> None:
        """Send a Modbus read using per-device address and count from API."""
        if not self.mqtt_client:
            return

        device_info = self.devices.get(device_mac, {})
        modbus_addr = device_info.get(
            "_modbus_address", REGISTER_MODBUS_ADDRESS
        )
        modbus_count = device_info.get("_modbus_count", 80)

        command_bytes = get_read_modbus(modbus_addr, modbus_count)
        self.mqtt_client.publish_command(device_mac, command_bytes)
        self._logger.debug(
            "Sent func 03 to %s (addr=%d, count=%d)",
            device_mac, modbus_addr, modbus_count,
        )

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
            device_info = self.devices.get(device_id, {})
            modbus_addr = device_info.get(
                "_modbus_address", REGISTER_MODBUS_ADDRESS
            )
            try:
                command_bytes = get_write_modbus(
                    modbus_addr, register, reg_value,
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

        if (
            current_time - self._last_reconnection_attempt
            < self._min_reconnection_interval
        ):
            await asyncio.sleep(self._min_reconnection_interval)
            current_time = time.time()

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

            try:
                await asyncio.wait_for(self._cleanup(), timeout=10.0)
            except asyncio.TimeoutError:
                self._logger.error("Cleanup timeout during reconnection")

            self.api_client = None
            self.mqtt_client = None
            await asyncio.sleep(2)

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
