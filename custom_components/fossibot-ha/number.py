"""Support for Fossibot number entities."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity
from .sydpower.const import (
    REGISTER_MAXIMUM_CHARGING_CURRENT,
    REGISTER_STOP_CHARGE_AFTER,
    REGISTER_DISCHARGE_LIMIT,
    REGISTER_CHARGING_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

NUMBER_DEFINITIONS = [
    {
        "name": "Maximum Charging Current",
        "key": "maximumChargingCurrent",
        "register": REGISTER_MAXIMUM_CHARGING_CURRENT,
        "min_value": 1,
        "max_value": 20,
        "step": 1,
        "unit": "A",
        "mode": NumberMode.SLIDER,
        "multiplier": 1,
    },
    {
        "name": "Stop Charge After",
        "key": "stopChargeAfter",
        "register": REGISTER_STOP_CHARGE_AFTER,
        "min_value": 0,
        "max_value": 1440,
        "step": 1,
        "unit": "min",
        "mode": NumberMode.BOX,
        "multiplier": 1,
    },
    {
        "name": "Discharge Lower Limit",
        "key": "dischargeLowerLimit",
        "register": REGISTER_DISCHARGE_LIMIT,
        "min_value": 0,
        "max_value": 100,
        "step": 1,
        "unit": "%",
        "mode": NumberMode.SLIDER,
        "multiplier": 10,  # UI shows %, register stores permille
    },
    {
        "name": "AC Charging Upper Limit",
        "key": "acChargingUpperLimit",
        "register": REGISTER_CHARGING_LIMIT,
        "min_value": 0,
        "max_value": 100,
        "step": 1,
        "unit": "%",
        "mode": NumberMode.SLIDER,
        "multiplier": 10,  # UI shows %, register stores permille
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fossibot number entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        FossibotNumber(coordinator, device_id, **defn)
        for device_id in coordinator.data
        for defn in NUMBER_DEFINITIONS
    ]

    async_add_entities(entities)


class FossibotNumber(FossibotEntity, NumberEntity):
    """Representation of a Fossibot number entity."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        register: int,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
        mode: NumberMode,
        multiplier: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._register = register
        self._multiplier = multiplier
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = mode

    @property
    def native_value(self):
        """Return the current value."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        reg_value = int(value * self._multiplier)
        await self.coordinator.connector.run_command(
            self._device_id, "write_register", (self._register, reg_value)
        )
        await self.coordinator.async_request_refresh()
