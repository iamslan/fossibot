"""Standalone script to reverse-engineer Fossibot API responses.

Usage:
    py scripts/discover_mqtt.py <username> <password>

Authenticates against the Fossibot cloud API, dumps every response,
and tests MQTT connectivity against all candidate hosts.
No Home Assistant needed.
"""

import asyncio
import hashlib
import hmac
import json
import random
import sys
import time

try:
    import aiohttp
except ImportError:
    print("Install aiohttp first:  py -m pip install aiohttp")
    sys.exit(1)

ENDPOINT = "https://api.next.bspapp.com/client"
CLIENT_SECRET = "5rCEdl/nx7IgViBe4QYRiQ=="
FALLBACK_HOST = "mqtt.sydpower.com"
MQTT_PORT = 8083
MQTT_PASSWORD = "helloyou"


def generate_device_info():
    device_id = "".join(random.choice("0123456789ABCDEF") for _ in range(32))
    return {
        "PLATFORM": "app",
        "OS": "android",
        "APPID": "__UNI__55F5E7F",
        "DEVICEID": device_id,
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
        "deviceId": device_id,
        "deviceModel": "SM-A426B",
        "deviceType": "phone",
        "osName": "android",
        "osVersion": 10,
        "romName": "Android",
        "romVersion": 10,
        "ua": (
            "Mozilla/5.0 (Linux; Android 10; SM-A426B) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/87.0.4280.86 Mobile Safari/537.36"
        ),
        "uniPlatform": "app",
        "uniRuntimeVersion": "4.24",
        "locale": "en",
        "LOCALE": "en",
    }


def build_function_params(url, data, token=None):
    args = {"$url": url, "data": data, "clientInfo": generate_device_info()}
    if token:
        args["uniIdToken"] = token
    return json.dumps({"functionTarget": "router", "functionArgs": args})


async def call_api(session, method, params="{}", token=None):
    data = {
        "method": method,
        "params": params,
        "spaceId": "mp-6c382a98-49b8-40ba-b761-645d83e8ee74",
        "timestamp": int(time.time() * 1000),
    }
    if token:
        data["token"] = token

    items = [f"{k}={data[k]}" for k in sorted(data.keys()) if data[k]]
    sig = hmac.new(
        CLIENT_SECRET.encode(), "&".join(items).encode(), hashlib.md5
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "x-serverless-sign": sig,
        "user-agent": generate_device_info()["ua"],
    }

    async with session.post(ENDPOINT, json=data, headers=headers) as resp:
        return await resp.json()


def pretty(label, obj):
    """Print a labelled JSON object with indentation."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(obj, indent=2, default=str))


async def test_mqtt_host(host, port, mqtt_token, device_mac, timeout=10):
    """Test MQTT connectivity to a host using raw WebSocket + MQTT CONNECT."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print(f"    (paho-mqtt not installed, skipping live MQTT test)")
        return None

    connected = asyncio.Event()
    got_data = asyncio.Event()
    result = {"rc": None, "data": False}
    loop = asyncio.get_running_loop()

    def on_connect(client, userdata, flags, rc):
        result["rc"] = rc
        if rc == 0:
            loop.call_soon_threadsafe(connected.set)
            # Subscribe and request data
            client.subscribe(f"{device_mac}/device/response/state", 1)
            client.subscribe(f"{device_mac}/device/response/client/+", 1)
            # Request a data update
            req = [17, 3, 0, 0, 0, 80, 69, 210]
            client.publish(
                f"{device_mac}/client/request/data", bytes(req), qos=1
            )
        else:
            loop.call_soon_threadsafe(connected.set)

    def on_message(client, userdata, msg):
        if len(list(msg.payload)) > 10:
            result["data"] = True
            loop.call_soon_threadsafe(got_data.set)

    hex_str = "".join(random.choice("0123456789abcdef") for _ in range(24))
    client_id = f"test_{hex_str}_{int(time.time()*1000)}"

    # paho-mqtt v2 changed the constructor API
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
            clean_session=True,
            transport="websockets",
            protocol=mqtt.MQTTv311,
        )
    except (AttributeError, TypeError):
        # paho-mqtt v1 fallback
        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            transport="websockets",
            protocol=mqtt.MQTTv311,
        )
    client.ws_set_options(
        path="/mqtt", headers={"Sec-WebSocket-Protocol": "mqtt"}
    )
    client.username_pw_set(username=mqtt_token, password=MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(host, port, keepalive=15)
        client.loop_start()

        try:
            await asyncio.wait_for(connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return {"connected": False, "reason": "connection timeout"}

        if result["rc"] != 0:
            return {"connected": False, "reason": f"rc={result['rc']}"}

        # Wait for data response
        try:
            await asyncio.wait_for(got_data.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

        return {
            "connected": True,
            "got_data": result["data"],
        }
    except Exception as e:
        return {"connected": False, "reason": str(e)}
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


async def main(username, password):
    async with aiohttp.ClientSession() as session:

        # ── Step 1: Anonymous auth ──────────────────────────────
        print("\n[1/5] Getting anonymous auth token...")
        auth_resp = await call_api(
            session, "serverless.auth.user.anonymousAuthorize"
        )
        pretty("Anonymous auth response -> data", auth_resp.get("data", {}))
        auth_token = auth_resp["data"]["accessToken"]
        print(f"  + auth_token = {auth_token[:20]}...")

        # ── Step 2: Login ───────────────────────────────────────
        print("\n[2/5] Logging in...")
        login_params = build_function_params(
            "user/pub/login",
            {"locale": "en", "username": username, "password": password},
        )
        login_resp = await call_api(
            session, "serverless.function.runtime.invoke",
            params=login_params, token=auth_token,
        )
        login_data = login_resp.get("data", {})
        pretty("Login response -> data", login_data)
        access_token = login_data.get("token")
        if not access_token:
            print("  x Login failed! Check credentials.")
            return
        print(f"  + access_token = {access_token[:20]}...")

        # ── Step 3: Get MQTT token ──────────────────────────────
        print("\n[3/5] Getting MQTT token (emqx.getAccessToken)...")
        mqtt_params = build_function_params(
            "common/emqx.getAccessToken",
            {"locale": "en"},
            token=access_token,
        )
        mqtt_resp = await call_api(
            session, "serverless.function.runtime.invoke",
            params=mqtt_params, token=auth_token,
        )
        mqtt_data = mqtt_resp.get("data", {})
        pretty("MQTT token response -> data  *** KEY RESPONSE ***", mqtt_data)

        mqtt_token = mqtt_data.get("access_token", "")
        api_host = mqtt_data.get("mqtt_host", "")

        # ── Step 4: Get devices ─────────────────────────────────
        print("\n[4/5] Getting device list...")
        devices_params = build_function_params(
            "client/device/kh/getList",
            {"locale": "en", "pageIndex": 1, "pageSize": 100},
            token=access_token,
        )
        devices_resp = await call_api(
            session, "serverless.function.runtime.invoke",
            params=devices_params, token=auth_token,
        )
        devices_data = devices_resp.get("data", {})
        pretty("Device list response -> data", devices_data)

        # Extract first device MAC for MQTT test
        device_mac = ""
        rows = devices_data.get("rows", [])
        if rows:
            device_mac = rows[0].get("device_id", "").replace(":", "")
            product_info = rows[0].get("productInfo", {})
            print(f"\n  Device MAC: {device_mac}")
            print(f"  modbus_address: {product_info.get('modbus_address')}")
            print(f"  modbus_count: {product_info.get('modbus_count')}")

        # ── Step 5: Test MQTT connectivity ──────────────────────
        print(f"\n[5/5] Testing MQTT connectivity...")

        hosts_to_test = []
        if api_host:
            hosts_to_test.append(("API", api_host))
        if not api_host or api_host != FALLBACK_HOST:
            hosts_to_test.append(("fallback", FALLBACK_HOST))

        for source, host in hosts_to_test:
            print(f"\n  Testing {source} host: {host}:{MQTT_PORT} ...")
            if not mqtt_token:
                print("    (no MQTT token, skipping)")
                continue
            if not device_mac:
                print("    (no device MAC, skipping)")
                continue

            result = await test_mqtt_host(
                host, MQTT_PORT, mqtt_token, device_mac
            )
            if result is None:
                continue
            if result.get("connected"):
                data_status = "GOT DATA" if result.get("got_data") else "no data (timeout)"
                print(f"    + CONNECTED - {data_status}")
            else:
                print(f"    x FAILED - {result.get('reason', 'unknown')}")

        # ── Summary ─────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}")
        print(f"API-provided MQTT host: {api_host or '(none)'}")
        print(f"Hardcoded fallback:     {FALLBACK_HOST}")
        print(f"MQTT data keys: {list(mqtt_data.keys())}")
        if rows:
            print(f"First device keys: {list(rows[0].keys())}")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: py {sys.argv[0]} <username> <password>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1], sys.argv[2]))
