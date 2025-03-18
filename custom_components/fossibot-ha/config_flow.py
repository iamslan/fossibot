"""Config flow for Fossibot integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .sydpower.connector import SydpowerConnector 

_LOGGER = logging.getLogger(__name__)

class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fossibot."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate the credentials
                connector = SydpowerConnector(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD]
                )
            
                success = await connector.connect()
                if not success:
                    raise Exception("Failed to connect to Fossibot API")
                
                await connector.disconnect()

                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=user_input,
                )
            except Exception as error:
                _LOGGER.error("Failed to connect: %s", error)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )