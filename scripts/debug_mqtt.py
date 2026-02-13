"""Debug script to observe raw MQTT messages from a Fossibot battery.

Usage:
    py scripts/debug_mqtt.py                    # reads .env file
    py scripts/debug_mqtt.py <user> <password>  # explicit credentials

Connects to the MQTT broker, logs every message with timing,
and runs a sequence of tests to see what the battery responds to.
No Home Assistant needed.
"""

import asyncio
import json
import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# Reuse the sydpower package directly
# ---------------------------------------------------------------------------
sys.path.insert(0, "custom_components/fossibot-ha")

from sydpower.api_client import APIClient
from sydpower.const import MQTT_HOSTS_PROD, MQTT_PORT, MQTT_PASSWORD, MQTT_WEBSOCKET_PATH
from sydpower.modbus import (
    get_read_modbus, get_read_input_modbus,
    parse_registers, high_low_to_int,
    REGISTER_MODBUS_ADDRESS,
)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Install paho-mqtt first:  py -m pip install paho-mqtt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Raw MQTT session — no dedup, no filtering, just log everything
# ---------------------------------------------------------------------------

class DebugMQTTSession:
    """Single MQTT session that logs every message."""

    def __init__(self, loop, mqtt_token, device_mac, host, port):
        self.loop = loop
        self.mqtt_token = mqtt_token
        self.device_mac = device_mac
        self.host = host
        self.port = port
        self.connected = asyncio.Event()
        self.messages = []  # (elapsed_ms, topic_suffix, register_count, parsed_fields)
        self._t0 = None
        self.client = None

    def _elapsed(self):
        return int((time.time() - self._t0) * 1000) if self._t0 else 0

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            print(f"    MQTT connect failed: rc={rc}")
            self.loop.call_soon_threadsafe(self.connected.set)
            return

        client.subscribe([
            (f"{self.device_mac}/device/response/state", 1),
            (f"{self.device_mac}/device/response/client/+", 1),
        ])
        self.loop.call_soon_threadsafe(self.connected.set)

    def _on_message(self, client, userdata, msg):
        elapsed = self._elapsed()
        topic = msg.topic
        payload = list(msg.payload)

        # Extract topic suffix for readability
        parts = topic.split("/", 1)
        suffix = parts[1] if len(parts) > 1 else topic

        if len(payload) < 8:
            print(f"    +{elapsed:5d}ms  {suffix}  ({len(payload)} bytes, too short)")
            return

        data_bytes = payload[6:]
        if len(data_bytes) % 2 != 0:
            print(f"    +{elapsed:5d}ms  {suffix}  ({len(data_bytes)} data bytes, odd)")
            return

        registers = [
            high_low_to_int(data_bytes[i], data_bytes[i + 1])
            for i in range(0, len(data_bytes), 2)
        ]

        parsed = parse_registers(registers, topic) if len(registers) >= 57 else {}
        field_names = list(parsed.keys()) if parsed else []

        self.messages.append((elapsed, suffix, len(registers), parsed))

        tag = ""
        if "client/04" in suffix:
            tag = " [SENSORS]"
        elif "client/data" in suffix:
            tag = " [SETTINGS]"
        elif "response/state" in suffix:
            tag = " [STATE]"

        print(f"    +{elapsed:5d}ms  {suffix}{tag}")
        print(f"             {len(registers)} registers -> {len(parsed)} fields: {field_names}")

    async def connect(self):
        """Connect and return True if successful."""
        self._t0 = time.time()
        self.connected.clear()
        self.messages.clear()

        hex_str = "".join(random.choice("0123456789abcdef") for _ in range(24))
        client_id = f"debug_{hex_str}_{int(time.time() * 1000)}"

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id, clean_session=True,
                transport="websockets", protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            self.client = mqtt.Client(
                client_id=client_id, clean_session=True,
                transport="websockets", protocol=mqtt.MQTTv311,
            )

        self.client.ws_set_options(
            path=MQTT_WEBSOCKET_PATH,
            headers={"Sec-WebSocket-Protocol": "mqtt"},
        )
        self.client.username_pw_set(self.mqtt_token, MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(self.host, self.port, keepalive=30)
        except Exception as e:
            print(f"    Connection error: {e}")
            return False

        self.client.loop_start()

        try:
            await asyncio.wait_for(self.connected.wait(), timeout=10.0)
            return True
        except asyncio.TimeoutError:
            print("    Connection timeout!")
            return False

    def send_func03(self, label="func 03 (settings)"):
        """Send a read holding registers command (func 03)."""
        cmd = get_read_modbus(REGISTER_MODBUS_ADDRESS, 80)
        self.client.publish(
            f"{self.device_mac}/client/request/data",
            bytes(cmd), qos=1,
        )
        print(f"    +{self._elapsed():5d}ms  >>> SENT {label}")

    def send_func04(self, label="func 04 (sensors)"):
        """Send a read input registers command (func 04)."""
        cmd = get_read_input_modbus(REGISTER_MODBUS_ADDRESS, 80)
        self.client.publish(
            f"{self.device_mac}/client/request/data",
            bytes(cmd), qos=1,
        )
        print(f"    +{self._elapsed():5d}ms  >>> SENT {label}")

    async def wait(self, seconds, label=""):
        """Wait and collect messages."""
        if label:
            print(f"    ... waiting {seconds}s {label}")
        await asyncio.sleep(seconds)

    async def disconnect(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            await asyncio.sleep(0.5)

    def summary(self):
        sensor_count = sum(1 for _, s, _, _ in self.messages if "client/04" in s)
        settings_count = sum(1 for _, s, _, _ in self.messages if "client/data" in s)
        other_count = len(self.messages) - sensor_count - settings_count
        total_fields = set()
        for _, _, _, parsed in self.messages:
            total_fields.update(parsed.keys())
        return sensor_count, settings_count, other_count, total_fields


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def run_test(label, session, steps):
    """Run a single test: connect, execute steps, disconnect, summarize."""
    print(f"\n{'-'*60}")
    print(f"  TEST: {label}")
    print(f"{'-'*60}")

    if not await session.connect():
        print("    FAILED to connect")
        return

    for step in steps:
        await step(session)

    s, st, o, fields = session.summary()
    print(f"\n    RESULT: {s} sensor msg, {st} settings msg, {o} other")
    print(f"    Total unique fields ({len(fields)}): {sorted(fields)}")

    await session.disconnect()
    await asyncio.sleep(2)  # gap between tests


async def main(username, password):
    # -- Authenticate ------------------------------------------
    print("Authenticating...")
    api = APIClient()
    await api.authenticate(username, password)
    mqtt_info = await api.get_mqtt_token()
    devices = await api.get_devices()
    await api.close()

    mqtt_token = mqtt_info["token"]
    api_host = mqtt_info.get("mqtt_host", "")
    device_mac = list(devices.keys())[0]

    # Build host list: API-provided first, then fallbacks
    hosts = []
    if api_host:
        hosts.append(api_host)
    for h in MQTT_HOSTS_PROD:
        if h not in hosts:
            hosts.append(h)

    print(f"Device:    {device_mac}")
    print(f"Hosts to try: {hosts}")

    # Find a working host
    loop = asyncio.get_running_loop()
    working_host = None

    for host in hosts:
        print(f"\nTrying {host}:{MQTT_PORT} ...")
        test_session = DebugMQTTSession(loop, mqtt_token, device_mac, host, MQTT_PORT)
        try:
            if await test_session.connect():
                print(f"  Connected to {host}!")
                working_host = host
                await test_session.disconnect()
                await asyncio.sleep(2)
                break
            else:
                print(f"  Failed (timeout)")
        except Exception as e:
            print(f"  Failed: {e}")
        finally:
            await test_session.disconnect()

    if not working_host:
        print("\nCould not connect to any MQTT host!")
        return

    print(f"\nUsing host: {working_host}")

    def make_session():
        return DebugMQTTSession(loop, mqtt_token, device_mac, working_host, MQTT_PORT)

    # -- Test 1: Just connect, don't send anything -------------
    async def test1_steps(s):
        await s.wait(6, "(passive — only auto-push)")

    await run_test(
        "Passive connect (no commands sent)",
        make_session(),
        [lambda s: test1_steps(s)],
    )

    # -- Test 2: Send func 03 immediately after connect --------
    async def test2_steps(s):
        s.send_func03("func 03 right after connect")
        await s.wait(6, "(waiting for response)")

    await run_test(
        "Send func 03 immediately after connect",
        make_session(),
        [lambda s: test2_steps(s)],
    )

    # -- Test 3: Send func 04 immediately after connect --------
    async def test3_steps(s):
        s.send_func04("func 04 right after connect")
        await s.wait(6, "(waiting for response)")

    await run_test(
        "Send func 04 immediately after connect",
        make_session(),
        [lambda s: test3_steps(s)],
    )

    # -- Test 4: Wait for auto-push, then send func 03 --------
    async def test4_steps(s):
        await s.wait(3, "(let auto-push arrive)")
        s.send_func03("func 03 after auto-push consumed")
        await s.wait(6, "(waiting for settings response)")

    await run_test(
        "Wait for auto-push, then send func 03",
        make_session(),
        [lambda s: test4_steps(s)],
    )

    # -- Test 5: Wait for auto-push, then send func 04 --------
    async def test5_steps(s):
        await s.wait(3, "(let auto-push arrive)")
        s.send_func04("func 04 after auto-push consumed")
        await s.wait(6, "(waiting for sensor response)")

    await run_test(
        "Wait for auto-push, then send func 04",
        make_session(),
        [lambda s: test5_steps(s)],
    )

    # -- Test 6: Send func 03 then func 04 with gap -----------
    async def test6_steps(s):
        s.send_func03("func 03 first")
        await s.wait(2)
        s.send_func04("func 04 second")
        await s.wait(6, "(waiting for both)")

    await run_test(
        "Send func 03 first, then func 04 (2s gap)",
        make_session(),
        [lambda s: test6_steps(s)],
    )

    # -- Test 7: Send func 04 then func 03 with gap -----------
    async def test7_steps(s):
        s.send_func04("func 04 first")
        await s.wait(2)
        s.send_func03("func 03 second")
        await s.wait(6, "(waiting for both)")

    await run_test(
        "Send func 04 first, then func 03 (2s gap)",
        make_session(),
        [lambda s: test7_steps(s)],
    )

    # -- Done --------------------------------------------------
    print(f"\n{'='*60}")
    print("  ALL TESTS COMPLETE")
    print(f"{'='*60}\n")


def load_env(path=".env"):
    """Load key=value pairs from a .env file into os.environ."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


if __name__ == "__main__":
    load_env()

    if len(sys.argv) == 3:
        user, pw = sys.argv[1], sys.argv[2]
    else:
        user = os.environ.get("FOSSIBOT_USERNAME", "")
        pw = os.environ.get("FOSSIBOT_PASSWORD", "")

    if not user or not pw:
        print(f"Usage: py {sys.argv[0]} <username> <password>")
        print("  or set FOSSIBOT_USERNAME / FOSSIBOT_PASSWORD in .env")
        sys.exit(1)

    asyncio.run(main(user, pw))
