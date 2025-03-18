"""Config flow for Fossibot integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import DOMAIN, CONF_DEVELOPER_MODE
from .sydpower.connector import SydpowerConnector 

_LOGGER = logging.getLogger(__name__)

class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fossibot."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}
        self._show_advanced_options = False
        
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Store the data
            self._data.update(user_input)
            
            # Check if the user wants to see advanced options
            if user_input.get("show_advanced", False):
                return await self.async_step_advanced()
                
            # Otherwise move to validation
            return await self.async_step_validate()

        # First step - username/password and advanced toggle
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
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Store the data
            self._data.update(user_input)
            # Move to validation
            return await self.async_step_validate()

        # Show advanced options form
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEVELOPER_MODE, default=False): bool,
                }
            ),
            errors=errors,
        )
        
    async def async_step_validate(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Validate the credentials."""
        try:
            # Create connector with or without developer mode
            connector = SydpowerConnector(
                self._data[CONF_USERNAME],
                self._data[CONF_PASSWORD],
                developer_mode=self._data.get(CONF_DEVELOPER_MODE, False)
            )
        
            success = await connector.connect()
            if not success:
                raise Exception("Failed to connect to Fossibot API")
            
            await connector.disconnect()

            # Remove temporary keys
            if "show_advanced" in self._data:
                self._data.pop("show_advanced")
                
            # Create the config entry
            return self.async_create_entry(
                title=self._data[CONF_USERNAME],
                data=self._data,
            )
        except Exception as error:
            _LOGGER.error("Failed to connect: %s", error)
            # Return to the user step with error
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_USERNAME, default=self._data.get(CONF_USERNAME, "")): str,
                        vol.Required(CONF_PASSWORD, default=self._data.get(CONF_PASSWORD, "")): str,
                        vol.Optional("show_advanced", default=False): bool,
                    }
                ),
                errors={"base": "cannot_connect"},
            )