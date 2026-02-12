"""Support for Fossibot sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity

SENSOR_DEFINITIONS = [
    {"name": "State of Charge", "key": "soc", "unit": "%", "device_class": SensorDeviceClass.BATTERY},
    {"name": "State of Charge Slave 1", "key": "soc_s1", "unit": "%", "device_class": SensorDeviceClass.BATTERY},
    {"name": "State of Charge Slave 2", "key": "soc_s2", "unit": "%", "device_class": SensorDeviceClass.BATTERY},
    {"name": "DC Input", "key": "dcInput", "unit": "W", "device_class": SensorDeviceClass.POWER},
    {"name": "Total Input", "key": "totalInput", "unit": "W", "device_class": SensorDeviceClass.POWER},
    {"name": "AC Charging Rate", "key": "acChargingRate", "unit": None, "device_class": None},
    {"name": "Total Output", "key": "totalOutput", "unit": "W", "device_class": SensorDeviceClass.POWER},
    {"name": "AC Output Voltage", "key": "acOutputVoltage", "unit": "V", "device_class": SensorDeviceClass.VOLTAGE},
    {"name": "AC Output Frequency", "key": "acOutputFrequency", "unit": "Hz", "device_class": SensorDeviceClass.FREQUENCY},
    {"name": "AC Input Voltage", "key": "acInputVoltage", "unit": "V", "device_class": SensorDeviceClass.VOLTAGE},
    {"name": "AC Input Frequency", "key": "acInputFrequency", "unit": "Hz", "device_class": SensorDeviceClass.FREQUENCY},
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        FossibotSensor(coordinator, device_id, **defn)
        for device_id in coordinator.data
        for defn in SENSOR_DEFINITIONS
    ]

    async_add_entities(entities)


class FossibotSensor(FossibotEntity, SensorEntity):
    """Representation of a Fossibot sensor."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_unique_id = f"{device_id}_{key}"

        if device_class == SensorDeviceClass.POWER:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)
