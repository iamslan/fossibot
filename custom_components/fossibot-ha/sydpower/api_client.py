"""API client for Fossibot cloud service."""

import asyncio
import time
import hmac
import hashlib
import json
import random
from typing import Any, Dict, Optional

import aiohttp

from .const import ENDPOINT, CLIENT_SECRET
from .logger import SmartLogger


class APIClient:
    """Client for Fossibot/Sydpower API."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._logger = SmartLogger(__name__)
        self._auth_token = None
        self._access_token = None

    def _generate_device_info(self) -> Dict[str, Any]:
        """Generate realistic Android device info for API calls."""
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
            "ua": "Mozilla/5.0 (Linux; Android 10; SM-A426B) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/87.0.4280.86 Mobile Safari/537.36",
            "uniPlatform": "app",
            "uniRuntimeVersion": "4.24",
            "locale": "en",
            "LOCALE": "en",
        }

    async def _ensure_session(self):
        """Ensure that a persistent aiohttp session exists."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)

    def _build_function_params(
        self, url: str, data: Dict, token: Optional[str] = None
    ) -> str:
        """Build JSON params for a serverless function invocation."""
        args: Dict[str, Any] = {
            "$url": url,
            "data": data,
            "clientInfo": self._generate_device_info(),
        }
        if token:
            args["uniIdToken"] = token
        return json.dumps({"functionTarget": "router", "functionArgs": args})

    async def _call_api(
        self,
        method: str,
        params: str = "{}",
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an API call to Fossibot with retries."""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                await self._ensure_session()

                data = {
                    "method": method,
                    "params": params,
                    "spaceId": "mp-6c382a98-49b8-40ba-b761-645d83e8ee74",
                    "timestamp": int(time.time() * 1000),
                }
                if token:
                    data["token"] = token

                # Generate HMAC-MD5 signature
                items = [
                    f"{key}={data[key]}"
                    for key in sorted(data.keys())
                    if data[key]
                ]
                query_str = "&".join(items)
                signature = hmac.new(
                    CLIENT_SECRET.encode("utf-8"),
                    query_str.encode("utf-8"),
                    hashlib.md5,
                ).hexdigest()

                device_info = self._generate_device_info()
                headers = {
                    "Content-Type": "application/json",
                    "x-serverless-sign": signature,
                    "user-agent": device_info["ua"],
                }

                async with self._session.post(
                    ENDPOINT, json=data, headers=headers, timeout=10
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        self._logger.error(
                            "API request failed with status %d: %s",
                            resp.status, error_text[:200],
                        )
                        raise Exception(
                            f"API request failed with status {resp.status}"
                        )

                    resp_json = await resp.json()

                    if not resp_json.get("data"):
                        raise Exception(
                            f"API request returned no data: {resp_json}"
                        )

                    return resp_json

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._logger.error(
                    "API call failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (attempt + 1))

    async def authenticate(self, username: str, password: str) -> Dict[str, str]:
        """Authenticate and obtain access tokens."""
        # Step 1: Get anonymous auth token
        auth_resp = await self._call_api(
            "serverless.auth.user.anonymousAuthorize"
        )
        self._auth_token = auth_resp["data"]["accessToken"]

        # Step 2: Login with credentials
        login_params = self._build_function_params(
            "user/pub/login",
            {"locale": "en", "username": username, "password": password},
        )
        login_resp = await self._call_api(
            "serverless.function.runtime.invoke",
            params=login_params,
            token=self._auth_token,
        )
        login_data = login_resp.get("data", {})
        self._logger.debug("Login response keys: %s", list(login_data.keys()))
        self._access_token = login_data.get("token")

        if not self._access_token:
            raise ValueError("Login failed - no token in response")

        return {
            "auth_token": self._auth_token,
            "access_token": self._access_token,
        }

    async def get_mqtt_token(self) -> Dict[str, Any]:
        """Get MQTT access token and connection info.

        Returns a dict with at least ``token``.  May also contain
        ``mqtt_host`` and ``mqtt_port`` if the API provides them.
        """
        if not self._auth_token or not self._access_token:
            raise ValueError("Must authenticate first")

        params = self._build_function_params(
            "common/emqx.getAccessToken",
            {"locale": "en"},
            token=self._access_token,
        )
        resp = await self._call_api(
            "serverless.function.runtime.invoke",
            params=params,
            token=self._auth_token,
        )
        data = resp.get("data", {})

        self._logger.info(
            "MQTT token response keys: %s", list(data.keys())
        )
        self._logger.debug("MQTT token response data: %s", data)

        mqtt_token = data.get("access_token")
        if not mqtt_token:
            raise ValueError("Failed to get MQTT token")

        # Try to extract MQTT host from response — field name unknown,
        # so check common patterns used by EMQX cloud APIs.
        mqtt_host = (
            data.get("mqtt_host")
            or data.get("host")
            or data.get("mqttHost")
            or data.get("server")
            or data.get("endpoint")
            or data.get("broker")
            or data.get("url")
            or data.get("addr")
        )

        mqtt_port = (
            data.get("mqtt_port")
            or data.get("port")
            or data.get("mqttPort")
        )

        result: Dict[str, Any] = {"token": mqtt_token}
        if mqtt_host:
            self._logger.info("API returned MQTT host: %s", mqtt_host)
            result["mqtt_host"] = mqtt_host
        if mqtt_port:
            self._logger.info("API returned MQTT port: %s", mqtt_port)
            result["mqtt_port"] = int(mqtt_port)

        return result

    async def get_devices(self) -> Dict[str, Any]:
        """Get list of devices."""
        if not self._auth_token or not self._access_token:
            raise ValueError("Must authenticate first")

        params = self._build_function_params(
            "client/device/kh/getList",
            {"locale": "en", "pageIndex": 1, "pageSize": 100},
            token=self._access_token,
        )
        resp = await self._call_api(
            "serverless.function.runtime.invoke",
            params=params,
            token=self._auth_token,
        )
        resp_data = resp.get("data", {})
        self._logger.debug("Device list response keys: %s", list(resp_data.keys()))
        devices = resp_data.get("rows", [])

        if devices:
            self._logger.debug(
                "First device keys: %s", list(devices[0].keys())
            )

        device_dict = {}
        for device in devices:
            raw_id = device.get("device_id") or ""
            dev_id = raw_id.replace(":", "")
            if not dev_id:
                self._logger.warning(
                    "Device '%s' has no device_id in API response — skipping. "
                    "Re-register the device in the Fossibot/BrightEMS app to fix this.",
                    device.get("device_name", "<unknown>"),
                )
                continue
            # Extract modbus info from productInfo for per-device addressing
            product_info = device.get("productInfo", {})
            if product_info.get("modbus_address") is not None:
                device["_modbus_address"] = int(product_info["modbus_address"])
            if product_info.get("modbus_count") is not None:
                device["_modbus_count"] = int(product_info["modbus_count"])
            device_dict[dev_id] = device

        self._logger.debug("Found %d devices", len(device_dict))
        return device_dict

    async def close(self):
        """Close the session."""
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                self._logger.error("Error closing API session: %s", e)
            finally:
                self._session = None
