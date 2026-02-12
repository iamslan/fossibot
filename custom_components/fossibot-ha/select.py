"""Support for Fossibot select entities."""

import logging
from collections import OrderedDict

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity
from .sydpower.const import (
    REGISTER_USB_STANDBY_TIME,
    REGISTER_AC_STANDBY_TIME,
    REGISTER_DC_STANDBY_TIME,
    REGISTER_SCREEN_REST_TIME,
    REGISTER_SLEEP_TIME,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LED mode (command-based: uses pre-defined COMMANDS in connector)
# ---------------------------------------------------------------------------

LED_MODES = {
    "Off": "REGDisableLED",
    "On": "REGEnableLEDAlways",
    "SOS": "REGEnableLEDSOS",
    "Flash": "REGEnableLEDFlash",
}

# ---------------------------------------------------------------------------
# Register-based selects: each maps display labels → raw register values
# Uses OrderedDict so HA UI shows options in a logical order.
# ---------------------------------------------------------------------------

SELECT_DEFINITIONS = [
    {
        "name": "USB Standby Time",
        "key": "usbStandbyTime",
        "register": REGISTER_USB_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("3 min", 3), ("5 min", 5), ("10 min", 10), ("30 min", 30),
        ]),
    },
    {
        "name": "AC Standby Time",
        "key": "acStandbyTime",
        "register": REGISTER_AC_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("8 hours", 480), ("16 hours", 960), ("24 hours", 1440),
        ]),
    },
    {
        "name": "DC Standby Time",
        "key": "dcStandbyTime",
        "register": REGISTER_DC_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("8 hours", 480), ("16 hours", 960), ("24 hours", 1440),
        ]),
    },
    {
        "name": "Screen Rest Time",
        "key": "screenRestTime",
        "register": REGISTER_SCREEN_REST_TIME,
        "options": OrderedDict([
            ("Off", 0), ("3 min", 180), ("5 min", 300), ("10 min", 600), ("30 min", 1800),
        ]),
    },
    {
        "name": "Sleep Time",
        "key": "wholeMachineUnusedTime",
        "register": REGISTER_SLEEP_TIME,
        "options": OrderedDict([
            ("5 min", 5), ("10 min", 10), ("30 min", 30), ("8 hours", 480),
        ]),
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fossibot select entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for device_id in coordinator.data:
        entities.append(FossibotLEDModeSelect(coordinator, device_id))
        for defn in SELECT_DEFINITIONS:
            entities.append(FossibotRegisterSelect(coordinator, device_id, **defn))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# LED mode select (command-based)
# ---------------------------------------------------------------------------

class FossibotLEDModeSelect(FossibotEntity, SelectEntity):
    """Fossibot LED mode selector."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the LED mode selector."""
        super().__init__(coordinator, device_id)
        self._key = "ledOutput"
        self._attr_name = f"Fossibot {device_id} LED Mode"
        self._attr_unique_id = f"{device_id}_led_mode"
        self._attr_options = list(LED_MODES.keys())
        self._last_selected_mode = "Off"

    @property
    def current_option(self):
        """Return the currently selected LED mode."""
        if self._device_id not in self.coordinator.data:
            return None

        led_state = self.coordinator.data[self._device_id].get(self._key, False)

        if not led_state:
            self._last_selected_mode = "Off"
            return "Off"

        # If LED is on but was previously off, assume "On" mode
        if self._last_selected_mode == "Off":
            self._last_selected_mode = "On"

        return self._last_selected_mode

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in LED_MODES:
            _LOGGER.error("Invalid LED mode: %s", option)
            return

        self._last_selected_mode = option

        await self.coordinator.connector.run_command(
            self._device_id, LED_MODES[option]
        )
        await self.coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Register-based select (write_register command)
# ---------------------------------------------------------------------------

class FossibotRegisterSelect(FossibotEntity, SelectEntity):
    """Fossibot select backed by a Modbus register with discrete allowed values."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        register: int,
        options: OrderedDict,
    ) -> None:
        """Initialize the register-based select."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._register = register
        self._options_map = options                        # label → register value
        self._reverse_map = {v: k for k, v in options.items()}  # register value → label
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_options = list(options.keys())

    @property
    def current_option(self):
        """Return the currently selected option."""
        if self._device_id not in self.coordinator.data:
            return None
        raw = self.coordinator.data[self._device_id].get(self._key)
        if raw is None:
            return None
        return self._reverse_map.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._options_map:
            _LOGGER.error("Invalid option for %s: %s", self._key, option)
            return

        reg_value = self._options_map[option]
        await self.coordinator.connector.run_command(
            self._device_id, "write_register", (self._register, reg_value)
        )
        await self.coordinator.async_request_refresh()
