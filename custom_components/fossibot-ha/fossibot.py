#!/usr/bin/env python3
"""
Fossibot API Client for Home Assistant.
"""

import asyncio
import aiohttp
import time
import hmac
import hashlib
import json
import logging
import random
from typing import Dict, Any, Optional

import paho.mqtt.client as mqtt

# -----------------------------------------------------------------------------
# Configure root logging (adjust as needed)
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# -----------------------------------------------------------------------------
# MODBUS command conversion functions
# -----------------------------------------------------------------------------
def int_to_high_low(value: int) -> dict:
    """Convert an integer to a high/low dictionary (16-bit)."""
    return {'low': value & 0xff, 'high': (value >> 8) & 0xff}

def high_low_to_int(high: int, low: int) -> int:
    """Convert high and low parts to a 16-bit integer."""
    return ((high & 0xff) << 8) | (low & 0xff)

def zi(e: int) -> dict:
    return {'low': e & 0xff, 'high': (e >> 8) & 0xff}

def ta(arr: list) -> int:
    """Compute checksum using the algorithm from JS function ta."""
    t = 0xffff
    for byte in arr:
        t ^= byte
        for _ in range(8):
            if t & 1:
                t = (t >> 1) ^ 40961
            else:
                t >>= 1
    return t & 0xffff

def sa(e: int, t: int, n: list, o: bool) -> list:
    """Build the command array and append the checksum."""
    r = [e, t] + n
    cs = zi(ta(r))
    if o:
        r += [cs['low'], cs['high']]
    else:
        r += [cs['high'], cs['low']]
    return r

def aa(e: int, t: int, n: list, o: bool) -> list:
    """Wrap getWriteModbus: convert feature number into two bytes and build command."""
    r = zi(t)
    return sa(e, 6, [r['high'], r['low']] + n, o)

def ia(e: int, t: int, n: int, o: bool) -> list:
    """Wrap getReadModbus: prepare a read command."""
    r = zi(t)
    i_val = n & 0xff
    a_val = n >> 8
    return sa(e, 3, [r['high'], r['low'], a_val, i_val], o)

def get_write_modbus(address: int, feature: int, value: int) -> list:
    """Equivalent of getWriteModbus in JS."""
    a = int_to_high_low(value)
    return aa(address, feature, [a['high'], a['low']], False)

def get_read_modbus(address: int, count: int) -> list:
    """Equivalent of getReadModbus in JS."""
    return ia(address, 0, count, False)

# -----------------------------------------------------------------------------
# Register definitions and pre-defined commands
# -----------------------------------------------------------------------------
REGISTER_MODBUS_ADDRESS = 17
REGISTER_TOTAL_INPUT = 6
REGISTER_DC_INPUT = 4
REGISTER_MAXIMUM_CHARGING_CURRENT = 20
REGISTER_USB_OUTPUT = 24
REGISTER_DC_OUTPUT = 25
REGISTER_AC_OUTPUT = 26
REGISTER_LED = 27
REGISTER_TOTAL_OUTPUT = 39
REGISTER_ACTIVE_OUTPUT_LIST = 41
REGISTER_STATE_OF_CHARGE = 56
REGISTER_AC_SILENT_CHARGING = 57

# Pre-defined commands
REGRequestSettings   = get_read_modbus(REGISTER_MODBUS_ADDRESS, 80)
REGDisableUSBOutput  = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 0)
REGEnableUSBOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
REGDisableDCOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 0)
REGEnableDCOutput    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 1)
REGDisableACOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 0)
REGEnableACOutput    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 1)
REGDisableLED        = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 0)
REGEnableLEDAlways   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 1)

# -----------------------------------------------------------------------------
# Configuration constants and device info
# -----------------------------------------------------------------------------
ENDPOINT = "https://api.next.bspapp.com/client"
CLIENT_SECRET = "5rCEdl/nx7IgViBe4QYRiQ=="
MQTT_HOST = "mqtt.sydpower.com"
MQTT_PORT = 8083
MQTT_CLIENT_ID = "client_helloyou"
MQTT_PASSWORD = "helloyou"
MQTT_WEBSOCKET_PATH = "/mqtt"

# -----------------------------------------------------------------------------
# Smart Logger Class
# -----------------------------------------------------------------------------
class SmartLogger:
    """Smart logging helper that adapts logging level based on system state."""
    
    def __init__(self, logger_name: str):
        self._logger = logging.getLogger(logger_name)
        self._error_count = 0
        self._last_error_time = 0
        self._error_window = 300  # seconds (5 minutes)
        self._verbose_mode = False
        self._last_status = {}

    def _should_log_verbose(self) -> bool:
        return True
        """Determine if we should log verbose information."""
        current_time = time.time()
        if current_time - self._last_error_time > self._error_window:
            self._error_count = 0
            self._verbose_mode = False
        return self._verbose_mode

    def error(self, msg: str, *args, **kwargs):
        """Log error and increase error tracking."""
        current_time = time.time()
        self._error_count += 1
        self._last_error_time = current_time
        
        if self._error_count >= 3:
            self._verbose_mode = True
        
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, is_status_update=False, **kwargs):
        """Smart debug logging that reduces redundant status messages."""
        if is_status_update and not self._should_log_verbose():
            status_key = msg
            current_args = str(args)
            if (status_key not in self._last_status or 
                self._last_status[status_key] != current_args):
                self._logger.debug(msg, *args, **kwargs)
                self._last_status[status_key] = current_args
        elif self._should_log_verbose():
            self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

# -----------------------------------------------------------------------------
# SydpowerConnector Class
# -----------------------------------------------------------------------------
class SydpowerConnector:
    """Main class for Fossibot/Sydpower API connection."""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token = None
        self.mqtt_client = None
        self.devices: Dict[str, Any] = {}
        self._mqtt_connected = asyncio.Event()
        self._data_updated = asyncio.Event()
        self.loop = None

        # Connection management
        self._connection_lock = asyncio.Lock()
        self._reconnection_in_progress = False
        self._reconnection_event = asyncio.Event()
        self._last_reconnection_attempt = 0
        self._min_reconnection_interval = 5
        self._last_successful_communication = time.time()

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None
        self._reconnect_attempt = 0
        self._mqtt_token = None
        
        # Logging
        self._logger = SmartLogger(__name__)

    async def _ensure_session(self):
        """Ensure that a persistent aiohttp session exists."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._logger.debug("Created new aiohttp session with timeout %s seconds", timeout.total)

    def _generate_device_info(self) -> dict:
        """Generate device information for API calls."""
        deviceId = "".join(random.choice("0123456789ABCDEF") for _ in range(32))
        return {
            "PLATFORM": "app",
            "OS": "android",
            "APPID": "__UNI__55F5E7F",
            "DEVICEID": deviceId,
            "channel": "google",
            "scene": 1001,
            "appId": "__UNI__55F5E7F",
            "appLanguage": "en",
            "appName": "BrightEMS",
            "appVersion": "1.2.3",
            "appVersionCode": 123,
            "appWgtVersion": "1.2.3",
            "browserName": "chrome",
            "browserVersion": "130.0.6723.86",
            "deviceBrand": "Samsung",
            "deviceId": deviceId,
            "deviceModel": "SM-A426B",
            "deviceType": "phone",
            "osName": "android",
            "osVersion": 10,
            "romName": "Android",
            "romVersion": 10,
            "ua": "Mozilla/5.0 (Linux; Android 10; SM-A426B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.86 Mobile Safari/537.36",
            "uniPlatform": "app",
            "uniRuntimeVersion": "4.24",
            "locale": "en",
            "LOCALE": "en"
        }

    async def _api(self, config: dict) -> dict:
        """Make an API call to Fossibot with retries and smart logging."""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                await self._ensure_session()
                
                if self._logger._should_log_verbose():
                    self._logger.debug("API call attempt %d/%d with config: %s",
                                       attempt + 1, max_retries, config)
                
                method = "serverless.function.runtime.invoke"
                params = "{}"
                client_info_dict = self._generate_device_info()
                
                route = config.get("route")
                if route == "api-auth":
                    method = "serverless.auth.user.anonymousAuthorize"
                elif route == "api-login":
                    params = json.dumps({
                        "functionTarget": "router",
                        "functionArgs": {
                            "$url": "user/pub/login",
                            "data": {
                                "locale": "en",
                                "username": config.get("username"),
                                "password": config.get("password")
                            },
                            "clientInfo": client_info_dict
                        }
                    })
                elif route == "api-mqtt":
                    params = json.dumps({
                        "functionTarget": "router",
                        "functionArgs": {
                            "$url": "common/emqx.getAccessToken",
                            "data": {"locale": "en"},
                            "clientInfo": client_info_dict,
                            "uniIdToken": config.get("accessToken")
                        }
                    })
                elif route == "api-devices":
                    params = json.dumps({
                        "functionTarget": "router",
                        "functionArgs": {
                            "$url": "client/device/kh/getList",
                            "data": {"locale": "en", "pageIndex": 1, "pageSize": 100},
                            "clientInfo": client_info_dict,
                            "uniIdToken": config.get("accessToken")
                        }
                    })

                data = {
                    "method": method,
                    "params": params,
                    "spaceId": "mp-6c382a98-49b8-40ba-b761-645d83e8ee74",
                    "timestamp": int(time.time() * 1000)
                }
                
                if "authorizeToken" in config:
                    data["token"] = config["authorizeToken"]

                # Generate signature
                items = []
                for key in sorted(data.keys()):
                    if data[key]:
                        items.append(f"{key}={data[key]}")
                query_str = "&".join(items)
                signature = hmac.new(
                    CLIENT_SECRET.encode('utf-8'),
                    query_str.encode('utf-8'),
                    hashlib.md5
                ).hexdigest()

                headers = {
                    "Content-Type": "application/json",
                    "x-serverless-sign": signature,
                    "user-agent": client_info_dict["ua"]
                }

                async with self._session.post(ENDPOINT, json=data, headers=headers) as resp:
                    resp_json = await resp.json()
                    if not resp_json.get('data'):
                        raise Exception(f"API request failed: {resp_json}")
                    if (route == "api-login" and not resp_json.get('data', {}).get('token')):
                        raise Exception(f"Login failed - no token in response: {resp_json}")
                    return resp_json

            except Exception as e:
                self._logger.error("API call failed (attempt %d/%d): %s",
                                   attempt + 1, max_retries, str(e))
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (attempt + 1))

    async def _perform_full_connection_cycle(self) -> None:
        """Perform a complete connection cycle from scratch."""
        try:
            # Step 1: Get anonymous auth token
            auth_resp = await self._api({"route": "api-auth"})
            authorize_token = auth_resp.get("data", {}).get("accessToken")
            self._logger.debug("Fetched anonymous authorized token: %s", authorize_token)

            # Step 2: Login and get access token
            login_resp = await self._api({
                "route": "api-login",
                "authorizeToken": authorize_token,
                "username": self.username,
                "password": self.password
            })
            self.access_token = login_resp.get("data", {}).get("token")
            self._logger.debug("Fetched logged-in access token: %s", self.access_token)

            # Step 3: Get MQTT token
            mqtt_resp = await self._api({
                "route": "api-mqtt",
                "authorizeToken": authorize_token,
                "accessToken": self.access_token
            })
            self._mqtt_token = mqtt_resp.get("data", {}).get("access_token")
            self._logger.debug("Fetched MQTT access token: %s", self._mqtt_token)

            # Step 4: Get devices list
            devices_resp = await self._api({
                "route": "api-devices",
                "authorizeToken": authorize_token,
                "accessToken": self.access_token
            })
            devices = devices_resp.get("data", {}).get("rows", [])
            device_ids = []
            for device in devices:
                dev_id = device.get("device_id", "").replace(":", "")
                self.devices[dev_id] = device
                device_ids.append(dev_id)
            self._logger.debug("Fetched devices: %s", device_ids)

            if not device_ids:
                raise Exception("No devices returned from API")

            # Step 5: Start MQTT connection
            await self._start_mqtt(self._mqtt_token, device_ids)

        except Exception as e:
            self._logger.error("Full connection cycle failed: %s", str(e))
            raise

    async def _start_mqtt(self, access_token: str, device_ids: list) -> None:
        """Start the MQTT connection using WebSocket."""
        try:
            self._logger.debug("Starting MQTT WebSocket connection to %s:%s", MQTT_HOST, MQTT_PORT)
            
            # Generate a unique client ID using timestamp and random string
            unique_id = ''.join(random.choice("0123456789ABCDEF") for _ in range(8))
            timestamp = int(time.time())
            client_id = f"{MQTT_CLIENT_ID}_{timestamp}_{unique_id}"
            
            self.mqtt_client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                transport="websockets",
                protocol=mqtt.MQTTv311
            )
            
            self.mqtt_client.ws_set_options(
                path=MQTT_WEBSOCKET_PATH,
                headers={"Sec-WebSocket-Protocol": "mqtt"}
            )
            self.mqtt_client.username_pw_set(
                username=access_token,
                password=MQTT_PASSWORD
            )
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message
            self.mqtt_client.on_disconnect = self._on_disconnect
            
            self._logger.debug("Attempting MQTT WebSocket connection...")
            # Uncomment the following if TLS is required:
            # self.mqtt_client.tls_set()
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            self.mqtt_client.loop_start()
            
            try:
                await asyncio.wait_for(self._mqtt_connected.wait(), timeout=30.0)
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

    def _on_mqtt_connect(self, client, userdata, flags, rc):
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
            subscribe_topics = []
            for device_mac in self.devices.keys():
                topics = [
                    (f"{device_mac}/device/response/state", 1),
                    (f"{device_mac}/device/response/client/+", 1)
                ]
                subscribe_topics.extend(topics)
                self._logger.debug("Adding subscription topics for device %s: %s", device_mac, topics)
                
            if subscribe_topics:
                client.subscribe(subscribe_topics)
                self._logger.debug("Subscribed to topics: %s", subscribe_topics)
                for device_mac in self.devices.keys():
                    self._logger.debug("Requesting initial data for device %s", device_mac)
                    client.publish(
                        f"{device_mac}/client/request/data",
                        bytes(REGRequestSettings),
                        qos=1
                    )
                self.loop.call_soon_threadsafe(self._mqtt_connected.set)
                self._logger.debug("MQTT setup completed successfully")
            else:
                self._logger.error("No devices found to subscribe to")
        else:
            self._logger.error("Failed to connect to MQTT broker: %s", connection_responses.get(rc, "Unknown error"))

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            self._logger.debug("MQTT message received on topic: %s", topic)

            # Convert payload to list of bytes
            payload = list(msg.payload)
            self._logger.debug("Raw payload (%d bytes): %s", len(payload), payload)

            # If the message is from a 'state' topic and the payload is very short, ignore it.
            if topic.endswith("/device/response/state"):
                # Adjust the threshold as needed; here we assume fewer than 10 bytes means it's not a full update.
                if len(payload) < 10:
                    self._logger.warning("Ignoring short state message on topic %s: %s", topic, payload)
                    return

            # Check if payload is long enough for processing
            if len(payload) < 8:
                self._logger.warning("MQTT payload too short on topic %s: %s", topic, payload)
                self.loop.call_soon_threadsafe(self._data_updated.set)
                return

            # Separate header (first 6 bytes) from the data bytes.
            header = payload[:6]
            data_bytes = payload[6:]
            self._logger.debug("Header bytes: %s", header)
            self._logger.debug("Data bytes: %s", data_bytes)

            # Ensure an even number of bytes for pairing
            if len(data_bytes) % 2 != 0:
                self._logger.warning("Odd number of data bytes in payload from topic %s: %s", topic, data_bytes)
                self.loop.call_soon_threadsafe(self._data_updated.set)
                return

            # Parse registers (each pair of bytes becomes one register)
            registers = [high_low_to_int(data_bytes[i], data_bytes[i+1]) for i in range(0, len(data_bytes), 2)]
            self._logger.debug("Parsed %d registers: %s", len(registers), registers)

            if len(registers) < 57:
                self._logger.warning("Unexpected register count from topic %s: %d", topic, len(registers))
                self.loop.call_soon_threadsafe(self._data_updated.set)
                return

            device_update = {}
            # If we have exactly 81 registers, assume a full update.
            if len(registers) == 81:
                if 'device/response/client/04' in topic:
                    active_outputs = format(registers[41], '016b')
                    device_update.update({
                        "soc": round(registers[56] / 1000 * 100, 1),
                        "dcInput": registers[4],
                        "totalInput": registers[6],
                        "totalOutput": registers[39],
                        "usbOutput": active_outputs[9] == '1',
                        "dcOutput": active_outputs[10] == '1',
                        "acOutput": active_outputs[11] == '1',
                        "ledOutput": active_outputs[12] == '1'
                    })
                elif 'device/response/client/data' in topic:
                    device_update.update({
                        "maximumChargingCurrent": registers[20],
                        "acSilentCharging": (registers[57] == 1),
                        "usbStandbyTime": registers[59],
                        "acStandbyTime": registers[60],
                        "dcStandbyTime": registers[61],
                        "screenRestTime": registers[62],
                        "stopChargeAfter": registers[63],
                        "dischargeLowerLimit": registers[66],
                        "acChargingUpperLimit": registers[67],
                        "wholeMachineUnusedTime": registers[68]
                    })
            else:
                # Handle unexpected register counts with a partial update if possible.
                self._logger.warning(
                    "Register count from topic %s does not equal 81 (got %d). Attempting partial update.",
                    topic, len(registers)
                )
                try:
                    if len(registers) >= 57:
                        device_update["soc"] = round(registers[56] / 1000 * 100, 1)
                        self._logger.debug("Partial update: SOC set to %s", device_update["soc"])
                    else:
                        self._logger.warning("Not enough registers to perform even a partial update.")
                except Exception as e:
                    self._logger.error("Error during partial update: %s", str(e))

            device_mac = topic.split('/')[0]
            if device_update:
                self._logger.debug("Device %s update parsed: %s", device_mac, device_update)
                self.devices.setdefault(device_mac, {}).update(device_update)
            else:
                self._logger.warning("No valid device update extracted from message on topic %s", topic)

            # Update last communication timestamp and signal that data has been updated.
            self._last_successful_communication = time.time()
            self.loop.call_soon_threadsafe(self._data_updated.set)

        except Exception as e:
            self._logger.error("Error processing MQTT message: %s", str(e))
            self.loop.call_soon_threadsafe(self._data_updated.set)


    async def _handle_reconnection(self):
        """Handle reconnection with proper backoff and state management."""
        current_time = time.time()
        if current_time - self._last_reconnection_attempt < self._min_reconnection_interval:
            self._logger.debug("Skipping reconnection attempt - too soon since last attempt")
            return

        async with self._connection_lock:
            if self._reconnection_in_progress:
                self._logger.debug("Reconnection already in progress, waiting...")
                await self._reconnection_event.wait()
                return

            try:
                self._reconnection_in_progress = True
                self._last_reconnection_attempt = current_time
                self._reconnection_event.clear()

                # Clean up existing connection
                if self.mqtt_client:
                    try:
                        self.mqtt_client.loop_stop()
                        self.mqtt_client.disconnect()
                    except Exception as e:
                        self._logger.debug("Error stopping existing MQTT client: %s", str(e))
                    finally:
                        self.mqtt_client = None

                self._mqtt_connected.clear()
                self._data_updated.clear()

                # Reset tokens and devices list
                self.access_token = None
                self._mqtt_token = None
                self.devices.clear()

                # Exponential backoff parameters
                max_attempts = 5
                base_delay = 1

                for attempt in range(max_attempts):
                    try:
                        await self._perform_full_connection_cycle()
                        self._reconnect_attempt = 0
                        self._logger.info("Successfully completed full reconnection cycle")
                        break
                    except Exception as e:
                        delay = min(base_delay * (2 ** attempt), 60)
                        if attempt < max_attempts - 1:
                            self._logger.warning(
                                "Reconnection attempt %d failed: %s. Retrying in %d seconds...",
                                attempt + 1, str(e), delay
                            )
                            await asyncio.sleep(delay)
                        else:
                            self._logger.error(
                                "Final reconnection attempt %d failed: %s",
                                attempt + 1, str(e)
                            )
                else:
                    self._logger.error("Failed to reconnect after %d attempts", max_attempts)

            finally:
                self._reconnection_in_progress = False
                self._reconnection_event.set()

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._logger.debug("MQTT client disconnected with result code: %s", rc)
        self.loop.call_soon_threadsafe(self._mqtt_connected.clear)
        
        if rc != 0:  # Unexpected disconnection
            if not self._reconnection_in_progress:
                self._logger.info("MQTT disconnected unexpectedly. Attempting reconnection...")
                if self.loop and not self.loop.is_closed():
                    asyncio.run_coroutine_threadsafe(self._handle_reconnection(), self.loop)

    async def connect(self):
        """Initial connection to the API and MQTT broker."""
        async with self._connection_lock:
            if self.loop is None:
                self.loop = asyncio.get_running_loop()

            if self._reconnection_in_progress:
                self._logger.debug("Connection attempt while reconnection in progress, waiting...")
                await self._reconnection_event.wait()
                if self.mqtt_client and self.mqtt_client.is_connected():
                    return

            self._reconnect_attempt = 0
            await self._perform_full_connection_cycle()

    async def get_data(self) -> Dict[str, Any]:
        """Get the latest data from devices."""
        if not self.mqtt_client:
            self._logger.debug("MQTT client not initialized, calling connect()")
            await self.connect()
            await self._mqtt_connected.wait()

        self._data_updated.clear()

        if not self.devices:
            self._logger.warning("No devices available to request data from")
            return {}

        num_devices = len(self.devices)
        self._logger.debug("Publishing data request for %d device(s)", num_devices)

        for device_mac in self.devices.keys():
            self._logger.debug("Publishing data request for device: %s", device_mac)
            self.mqtt_client.publish(
                f"{device_mac}/client/request/data",
                bytes(REGRequestSettings),
                qos=1
            )

        start_time = time.time()
        self._logger.debug("Waiting for device data update (timeout = 30 seconds)...")
        try:
            await asyncio.wait_for(self._data_updated.wait(), timeout=30.0)
            elapsed = time.time() - start_time
            self._logger.debug("Device data update event received after %.2f seconds", elapsed)
            self._logger.debug("Devices updated: %s", list(self.devices.keys()))
        except asyncio.TimeoutError:
            self._logger.warning("Timeout waiting for device data update after 30 seconds. Devices: %s", list(self.devices.keys()))

        self._logger.debug("Returning device data: %s", self.devices)
        return self.devices


    async def run_command(self, device_id: str, command: str, value=None) -> None:
        """Run a command on a device."""
        if not self.mqtt_client:
            await self.connect()
            await self._mqtt_connected.wait()
        command_bytes = None
        if command in globals():
            command_obj = globals()[command]
            if callable(command_obj) and value is not None:
                command_bytes = command_obj(value)
            else:
                command_bytes = command_obj
        if command_bytes:
            self.mqtt_client.publish(
                f"{device_id}/client/request/data",
                bytes(command_bytes),
                qos=1
            )
            await asyncio.sleep(1)
        else:
            raise ValueError(f"Unknown command: {command}")

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker and close the HTTP session."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                self._logger.info("MQTT client disconnected successfully")
            except Exception as e:
                self._logger.error("Error during MQTT disconnect: %s", str(e))
            finally:
                self.mqtt_client = None
                self._mqtt_connected.clear()
                self._data_updated.clear()
        if self._session:
            try:
                await self._session.close()
                self._logger.debug("HTTP session closed")
            except Exception as e:
                self._logger.error("Error closing HTTP session: %s", str(e))
            finally:
                self._session = None

# -----------------------------------------------------------------------------
# Main (for testing)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    async def main():
        # Replace these with your actual username and password.
        connector = SydpowerConnector("your_username", "your_password")
        try:
            await connector.connect()
            # Allow some time for MQTT connection and data retrieval.
            await asyncio.sleep(5)
            data = await connector.get_data()
            print("Device data:", data)
        except Exception as e:
            print("Error:", e)
        finally:
            await connector.disconnect()

    asyncio.run(main())
