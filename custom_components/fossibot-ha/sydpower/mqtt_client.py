# mqtt_client.py
"""MQTT client for Fossibot devices."""

import asyncio
import time
import random
import threading
from typing import Any, Callable, Coroutine, Dict, List, Optional

import paho.mqtt.client as mqtt

from .const import MQTT_HOST_PROD, MQTT_PORT, MQTT_PASSWORD, MQTT_WEBSOCKET_PATH
from .logger import SmartLogger
from .modbus import REGRequestSettings, parse_registers, high_low_to_int

CONNECTION_CODES = {
    0: "Connection successful",
    1: "Incorrect protocol version",
    2: "Invalid client identifier",
    3: "Server unavailable",
    4: "Bad username or password",
    5: "Not authorized",
}


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
        self._message_cache_ttl = 2
        self._last_cache_cleanup = 0
        self._message_cache_lock = threading.RLock()

        # State tracking
        self._last_successful_communication = time.time()
        self._is_disconnecting = False
        self._subscribed_topics: List[str] = []

        # Custom message handlers
        self._message_handlers: Dict[str, Callable[[str, List[int]], Coroutine]] = {}

        # Disconnect callback
        self.on_disconnect_callback: Optional[Callable] = None

    async def connect(
        self,
        mqtt_token: str,
        device_ids: List[str],
        mqtt_host: str = MQTT_HOST_PROD,
    ) -> None:
        """Connect to MQTT broker and subscribe to device topics."""
        try:
            self._logger.debug(
                "Starting MQTT connection to %s:%s", mqtt_host, MQTT_PORT
            )
            self._is_disconnecting = False
            self.connected.clear()

            hex_string = "".join(
                random.choice("0123456789abcdef") for _ in range(24)
            )
            timestamp_ms = int(time.time() * 1000)
            client_id = f"client_{hex_string}_{timestamp_ms}"

            self.mqtt_client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                transport="websockets",
                protocol=mqtt.MQTTv311,
            )

            self.mqtt_client.ws_set_options(
                path=MQTT_WEBSOCKET_PATH,
                headers={"Sec-WebSocket-Protocol": "mqtt"},
            )
            self.mqtt_client.username_pw_set(
                username=mqtt_token, password=MQTT_PASSWORD
            )
            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_message = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect

            self._device_ids = device_ids

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
            self._logger.error("MQTT connection failed: %s", e)
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
            raise

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT connects."""
        self._logger.debug(
            "MQTT connect result: %s (%s)",
            rc,
            CONNECTION_CODES.get(rc, "Unknown error"),
        )

        if rc != 0:
            self._logger.error(
                "MQTT connection refused: %s",
                CONNECTION_CODES.get(rc, "Unknown error"),
            )
            return

        # Unsubscribe from any prior topics
        for topic in self._subscribed_topics:
            client.unsubscribe(topic)
        self._subscribed_topics = []

        subscribe_topics = []
        for device_mac in self._device_ids:
            topics = [
                (f"{device_mac}/device/response/state", 1),
                (f"{device_mac}/device/response/client/+", 1),
            ]
            for topic, qos in topics:
                subscribe_topics.append((topic, qos))
                self._subscribed_topics.append(topic)

        if not subscribe_topics:
            self._logger.error("No devices found to subscribe to")
            return

        client.subscribe(subscribe_topics)
        self._logger.debug("Subscribed to %d topics", len(subscribe_topics))

        for device_mac in self._device_ids:
            client.publish(
                f"{device_mac}/client/request/data",
                bytes(REGRequestSettings),
                qos=1,
            )

        self.loop.call_soon_threadsafe(self.connected.set)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages with deduplication."""
        try:
            topic = msg.topic
            payload = list(msg.payload)

            # Deduplication
            message_id = f"{topic}:{hash(bytes(payload))}"
            current_time = time.time()

            with self._message_cache_lock:
                if current_time - self._last_cache_cleanup > 30:
                    expired = [
                        k
                        for k, v in self._message_cache.items()
                        if current_time - v > self._message_cache_ttl
                    ]
                    for key in expired:
                        del self._message_cache[key]
                    self._last_cache_cleanup = current_time

                if message_id in self._message_cache:
                    return
                self._message_cache[message_id] = current_time

            # Filter short/invalid messages
            if topic.endswith("/device/response/state") and len(payload) < 10:
                return
            if len(payload) < 8:
                return

            data_bytes = payload[6:]

            if len(data_bytes) % 2 != 0:
                self._logger.warning("Odd byte count in payload from %s", topic)
                return

            registers = [
                high_low_to_int(data_bytes[i], data_bytes[i + 1])
                for i in range(0, len(data_bytes), 2)
            ]

            if len(registers) < 57:
                self._logger.warning(
                    "Too few registers (%d) from %s", len(registers), topic
                )
                return

            device_mac = topic.split("/")[0]

            if device_mac in self._message_handlers:
                asyncio.run_coroutine_threadsafe(
                    self._message_handlers[device_mac](topic, registers),
                    self.loop,
                )
                return

            device_update = parse_registers(registers, topic)

            if device_update:
                self._logger.debug(
                    "Device %s update: %d fields parsed",
                    device_mac,
                    len(device_update),
                )
                asyncio.run_coroutine_threadsafe(
                    self._update_device_data(device_mac, device_update),
                    self.loop,
                )
            else:
                self._logger.warning(
                    "No data extracted from message on %s", topic
                )

        except Exception as e:
            self._logger.error("Error processing MQTT message: %s", e)

    async def _update_device_data(self, device_mac, device_update):
        """Update device data safely."""
        async with self._device_data_lock:
            if device_mac not in self.devices:
                self.devices[device_mac] = {}
            self.devices[device_mac].update(device_update)
            self._last_successful_communication = time.time()
            self.data_updated.set()

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._logger.debug("MQTT disconnected with code: %s", rc)

        if self._is_disconnecting:
            return

        self.loop.call_soon_threadsafe(self.connected.clear)

        if rc != 0:
            self._logger.warning("Unexpected MQTT disconnection (code %s)", rc)
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    self._handle_disconnect_callback(rc)
                )
            )

    async def _handle_disconnect_callback(self, rc):
        """Handle disconnect callback in async context."""
        if self.on_disconnect_callback:
            try:
                await self.on_disconnect_callback(rc)
            except Exception as e:
                self._logger.error("Error in disconnect callback: %s", e)

    def publish_command(self, device_id: str, command: List[int]) -> None:
        """Publish a command to a device."""
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            self._logger.error("Cannot send command: MQTT not connected")
            return

        try:
            topic = f"{device_id}/client/request/data"
            self.mqtt_client.publish(topic, bytes(command), qos=1)
        except Exception as e:
            self._logger.error("Error publishing command: %s", e)

    def register_message_handler(
        self, device_id: str, handler: Callable
    ) -> None:
        """Register a custom message handler for a device."""
        self._message_handlers[device_id] = handler

    def request_data_update(self, device_id: str) -> None:
        """Request a data update from a device."""
        self.publish_command(device_id, REGRequestSettings)

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self.mqtt_client:
            try:
                self._is_disconnecting = True
                self.connected.clear()
                self.data_updated.clear()
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                self._logger.debug("MQTT client disconnected")
                await asyncio.sleep(0.5)
            except Exception as e:
                self._logger.error("Error during MQTT disconnect: %s", e)
            finally:
                self.mqtt_client = None
                self._is_disconnecting = False
