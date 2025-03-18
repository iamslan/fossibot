# api_client.py
"""
API client for Fossibot cloud service.
"""

import asyncio
import time
import hmac
import hashlib
import json
import random
import aiohttp
from typing import Dict, Any, Optional

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

    async def _ensure_session(self):
        """Ensure that a persistent aiohttp session exists."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)  # 15 seconds timeout
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._logger.debug("Created new aiohttp session with timeout %s seconds", timeout.total)

    async def call_api(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Make an API call to Fossibot with retries and smart logging."""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                await self._ensure_session()
                
                self._logger.debug("API call attempt %d/%d for route: %s",
                                  attempt + 1, max_retries, config.get('route', 'unknown'))
                
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

                try:
                    # Use a timeout for the request
                    async with self._session.post(ENDPOINT, json=data, headers=headers, timeout=10) as resp:
                        if resp.status != 200:
                            self._logger.error(f"API request failed with status {resp.status}")
                            error_text = await resp.text()
                            self._logger.error(f"Error response: {error_text[:200]}")
                            raise Exception(f"API request failed with status {resp.status}")
                            
                        resp_json = await resp.json()
                        
                        if not resp_json.get('data'):
                            self._logger.error(f"API request failed: {resp_json}")
                            raise Exception(f"API request failed: {resp_json}")
                            
                        if (route == "api-login" and not resp_json.get('data', {}).get('token')):
                            self._logger.error(f"Login failed - no token in response")
                            raise Exception(f"Login failed - no token in response")
                            
                        return resp_json
                except asyncio.TimeoutError:
                    self._logger.error(f"API request timed out for route {route}")
                    raise

            except asyncio.CancelledError:
                self._logger.warning("API call cancelled")
                raise
            except Exception as e:
                self._logger.error("API call failed (attempt %d/%d): %s",
                                   attempt + 1, max_retries, str(e))
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (attempt + 1))
    
    async def authenticate(self, username: str, password: str) -> Dict[str, str]:
        """Get anonymous auth token, then login to get access token."""
        # Step 1: Get anonymous auth token
        self._logger.debug("Requesting anonymous auth token")
        auth_resp = await self.call_api({"route": "api-auth"})
        self._auth_token = auth_resp.get("data", {}).get("accessToken")
        
        if not self._auth_token:
            raise ValueError("Failed to get anonymous auth token")
            
        self._logger.debug("Fetched anonymous authorized token")

        # Step 2: Login and get access token
        self._logger.debug("Attempting login with username and password")
        login_resp = await self.call_api({
            "route": "api-login",
            "authorizeToken": self._auth_token,
            "username": username,
            "password": password
        })
        self._access_token = login_resp.get("data", {}).get("token")
        
        if not self._access_token:
            raise ValueError("Failed to get access token from login response")
            
        self._logger.debug("Fetched logged-in access token")

        return {
            "auth_token": self._auth_token,
            "access_token": self._access_token
        }
    
    async def get_mqtt_token(self) -> str:
        """Get MQTT access token."""
        if not self._auth_token or not self._access_token:
            raise ValueError("Must authenticate first")
            
        self._logger.debug("Requesting MQTT token")
        mqtt_resp = await self.call_api({
            "route": "api-mqtt",
            "authorizeToken": self._auth_token,
            "accessToken": self._access_token
        })
        mqtt_token = mqtt_resp.get("data", {}).get("access_token")
        
        if not mqtt_token:
            raise ValueError("Failed to get MQTT token from response")
            
        self._logger.debug("Fetched MQTT access token")
        return mqtt_token
    
    async def get_devices(self) -> Dict[str, Any]:
        """Get list of devices."""
        if not self._auth_token or not self._access_token:
            raise ValueError("Must authenticate first")
            
        self._logger.debug("Requesting device list")
        devices_resp = await self.call_api({
            "route": "api-devices",
            "authorizeToken": self._auth_token,
            "accessToken": self._access_token
        })
        devices = devices_resp.get("data", {}).get("rows", [])
        
        device_dict = {}
        for device in devices:
            dev_id = device.get("device_id", "").replace(":", "")
            device_dict[dev_id] = device
            
        self._logger.debug(f"Found {len(device_dict)} devices")
        return device_dict
    
    async def close(self):
        """Close the session."""
        if self._session:
            try:
                await self._session.close()
                self._logger.debug("API session closed")
            except Exception as e:
                self._logger.error(f"Error closing API session: {e}")
            finally:
                self._session = None