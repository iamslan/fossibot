"""Base entity for Fossibot integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER


class FossibotEntity(CoordinatorEntity):
    """Base class for all Fossibot entities.

    Provides shared device_info and availability logic so that
    platform-specific entities (sensor, switch, select) don't
    duplicate this code.
    """

    def __init__(self, coordinator, device_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def available(self) -> bool:
        """Return True if the device is present in coordinator data."""
        return super().available and self._device_id in self.coordinator.data

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": f"Fossibot {self._device_id}",
            "manufacturer": MANUFACTURER,
        }
