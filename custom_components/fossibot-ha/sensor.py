"""Support for Fossibot sensors."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    """Set up the Fossibot sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for device_id, device_data in coordinator.data.items():
        entities.extend([
            FossibotSensor(
                coordinator,
                device_id,
                "State of Charge",
                "soc",
                "%",
                SensorDeviceClass.BATTERY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "State of Charge Slave 1",
                "soc_s1",
                "%",
                SensorDeviceClass.BATTERY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "State of Charge Slave 2",
                "soc_s2",
                "%",
                SensorDeviceClass.BATTERY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "DC Input",
                "dcInput",
                "W",
                SensorDeviceClass.POWER,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Total Input",
                "totalInput",
                "W",
                SensorDeviceClass.POWER,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Charging Rate",
                "acChargingRate",
                None,
                None,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Total Output",
                "totalOutput",
                "W",
                SensorDeviceClass.POWER,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Output Voltage",
                "acOutputVoltage",
                "V",
                SensorDeviceClass.VOLTAGE,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Output Frequency",
                "acOutputFrequency",
                "Hz",
                SensorDeviceClass.FREQUENCY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Input Voltage",
                "acInputVoltage",
                "V",
                SensorDeviceClass.VOLTAGE,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Input Frequency",
                "acInputFrequency",
                "Hz",
                SensorDeviceClass.FREQUENCY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Maximum Charging Current",
                "maximumChargingCurrent",
                "A",
                SensorDeviceClass.CURRENT,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "USB Standby Time",
                "usbStandbyTime",
                "min",
                SensorDeviceClass.DURATION,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC Standby Time",
                "acStandbyTime",
                "min",
                SensorDeviceClass.DURATION,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "DC Standby Time",
                "dcStandbyTime",
                "min",
                SensorDeviceClass.DURATION,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Screen Rest Time",
                "screenRestTime",
                "s",
                SensorDeviceClass.DURATION,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Stop charge after",
                "stopChargeAfter",
                "min",
                SensorDeviceClass.DURATION,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Discharge Lower Limit",
                "dischargeLowerLimit",
                "%",
                SensorDeviceClass.BATTERY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "AC charging upper limit in EPS mode",
                "acChargingUpperLimit",
                "%",
                SensorDeviceClass.BATTERY,
            ),
            FossibotSensor(
                coordinator,
                device_id,
                "Whole machine unused time",
                "wholeMachineUnusedTime",
                "min",
                SensorDeviceClass.DURATION,
            ),
        ])

    async_add_entities(entities)

class FossibotSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Fossibot sensor."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        unit: str,
        device_class: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key
        
        # Set proper name that includes device ID
        # This will generate an entity_id like: sensor.fossibot_abc123_state_of_charge
        self._attr_name = f"Fossibot {device_id} {name}"
        
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        
        # Unique ID should be stable and unchanging
        self._attr_unique_id = f"{device_id}_{key}"
        
        if device_class == SensorDeviceClass.POWER:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data[self._device_id].get(self._key)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": f"Fossibot {self._device_id}",
            "manufacturer": MANUFACTURER,
        }