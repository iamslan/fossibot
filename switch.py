"""Support for Fossibot switches."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import FossibotDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot switches."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for device_id, device_data in coordinator.data.items():
        entities.extend([
            FossibotSwitch(
                coordinator,
                device_id,
                "USB Output",
                "usbOutput",
                "REGEnableUSBOutput",
                "REGDisableUSBOutput",
            ),
            FossibotSwitch(
                coordinator,
                device_id,
                "DC Output",
                "dcOutput",
                "REGEnableDCOutput",
                "REGDisableDCOutput",
            ),
            FossibotSwitch(
                coordinator,
                device_id,
                "AC Output",
                "acOutput",
                "REGEnableACOutput",
                "REGDisableACOutput",
            ),
            FossibotSwitch(
                coordinator,
                device_id,
                "LED Output",
                "ledOutput",
                "REGEnableLEDAlways",
                "REGDisableLED",
            ),
        ])

    async_add_entities(entities)

class FossibotSwitch(CoordinatorEntity, SwitchEntity):
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
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key
        self._attr_name = name
        self._on_command = on_command
        self._off_command = off_command
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self.coordinator.data[self._device_id].get(self._key)

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.coordinator.connector.run_command(
            self._device_id,
            self._on_command,
            None
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.coordinator.connector.run_command(
            self._device_id,
            self._off_command,
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