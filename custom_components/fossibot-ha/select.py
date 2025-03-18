"""Support for Fossibot select entities."""
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import FossibotDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# LED modes and corresponding commands
LED_MODES = {
    "Off": "REGDisableLED",
    "On": "REGEnableLEDAlways",
    "SOS": "REGEnableLEDSOS",
    "Flash": "REGEnableLEDFlash",
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fossibot select entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up Fossibot SELECT platform with coordinator")
    
    entities = []
    for device_id, device_data in coordinator.data.items():
        _LOGGER.debug(f"Creating LED mode select entity for device {device_id}")
        entities.append(
            FossibotLEDModeSelect(
                coordinator,
                device_id,
            )
        )

    _LOGGER.debug(f"Adding {len(entities)} select entities")
    async_add_entities(entities)
    _LOGGER.debug("SELECT platform setup complete")


class FossibotLEDModeSelect(CoordinatorEntity, SelectEntity):
    """Fossibot LED mode selector."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the LED mode selector."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = "ledOutput"
        self._attr_name = f"Fossibot {device_id} LED Mode"
        self._attr_unique_id = f"{device_id}_led_mode"
        self._attr_options = list(LED_MODES.keys())
        # Store last selected mode
        self._last_selected_mode = "Off"

    @property
    def current_option(self):
        """Return the currently selected LED mode."""
        led_state = self.coordinator.data[self._device_id].get(self._key, False)
        
        # If LED is off, return Off
        if not led_state:
            self._last_selected_mode = "Off"
            return "Off"
        
        # If LED is on but was previously off, assume "On" mode
        if self._last_selected_mode == "Off":
            self._last_selected_mode = "On"
        
        # Return the last selected mode
        return self._last_selected_mode

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in LED_MODES:
            _LOGGER.error(f"Invalid LED mode: {option}")
            return

        command = LED_MODES[option]
        
        _LOGGER.debug(f"Setting LED mode to {option} using command {command}")
        
        # Store the selected mode
        self._last_selected_mode = option
        
        # Send the command
        await self.coordinator.connector.run_command(
            self._device_id,
            command,
            None
        )
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": f"Fossibot {self._device_id}",
            "manufacturer": MANUFACTURER,
        }