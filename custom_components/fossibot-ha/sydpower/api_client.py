"""API client for SYDPOWER local MQTT integration.

Uses the two public APIs:
- pub_getDeviceList: retrieve bound devices
- pub_updateMqttState: sync device online/offline state with the platform
"""

import asyncio
from typing import Any, Dict, Optional

import aiohttp

from .const import API_GET_DEVICE_LIST, API_UPDATE_MQTT_STATE
from .logger import SmartLogger


class APIClient:
    """Client for SYDPOWER public device APIs."""

    def __init__(self, api_token: str):
        self._api_token = api_token
        self._session: Optional[aiohttp.ClientSession] = None
        self._logger = SmartLogger(__name__)

    async def _ensure_session(self):
        """Ensure that a persistent aiohttp session exists."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def _request(
        self, url: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make an API request with retries."""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                await self._ensure_session()

                async with self._session.post(
                    url, json=params, timeout=10
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        self._logger.error(
                            "API request to %s failed with status %d: %s",
                            url, resp.status, error_text[:200],
                        )
                        raise Exception(
                            f"API request failed with status {resp.status}"
                        )

                    resp_json = await resp.json()
                    return resp_json

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._logger.error(
                    "API call to %s failed (attempt %d/%d): %s",
                    url, attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (attempt + 1))

    async def get_devices(self) -> Dict[str, Any]:
        """Get list of devices using pub_getDeviceList API.

        Returns a dict keyed by MAC (colons stripped), values are device records.
        """
        resp = await self._request(
            API_GET_DEVICE_LIST,
            {"api_token": self._api_token},
        )

        # The API may return a list directly or wrap it in a data/rows key
        devices_list = resp
        if isinstance(resp, dict):
            devices_list = (
                resp.get("data", {}).get("rows")
                or resp.get("data", [])
                or resp.get("rows", [])
            )
            if isinstance(devices_list, dict):
                devices_list = devices_list.get("rows", [])

        if not isinstance(devices_list, list):
            self._logger.error(
                "Unexpected device list response format: %s",
                type(devices_list),
            )
            self._logger.debug("Full response: %s", resp)
            return {}

        self._logger.debug("Device list returned %d entries", len(devices_list))

        device_dict = {}
        for device in devices_list:
            raw_id = device.get("device_id") or ""
            dev_id = raw_id.replace(":", "")
            name = device.get("device_name", "<unknown>")

            if not dev_id:
                self._logger.warning(
                    "Device '%s' has no device_id — skipping. "
                    "Re-register the device in the BrightEMS app to fix this.",
                    name,
                )
                continue

            self._logger.debug(
                "Device '%s': raw_id=%s mac=%s",
                name, raw_id, dev_id,
            )

            # Extract modbus info from productInfo
            product_info = device.get("productInfo", {})
            if product_info.get("modbus_address") is not None:
                device["_modbus_address"] = int(product_info["modbus_address"])
            if product_info.get("modbus_count") is not None:
                device["_modbus_count"] = int(product_info["modbus_count"])

            # Store raw device_id (with colons) for state sync API
            device["_raw_device_id"] = raw_id

            device_dict[dev_id] = device

        self._logger.info("Found %d devices", len(device_dict))
        return device_dict

    async def update_mqtt_state(
        self, device_id: str, online: bool
    ) -> bool:
        """Sync device online/offline state with the platform.

        Args:
            device_id: Device MAC address WITH colons (e.g. "AB:CD:EF:GH:IJ:KL")
            online: True if device is online, False if offline
        """
        try:
            resp = await self._request(
                API_UPDATE_MQTT_STATE,
                {
                    "api_token": self._api_token,
                    "device_id": device_id,
                    "mqtt_state": 1 if online else 0,
                },
            )
            self._logger.debug(
                "Updated MQTT state for %s: %s — response: %s",
                device_id,
                "online" if online else "offline",
                resp,
            )
            return True
        except Exception as e:
            self._logger.error(
                "Failed to update MQTT state for %s: %s", device_id, e
            )
            return False

    async def close(self):
        """Close the session."""
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                self._logger.error("Error closing API session: %s", e)
            finally:
                self._session = None
