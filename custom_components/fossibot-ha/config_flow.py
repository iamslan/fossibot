"""Config flow for Fossibot integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_API_TOKEN,
    DEFAULT_MQTT_PORT,
)
from .sydpower.api_client import APIClient

_LOGGER = logging.getLogger(__name__)


class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fossibot."""

    VERSION = 2

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step — MQTT broker + API token."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): str,
                    vol.Required(CONF_MQTT_HOST): str,
                    vol.Optional(
                        CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT
                    ): int,
                    vol.Optional(CONF_MQTT_USERNAME, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_validate(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Validate the API token by fetching device list."""
        api_client = None
        try:
            api_client = APIClient(self._data[CONF_API_TOKEN])
            devices = await api_client.get_devices()

            if not devices:
                raise Exception("No devices found for this API token")

            _LOGGER.info(
                "Validation successful: found %d devices", len(devices)
            )

            # Use the first device name or API token prefix as title
            title = f"Fossibot ({len(devices)} device{'s' if len(devices) > 1 else ''})"

            return self.async_create_entry(
                title=title,
                data=self._data,
            )
        except Exception as error:
            _LOGGER.error("Failed to validate: %s", error)
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_API_TOKEN,
                            default=self._data.get(CONF_API_TOKEN, ""),
                        ): str,
                        vol.Required(
                            CONF_MQTT_HOST,
                            default=self._data.get(CONF_MQTT_HOST, ""),
                        ): str,
                        vol.Optional(
                            CONF_MQTT_PORT,
                            default=self._data.get(
                                CONF_MQTT_PORT, DEFAULT_MQTT_PORT
                            ),
                        ): int,
                        vol.Optional(
                            CONF_MQTT_USERNAME,
                            default=self._data.get(CONF_MQTT_USERNAME, ""),
                        ): str,
                    }
                ),
                errors={"base": "cannot_connect"},
            )
        finally:
            if api_client:
                await api_client.close()

    async def async_step_reauth(
        self, entry_data: Dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle reauth input."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)

            api_client = None
            try:
                api_client = APIClient(self._data[CONF_API_TOKEN])
                devices = await api_client.get_devices()
                if not devices:
                    raise Exception("No devices found")

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
            finally:
                if api_client:
                    await api_client.close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_TOKEN,
                        default=self._data.get(CONF_API_TOKEN, ""),
                    ): str,
                    vol.Required(
                        CONF_MQTT_HOST,
                        default=self._data.get(CONF_MQTT_HOST, ""),
                    ): str,
                    vol.Optional(
                        CONF_MQTT_PORT,
                        default=self._data.get(
                            CONF_MQTT_PORT, DEFAULT_MQTT_PORT
                        ),
                    ): int,
                    vol.Optional(
                        CONF_MQTT_USERNAME,
                        default=self._data.get(CONF_MQTT_USERNAME, ""),
                    ): str,
                }
            ),
            errors=errors,
        )
