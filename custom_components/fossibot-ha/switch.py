"""Support for Fossibot switches."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity

SWITCH_DEFINITIONS = [
    {"name": "USB Output", "key": "usbOutput", "on_command": "REGEnableUSBOutput", "off_command": "REGDisableUSBOutput"},
    {"name": "DC Output", "key": "dcOutput", "on_command": "REGEnableDCOutput", "off_command": "REGDisableDCOutput"},
    {"name": "AC Output", "key": "acOutput", "on_command": "REGEnableACOutput", "off_command": "REGDisableACOutput"},
    {"name": "AC Silent Charging", "key": "acSilentCharging", "on_command": "REGEnableACSilentChg", "off_command": "REGDisableACSilentChg"},
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot switches."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        FossibotSwitch(coordinator, device_id, **defn)
        for device_id in coordinator.data
        for defn in SWITCH_DEFINITIONS
    ]

    async_add_entities(entities)


class FossibotSwitch(FossibotEntity, SwitchEntity):
    """Representation of a Fossibot switch."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        on_command: str,
        off_command: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._attr_name = f"Fossibot {device_id} {name}"
        self._on_command = on_command
        self._off_command = off_command
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def is_on(self):
        """Return true if switch is on."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.coordinator.connector.run_command(
            self._device_id, self._on_command
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.coordinator.connector.run_command(
            self._device_id, self._off_command
        )
        await self.coordinator.async_request_refresh()
