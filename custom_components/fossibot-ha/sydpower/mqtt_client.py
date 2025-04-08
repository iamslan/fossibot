# mqtt_client.py
"""
MQTT client for Fossibot devices.
"""

import asyncio
import time
import random
import threading
from typing import Dict, Any, List, Optional, Callable, Coroutine
import paho.mqtt.client as mqtt

from .const import (
    MQTT_HOST_PROD, MQTT_HOST_DEV, MQTT_PORT, MQTT_PASSWORD, MQTT_WEBSOCKET_PATH
)
from .logger import SmartLogger
from .modbus import REGRequestSettings, parse_registers, high_low_to_int

class MQTTClient:
    """MQTT client for Fossibot device communication."""
    
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.mqtt_client: Optional[mqtt.Client] = None
        self.connected = asyncio.Event()
        self.data_updated = asyncio.Event()
        self.loop = loop
        self._logger = SmartLogger(__name__)
        
        # Device data
        self.devices: Dict[str, Any] = {}
        self._device_data_lock = asyncio.Lock()
        
        # Message deduplication
        self._message_cache: Dict[str, float] = {}
        self._message_cache_ttl = 2  # Time in seconds to keep messages in cache
        self._last_cache_cleanup = 0
        self._message_cache_lock = threading.RLock()
        
        # State tracking
        self._last_successful_communication = time.time()
        self._is_disconnecting = False
        
        # Custom message handlers
        self._message_handlers: Dict[str, Callable[[str, List[int]], Coroutine]] = {}

        # Disconnect callback
        self.on_disconnect_callback = None

    async def connect(self, mqtt_token: str, device_ids: List[str], mqtt_host: str = MQTT_HOST_PROD) -> None:
        """Connect to MQTT broker and subscribe to device topics."""
        try:
            self._logger.debug("Starting MQTT WebSocket connection to %s:%s", mqtt_host, MQTT_PORT)
            
            # Reset disconnecting flag to ensure proper state tracking
            self._is_disconnecting = False
            
            # Clear connected event before starting
            self.connected.clear()
            
            # Generate a unique client ID in the format used by the official app
            # Format: client_[24-character hex string]_[timestamp in milliseconds]
            hex_string = ''.join(random.choice("0123456789abcdef") for _ in range(24))
            timestamp_ms = int(time.time() * 1000)  # Convert to milliseconds
            client_id = f"client_{hex_string}_{timestamp_ms}"
            
            self.mqtt_client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                transport="websockets",
                protocol=mqtt.MQTTv311
            )
            
            # Add storage for subscribed topics
            self.mqtt_client._subscribed_topics = []
            
            self.mqtt_client.ws_set_options(
                path=MQTT_WEBSOCKET_PATH,
                headers={"Sec-WebSocket-Protocol": "mqtt"}
            )
            self.mqtt_client.username_pw_set(
                username=mqtt_token,
                password=MQTT_PASSWORD
            )
            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_message = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect
            
            # Store device IDs for subscription
            self._device_ids = device_ids
            
            self._logger.debug("Attempting MQTT WebSocket connection...")
            # Uncomment the following if TLS is required:
            # self.mqtt_client.tls_set()
            self.mqtt_client.connect(mqtt_host, MQTT_PORT, keepalive=30)
            self.mqtt_client.loop_start()
            
            try:
                await asyncio.wait_for(self.connected.wait(), timeout=30.0)
                self._logger.debug("MQTT connection established successfully")
            except asyncio.TimeoutError:
                self._logger.error("MQTT connection timeout after 30 seconds")
                self.mqtt_client.loop_stop()
                raise
                
        except Exception as e:
            self._logger.error("MQTT connection failed with error: %s", str(e))
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
            raise
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT connects."""
        connection_responses = {
            0: "Connection successful",
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "Connection refused - not authorized",
            6: "Connection refused - not authorized",
            7: "Connection refused - protocol error"
        }
        self._logger.debug("MQTT Connect callback - Result code: %s (%s)", 
                           rc, connection_responses.get(rc, "Unknown error"))
        
        if rc == 0:
            self._logger.debug("MQTT Connection successful, subscribing to topics...")
            
            # Clear any existing subscriptions first to avoid duplicates
            if hasattr(client, '_subscribed_topics'):
                for topic in client._subscribed_topics:
                    client.unsubscribe(topic)
                client._subscribed_topics = []
            else:
                client._subscribed_topics = []
            
            subscribe_topics = []
            
            for device_mac in self._device_ids:
                topics = [
                    (f"{device_mac}/device/response/state", 1),
                    (f"{device_mac}/device/response/client/+", 1)
                ]
                for topic, qos in topics:
                    subscribe_topics.append((topic, qos))
                    client._subscribed_topics.append(topic)  # Track subscribed topics
                
            if subscribe_topics:
                client.subscribe(subscribe_topics)
                self._logger.debug("Subscribed to topics: %s", subscribe_topics)
                for device_mac in self._device_ids:
                    self._logger.debug("Requesting initial data for device %s", device_mac)
                    client.publish(
                        f"{device_mac}/client/request/data",
                        bytes(REGRequestSettings),
                        qos=1
                    )
                # Use loop.call_soon_threadsafe for thread safety
                self.loop.call_soon_threadsafe(self.connected.set)
                self._logger.debug("MQTT setup completed successfully")
            else:
                self._logger.error("No devices found to subscribe to")
        else:
            self._logger.error("Failed to connect to MQTT broker: %s", connection_responses.get(rc, "Unknown error"))
    
    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages with deduplication."""
        try:
            topic = msg.topic
            payload = list(msg.payload)
            
            # Create a simple hash of the message for deduplication
            message_id = f"{topic}:{hash(bytes(payload))}"
            
            # Thread-safe access to the message cache
            should_process = True
            current_time = time.time()
            
            # Use threading.RLock for thread safety in the callback
            with self._message_cache_lock:
                # Periodically clean up old cache entries
                if current_time - self._last_cache_cleanup > 30:  # Every 30 seconds
                    old_entries = []
                    for cache_id, timestamp in self._message_cache.items():
                        if current_time - timestamp > self._message_cache_ttl:
                            old_entries.append(cache_id)
                    for entry in old_entries:
                        self._message_cache.pop(entry, None)
                    self._last_cache_cleanup = current_time
                
                # Skip processing if we've seen this message recently
                if message_id in self._message_cache:
                    should_process = False
                    self._logger.debug("Skipping duplicate message on topic %s", topic)
                else:
                    # Add this message to the cache
                    self._message_cache[message_id] = current_time
            
            # Return early if this is a duplicate message
            if not should_process:
                return
            
            self._logger.debug("MQTT message received on topic: %s", topic)

            # If the message is from a 'state' topic and the payload is very short, ignore it.
            if topic.endswith("/device/response/state"):
                # Adjust the threshold as needed; here we assume fewer than 10 bytes means it's not a full update.
                if len(payload) < 10:
                    self._logger.warning("Ignoring short state message on topic %s: %s", topic, payload)
                    return

            # Check if payload is long enough for processing
            if len(payload) < 8:
                self._logger.warning("MQTT payload too short on topic %s: %s", topic, payload)
                return

            # Separate header (first 6 bytes) from the data bytes.
            header = payload[:6]
            data_bytes = payload[6:]

            # Ensure an even number of bytes for pairing
            if len(data_bytes) % 2 != 0:
                self._logger.warning("Odd number of data bytes in payload from topic %s: %s", topic, data_bytes)
                return

            # Parse registers (each pair of bytes becomes one register)
            registers = [high_low_to_int(data_bytes[i], data_bytes[i+1]) for i in range(0, len(data_bytes), 2)]
            self._logger.debug("Parsed %d registers", len(registers))

            if len(registers) < 57:
                self._logger.warning("Unexpected register count from topic %s: %d", topic, len(registers))
                return

            # Extract device MAC from topic
            device_mac = topic.split('/')[0]
            
            # Check for custom message handlers first
            if device_mac in self._message_handlers:
                asyncio.run_coroutine_threadsafe(
                    self._message_handlers[device_mac](topic, registers),
                    self.loop
                )
                return
                
            # Otherwise use default parser
            device_update = parse_registers(registers, topic)
            
            if device_update:
                self._logger.debug("Device %s update parsed successfully", device_mac)
                # Add logging for specific values if present
                if 'dcInput' in device_update:
                    self._logger.info("Device %s DC Input: %s W", device_mac, device_update['dcInput'])
                if 'soc' in device_update:
                    self._logger.info("Device %s State of Charge: %s%%", device_mac, device_update['soc'])
                if 'soc_s1' in device_update:
                    self._logger.info("Device %s State of Charge S1: %s%%", device_mac, device_update['soc_s1'])
                if 'soc_s2' in device_update:
                    self._logger.info("Device %s State of Charge S2: %s%%", device_mac, device_update['soc_s2'])
                
                # Schedule a safe update
                asyncio.run_coroutine_threadsafe(
                    self._update_device_data(device_mac, device_update),
                    self.loop
                )
            else:
                self._logger.warning("No valid device update extracted from message on topic %s", topic)

        except Exception as e:
            self._logger.error("Error processing MQTT message: %s", str(e))
            
    async def _update_device_data(self, device_mac, device_update):
        """Update device data safely."""
        async with self._device_data_lock:
            if device_mac not in self.devices:
                self.devices[device_mac] = {}
            self.devices[device_mac].update(device_update)
            # Update last communication timestamp
            self._last_successful_communication = time.time()
            # Signal that data has been updated
            self.data_updated.set()
    
    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._logger.debug("MQTT client disconnected with result code: %s", rc)
        
        # If we're intentionally disconnecting, don't trigger reconnection
        if self._is_disconnecting:
            self._logger.debug("Disconnection was intentional, not triggering reconnection")
            return
            
        # Clear flags in thread-safe way
        self.loop.call_soon_threadsafe(self.connected.clear)
        
        # Signal disconnect to any listeners
        if rc != 0:  # Unexpected disconnection
            self._logger.warning("Unexpected MQTT disconnection with code %s", rc)
            # Schedule reconnection task
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_disconnect_callback(rc))
            )
    
    async def _handle_disconnect_callback(self, rc):
        """Handle disconnect callback in an async context."""
        if hasattr(self, 'on_disconnect_callback') and self.on_disconnect_callback:
            try:
                await self.on_disconnect_callback(rc)
            except Exception as e:
                self._logger.error(f"Error in disconnect callback: {e}")
    
    def publish_command(self, device_id: str, command: List[int]) -> None:
        """Publish a command to a device."""
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            self._logger.error("Cannot send command: MQTT client not connected")
            return
            
        try:
            # Enhanced logging
            self._logger.debug(f"Publishing command to {device_id}: {command}")
            topic = f"{device_id}/client/request/data"
            
            self.mqtt_client.publish(
                topic,
                bytes(command),
                qos=1
            )
        except Exception as e:
            self._logger.error(f"Error publishing command: {e}")
    
    def register_message_handler(self, device_id: str, handler: Callable[[str, List[int]], Coroutine]) -> None:
        """Register a custom message handler for a device."""
        self._message_handlers[device_id] = handler
    
    def request_data_update(self, device_id: str) -> None:
        """Request a data update from a device."""
        self.publish_command(device_id, REGRequestSettings)
    
    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self.mqtt_client:
            try:
                # Set flag to prevent reconnection attempts during intentional disconnect
                self._is_disconnecting = True
                
                # Clear events to prevent any waiting code from proceeding
                self.connected.clear()
                self.data_updated.clear()
                
                # Properly disconnect
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                
                self._logger.info("MQTT client disconnected successfully")
                
                # Small delay to allow disconnect to complete
                await asyncio.sleep(0.5)
            except Exception as e:
                self._logger.error("Error during MQTT disconnect: %s", str(e))
            finally:
                self.mqtt_client = None
                self._is_disconnecting = False