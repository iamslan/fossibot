"""Config flow for Fossibot integration."""

import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_DEVELOPER_MODE,
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LOCAL,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_DEVICE_MAC,
)
from .sydpower.connector import SydpowerConnector
from .sydpower.const import MQTT_PORT

_LOGGER = logging.getLogger(__name__)

MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")


def _normalize_mac(raw: str) -> str:
    """Strip colons/dashes and uppercase a MAC address."""
    return raw.replace(":", "").replace("-", "").upper().strip()


class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fossibot."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step — choose connection mode."""
        if user_input is not None:
            mode = user_input.get(CONF_CONNECTION_MODE, CONNECTION_MODE_CLOUD)
            self._data[CONF_CONNECTION_MODE] = mode

            if mode == CONNECTION_MODE_LOCAL:
                return await self.async_step_local_mqtt()

            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_MODE, default=CONNECTION_MODE_CLOUD
                    ): vol.In(
                        {
                            CONNECTION_MODE_CLOUD: "Cloud API (username/password)",
                            CONNECTION_MODE_LOCAL: "Local MQTT (no cloud needed)",
                        }
                    ),
                }
            ),
        )

    # ── Cloud flow ───────────────────────────────────────────────────

    async def async_step_cloud(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle cloud credential input."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)

            if user_input.get("show_advanced", False):
                return await self.async_step_advanced()

            return await self.async_step_validate()

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional("show_advanced", default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_advanced(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the advanced options step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEVELOPER_MODE, default=False): bool,
                }
            ),
        )

    async def async_step_validate(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Validate the cloud credentials."""
        try:
            connector = SydpowerConnector(
                self._data[CONF_USERNAME],
                self._data[CONF_PASSWORD],
                developer_mode=self._data.get(CONF_DEVELOPER_MODE, False),
            )

            success = await connector.connect()
            if not success:
                raise Exception("Failed to connect to Fossibot API")

            await connector.disconnect()

            self._data.pop("show_advanced", None)

            return self.async_create_entry(
                title=self._data[CONF_USERNAME],
                data=self._data,
            )
        except Exception as error:
            _LOGGER.error("Failed to connect: %s", error)
            return self.async_show_form(
                step_id="cloud",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_USERNAME,
                            default=self._data.get(CONF_USERNAME, ""),
                        ): str,
                        vol.Required(
                            CONF_PASSWORD,
                            default=self._data.get(CONF_PASSWORD, ""),
                        ): str,
                        vol.Optional("show_advanced", default=False): bool,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

    # ── Local MQTT flow ──────────────────────────────────────────────

    async def async_step_local_mqtt(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle local MQTT configuration."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            mqtt_host = user_input.get(CONF_MQTT_HOST, "").strip()
            mqtt_port = user_input.get(CONF_MQTT_PORT, MQTT_PORT)
            raw_mac = user_input.get(CONF_DEVICE_MAC, "")
            device_mac = _normalize_mac(raw_mac)

            if not mqtt_host:
                errors[CONF_MQTT_HOST] = "invalid_host"
            elif not MAC_PATTERN.match(device_mac):
                errors[CONF_DEVICE_MAC] = "invalid_mac"
            else:
                self._data.update(
                    {
                        CONF_MQTT_HOST: mqtt_host,
                        CONF_MQTT_PORT: mqtt_port,
                        CONF_DEVICE_MAC: device_mac,
                    }
                )
                return await self.async_step_validate_local()

        return self.async_show_form(
            step_id="local_mqtt",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_HOST,
                        default=self._data.get(CONF_MQTT_HOST, ""),
                    ): str,
                    vol.Required(
                        CONF_MQTT_PORT,
                        default=self._data.get(CONF_MQTT_PORT, MQTT_PORT),
                    ): int,
                    vol.Required(
                        CONF_DEVICE_MAC,
                        default=self._data.get(CONF_DEVICE_MAC, ""),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_validate_local(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Validate the local MQTT connection."""
        try:
            connector = SydpowerConnector(
                username=None,
                password=None,
                connection_mode=CONNECTION_MODE_LOCAL,
                mqtt_host=self._data[CONF_MQTT_HOST],
                mqtt_port=self._data[CONF_MQTT_PORT],
                device_mac=self._data[CONF_DEVICE_MAC],
            )

            success = await connector.connect()
            if not success:
                raise Exception("Failed to connect to local MQTT broker")

            await connector.disconnect()

            return self.async_create_entry(
                title=f"Local MQTT ({self._data[CONF_DEVICE_MAC]})",
                data=self._data,
            )
        except Exception as error:
            _LOGGER.error("Failed to connect to local MQTT: %s", error)
            return self.async_show_form(
                step_id="local_mqtt",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_MQTT_HOST,
                            default=self._data.get(CONF_MQTT_HOST, ""),
                        ): str,
                        vol.Required(
                            CONF_MQTT_PORT,
                            default=self._data.get(CONF_MQTT_PORT, MQTT_PORT),
                        ): int,
                        vol.Required(
                            CONF_DEVICE_MAC,
                            default=self._data.get(CONF_DEVICE_MAC, ""),
                        ): str,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

    # ── Reauth (cloud only) ─────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: Dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle reauth credential input."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data[CONF_USERNAME] = user_input[CONF_USERNAME]
            self._data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

            try:
                connector = SydpowerConnector(
                    self._data[CONF_USERNAME],
                    self._data[CONF_PASSWORD],
                    developer_mode=self._data.get(CONF_DEVELOPER_MODE, False),
                )
                success = await connector.connect()
                if not success:
                    raise Exception("Failed to connect")
                await connector.disconnect()

                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                self.hass.config_entries.async_update_entry(
                    entry, data=self._data
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self._data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
