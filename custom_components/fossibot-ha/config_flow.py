"""Config flow for Fossibot integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_DEVELOPER_MODE
from .sydpower.connector import SydpowerConnector

_LOGGER = logging.getLogger(__name__)


class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fossibot."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)

            if user_input.get("show_advanced", False):
                return await self.async_step_advanced()

            return await self.async_step_validate()

        return self.async_show_form(
            step_id="user",
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
        """Validate the credentials."""
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
                step_id="user",
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
