"""
Main connector for Fossibot/Sydpower integration.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable, Coroutine

from .logger import SmartLogger
from .api_client import APIClient
from .mqtt_client import MQTTClient
from .modbus import (
    REGRequestSettings, REGDisableUSBOutput, REGEnableUSBOutput,
    REGDisableDCOutput, REGEnableDCOutput, REGDisableACOutput,
    REGEnableACOutput, REGDisableLED, REGEnableLEDAlways,
    REGEnableLEDSOS, REGEnableLEDFlash, REGDisableACSilentChg,
    REGEnableACSilentChg, get_write_modbus
)
from .const import REGISTER_MODBUS_ADDRESS, REGISTER_MAXIMUM_CHARGING_CURRENT, REGISTER_AC_SILENT_CHARGING, MQTT_HOST_PROD, MQTT_HOST_DEV

class SydpowerConnector:
    """Main class for Fossibot/Sydpower API connection."""
    
    def __init__(self, username: str, password: str, developer_mode: bool = False):
        self.username = username
        self.password = password
        self.developer_mode = developer_mode  # Add this line
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
        # First check if reconnection in progress or already connected
        mqtt_host = MQTT_HOST_DEV if self.developer_mode else MQTT_HOST_PROD

        if self._reconnection_in_progress:
            self._logger.debug("Connection attempt while reconnection in progress, waiting...")
            try:
                await asyncio.wait_for(self._reconnection_event.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                self._logger.error("Timeout waiting for reconnection")
                return False
                
            if self.mqtt_client and self.mqtt_client.connected.is_set():
                return True
        
        # If already connected, just return
        if self.mqtt_client and self.mqtt_client.connected.is_set():
            return True
            
        # Use lock to prevent concurrent connection attempts
        try:
            # Only wait 10 seconds for lock to prevent deadlock
            lock_acquired = False
            try:
                lock_acquired = await asyncio.wait_for(self._connection_lock.acquire(), timeout=10.0)
            except asyncio.TimeoutError:
                self._logger.error("Timeout acquiring connection lock")
                return False
                
            if not lock_acquired:
                return False
                
            try:
                if self.loop is None:
                    self.loop = asyncio.get_running_loop()

                # Initialize clients if needed
                if self.api_client is None:
                    self.api_client = APIClient()
                
                if self.mqtt_client is None:
                    self.mqtt_client = MQTTClient(self.loop)
                    # Register disconnect callback
                    self.mqtt_client.on_disconnect_callback = self._handle_mqtt_disconnect
                
                # Step 1: Authenticate with API
                self._logger.info("Authenticating with API")
                try:
                    auth_result = await asyncio.wait_for(
                        self.api_client.authenticate(self.username, self.password),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    self._logger.error("API authentication timeout")
                    raise
                
                # Step 2: Get MQTT token
                self._logger.info("Getting MQTT token")
                try:
                    mqtt_token = await asyncio.wait_for(
                        self.api_client.get_mqtt_token(),
                        timeout=15.0
                    )
                except asyncio.TimeoutError:
                    self._logger.error("MQTT token timeout")
                    raise
                
                # Step 3: Get devices
                self._logger.info("Getting device list")
                try:
                    self.devices = await asyncio.wait_for(
                        self.api_client.get_devices(),
                        timeout=15.0
                    )
                except asyncio.TimeoutError:
                    self._logger.error("Device list timeout")
                    raise
                    
                device_ids = list(self.devices.keys())
                
                if not device_ids:
                    self._logger.error("No devices returned from API")
                    raise ValueError("No devices returned from API")
                    
                self._logger.info(f"Found {len(device_ids)} devices: {device_ids}")
                
                # Step 4: Connect to MQTT
                self._logger.info("Connecting to MQTT broker")
                await self.mqtt_client.connect(mqtt_token, device_ids, mqtt_host)
                
                # Wait for MQTT connection
                try:
                    await asyncio.wait_for(self.mqtt_client.connected.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    self._logger.error("Timeout waiting for MQTT connection")
                    await self._cleanup()
                    return False
                
                # Verify connection works by requesting data
                try:
                    if not await asyncio.wait_for(self._verify_connection(), timeout=10.0):
                        self._logger.error("Connection verification failed")
                        await self._cleanup()
                        return False
                except asyncio.TimeoutError:
                    self._logger.error("Timeout during connection verification")
                    await self._cleanup()
                    return False
                
                # Update timestamp for successful connection
                self._last_successful_communication = time.time()
                self._logger.info("Connection successful and verified")
                return True
                    
            except Exception as e:
                self._logger.error(f"Error during connection: {e}")
                await self._cleanup()
                return False
            finally:
                if self._connection_lock.locked():
                    self._connection_lock.release()
                
        except asyncio.CancelledError:
            self._logger.warning("Connect operation was cancelled")
            if self._connection_lock.locked():
                self._connection_lock.release()
            raise
    
    async def _verify_connection(self) -> bool:
        """Verify the connection is working by attempting to get data."""
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            return False
            
        device_ids = list(self.devices.keys())
        if not device_ids:
            return False
            
        try:
            # Clear any existing data update event
            self.mqtt_client.data_updated.clear()
            
            # Request data from each device
            for device_id in device_ids:
                self.mqtt_client.request_data_update(device_id)
                
            # Wait for a short time to see if we get a response
            try:
                await asyncio.wait_for(self.mqtt_client.data_updated.wait(), timeout=5.0)
                # If we got here, we received data
                self._logger.info("Connection verification successful")
                return True
            except asyncio.TimeoutError:
                self._logger.warning("Connection verification timed out - no data received")
                return False
                
        except Exception as e:
            self._logger.error(f"Error during connection verification: {e}")
            return False
    
    async def get_data(self) -> Dict[str, Any]:
        """Get the latest data from devices."""
        # Check if reconnection is in progress before proceeding
        if self._reconnection_in_progress:
            self._logger.debug("Reconnection in progress, waiting before getting data...")
            try:
                await asyncio.wait_for(self._reconnection_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                self._logger.warning("Timeout waiting for reconnection")
                return {}
        
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            self._logger.debug("MQTT client not initialized or not connected, calling connect()")
            try:
                if not await asyncio.wait_for(self.connect(), timeout=30.0):
                    self._logger.error("Failed to connect")
                    return {}
            except asyncio.TimeoutError:
                self._logger.error("Connection timeout")
                return {}
            except Exception as e:
                self._logger.error(f"Connection error: {e}")
                return {}
        
        # Reset data updated event
        if self.mqtt_client:
            self.mqtt_client.data_updated.clear()

        if not self.devices:
            self._logger.warning("No devices available to request data from")
            return {}

        num_devices = len(self.devices)
        self._logger.debug(f"Publishing data request for {num_devices} device(s)")

        # Request update from each device
        for device_mac in self.devices.keys():
            if self.mqtt_client:
                self.mqtt_client.request_data_update(device_mac)
            else:
                self._logger.error("MQTT client became None unexpectedly")
                return {}

        # Wait for updates
        start_time = time.time()
        self._logger.debug("Waiting for device data update (timeout = 30 seconds)...")
        try:
            if not self.mqtt_client:
                raise RuntimeError("MQTT client is None")
                
            await asyncio.wait_for(self.mqtt_client.data_updated.wait(), timeout=30.0)
            elapsed = time.time() - start_time
            self._logger.debug(f"Device data update event received after {elapsed:.2f} seconds")
            
            # Verify that we actually got new data
            if not self.mqtt_client.devices:
                self._logger.warning("Data update event was triggered but no device data was received")
                return {}
                
            # Update last successful communication timestamp
            self._last_successful_communication = time.time()
            
            # Update our local copy of the device data
            self.devices = {**self.devices, **self.mqtt_client.devices}
            
            # Return the updated data
            return self.devices
            
        except asyncio.TimeoutError:
            self._logger.warning(f"Timeout waiting for device data update after 30 seconds. Devices: {list(self.devices.keys())}")
            return {}
        except Exception as e:
            self._logger.error(f"Error waiting for device data update: {e}")
            # Return empty dict to indicate failure
            return {}
    
    async def run_command(self, device_id: str, command: str, value=None) -> bool:
        """Run a command on a device. Returns True if successful."""
        # Check if reconnection is in progress before proceeding
        if self._reconnection_in_progress:
            self._logger.debug("Reconnection in progress, waiting before running command...")
            try:
                await asyncio.wait_for(self._reconnection_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                self._logger.warning("Timeout waiting for reconnection")
                return False
            
        if not self.mqtt_client or not self.mqtt_client.connected.is_set():
            try:
                if not await asyncio.wait_for(self.connect(), timeout=30.0):
                    self._logger.error("Failed to connect for command execution")
                    return False
            except asyncio.TimeoutError:
                self._logger.error("Connection timeout")
                return False
            except Exception as e:
                self._logger.error(f"Connection error for command execution: {e}")
                return False
        
        command_bytes = None
        
        # Handle pre-defined commands
        if command == "REGRequestSettings":
            command_bytes = REGRequestSettings
        elif command == "REGDisableUSBOutput":
            command_bytes = REGDisableUSBOutput
        elif command == "REGEnableUSBOutput":
            command_bytes = REGEnableUSBOutput
        elif command == "REGDisableDCOutput":
            command_bytes = REGDisableDCOutput
        elif command == "REGEnableDCOutput":
            command_bytes = REGEnableDCOutput
        elif command == "REGDisableACOutput":
            command_bytes = REGDisableACOutput
        elif command == "REGEnableACOutput":
            command_bytes = REGEnableACOutput
        elif command == "REGDisableLED":
            command_bytes = REGDisableLED
        elif command == "REGEnableLEDAlways":
            command_bytes = REGEnableLEDAlways
        # Add these two lines for the missing LED commands
        elif command == "REGEnableLEDSOS":
            command_bytes = REGEnableLEDSOS
        elif command == "REGEnableLEDFlash":
            command_bytes = REGEnableLEDFlash
        elif command == "REGDisableACSilentChg":
            command_bytes = REGDisableACSilentChg
        elif command == "REGEnableACSilentChg":
            command_bytes = REGEnableACSilentChg
        # Handle dynamic commands
        elif command == "set_charging_current" and value is not None:
            command_bytes = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_MAXIMUM_CHARGING_CURRENT, value)

        if command_bytes and self.mqtt_client:
            try:
                self._logger.debug(f"Sending command: {command} with bytes: {command_bytes}")
                self.mqtt_client.publish_command(device_id, command_bytes)
                # Update the last communication timestamp
                self._last_successful_communication = time.time()
                await asyncio.sleep(1)  # Small delay to allow for device response
                return True
            except Exception as e:
                self._logger.error(f"Error publishing command: {e}")
                return False
        else:
            self._logger.error(f"Unknown command: {command} or MQTT client is None")
            return False
    
    async def _handle_mqtt_disconnect(self, rc):
        """Handle MQTT disconnection events."""
        self._logger.warning(f"MQTT disconnected with code {rc}, initiating reconnection")
        # Check how long since the last successful communication
        current_time = time.time()
        time_since_last_success = current_time - self._last_successful_communication
        
        # If it's been more than 60 seconds since last successful communication,
        # trigger a reconnection with higher priority
        if time_since_last_success > 60:
            self._logger.warning(f"No successful communication in {time_since_last_success:.1f} seconds, forcing reconnection")
            self._last_reconnection_attempt = 0  # Reset to force reconnection
            
        # Create a task for reconnection instead of blocking
        self.loop.create_task(self._handle_reconnection())
    
    async def _handle_reconnection(self):
        """Handle reconnection with proper backoff and state management."""
        current_time = time.time()
        
        # Apply backoff if needed
        if current_time - self._last_reconnection_attempt < self._min_reconnection_interval:
            await asyncio.sleep(self._min_reconnection_interval)
            current_time = time.time()

        # Use a simpler approach to avoid deadlocks
        if self._reconnection_in_progress:
            self._logger.debug("Reconnection already in progress, waiting...")
            try:
                await asyncio.wait_for(self._reconnection_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                self._logger.error("Timeout waiting for existing reconnection")
            return self.is_connected()

        # Acquire lock with timeout to prevent deadlock
        lock_acquired = False
        try:
            lock_acquired = await asyncio.wait_for(self._connection_lock.acquire(), timeout=10.0)
        except asyncio.TimeoutError:
            self._logger.error("Timeout acquiring connection lock for reconnection")
            return False
            
        if not lock_acquired:
            return False
            
        try:
            self._reconnection_in_progress = True
            self._reconnection_event.clear()  # Mark that reconnection is in progress
            self._last_reconnection_attempt = current_time
            self._logger.info("Starting reconnection process...")

            # Fully clean up existing connections
            try:
                await asyncio.wait_for(self._cleanup(), timeout=10.0)
            except asyncio.TimeoutError:
                self._logger.error("Cleanup timeout during reconnection")
            
            # Reset internal state completely
            self.api_client = None
            self.mqtt_client = None
            
            # Sleep a moment to ensure full disconnection
            await asyncio.sleep(2)

            # Simple retry loop
            max_attempts = 10
            base_delay = 3

            for attempt in range(max_attempts):
                self._logger.info(f"Reconnection attempt {attempt+1}/{max_attempts}")
                try:
                    # Use timeout for connect
                    connect_result = await asyncio.wait_for(self.connect(), timeout=45.0)
                    
                    if connect_result:
                        self._logger.info(f"Successfully reconnected on attempt {attempt+1}")
                        self._last_successful_communication = time.time()
                        return True
                    else:
                        self._logger.warning(f"Reconnection attempt {attempt+1} failed verification")
                except asyncio.TimeoutError:
                    self._logger.error(f"Timeout during reconnection attempt {attempt+1}")
                except Exception as e:
                    self._logger.error(f"Reconnection attempt {attempt+1} failed: {e}")
                
                # Apply exponential backoff before next attempt
                if attempt < max_attempts - 1:
                    delay = min(base_delay * (1.5 ** attempt), 30)  # Cap at 30 seconds
                    self._logger.warning(f"Waiting {delay} seconds before next reconnection attempt")
                    await asyncio.sleep(delay)
            
            self._logger.error(f"Failed to reconnect after {max_attempts} attempts")
            return False

        except asyncio.CancelledError:
            self._logger.warning("Reconnection process was cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Unexpected error in reconnection handler: {e}")
            return False
        finally:
            self._reconnection_in_progress = False
            self._reconnection_event.set()  # Signal that reconnection is complete
            if self._connection_lock.locked():
                self._connection_lock.release()
    
    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self.mqtt_client:
            try:
                await asyncio.wait_for(self.mqtt_client.disconnect(), timeout=5.0)
            except asyncio.TimeoutError:
                self._logger.warning("MQTT client disconnect timeout")
            except Exception as e:
                self._logger.warning(f"Error during MQTT client cleanup: {e}")
            finally:
                self.mqtt_client = None
            
        if self.api_client:
            try:
                await asyncio.wait_for(self.api_client.close(), timeout=5.0)
            except asyncio.TimeoutError:
                self._logger.warning("API client close timeout")
            except Exception as e:
                self._logger.warning(f"Error during API client cleanup: {e}")
            finally:
                self.api_client = None
    
    async def disconnect(self) -> None:
        """Disconnect from the API and MQTT broker."""
        await self._cleanup()
        self._logger.info("Disconnected from all services")
    
    def is_connected(self) -> bool:
        """Check if the connector is connected."""
        if not self.mqtt_client:
            return False
        return self.mqtt_client.connected.is_set()
    
    def get_last_communication_time(self) -> float:
        """Get the timestamp of the last successful communication."""
        return self._last_successful_communication