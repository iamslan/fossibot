"""The Fossibot integration."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .coordinator import FossibotDataUpdateCoordinator

# Import the connector from our new module structure
from .sydpower.connector import SydpowerConnector  

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fossibot from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = FossibotDataUpdateCoordinator(
        hass,
        config=entry.data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    )

    await coordinator.async_config_entry_first_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady
        
    _LOGGER.info("Setting up platforms: %s", PLATFORMS)


    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info("Platforms setup complete, coordinator listeners: %d", 
                len(coordinator._listeners))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok