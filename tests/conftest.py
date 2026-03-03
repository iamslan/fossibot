"""Pytest configuration for Fossibot tests.

Rewrites sydpower's relative imports so the package can be tested
without installing it or Home Assistant.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Point directly at the integration package
INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "fossibot-ha"

# Stub out homeassistant so that importing entity.py / const.py doesn't blow up
ha_mock = MagicMock()
for mod in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.select",
    "homeassistant.helpers.entity_platform",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "voluptuous",
]:
    sys.modules.setdefault(mod, ha_mock)

# Register the integration as a top-level package named "fossibot_ha"
# so that `from fossibot_ha.sydpower.modbus import ...` works.
if "fossibot_ha" not in sys.modules:
    sys.path.insert(0, str(INTEGRATION_DIR.parent))
    # Python doesn't allow hyphens in package names, so we create an alias
    spec = importlib.util.spec_from_file_location(
        "fossibot_ha",
        INTEGRATION_DIR / "__init__.py",
        submodule_search_locations=[str(INTEGRATION_DIR)],
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["fossibot_ha"] = pkg

    # Also register sydpower sub-package
    sydpower_dir = INTEGRATION_DIR / "sydpower"
    sydpower_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower",
        sydpower_dir / "__init__.py",
        submodule_search_locations=[str(sydpower_dir)],
    )
    sydpower_pkg = importlib.util.module_from_spec(sydpower_spec)
    sys.modules["fossibot_ha.sydpower"] = sydpower_pkg

    # Now load const (no HA deps)
    const_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower.const",
        sydpower_dir / "const.py",
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules["fossibot_ha.sydpower.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    # Patch sydpower's relative import: when modbus.py does
    # `from .const import ...` it resolves to fossibot_ha.sydpower.const
    sydpower_pkg.const = const_mod

    # Now load modbus
    modbus_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower.modbus",
        sydpower_dir / "modbus.py",
    )
    modbus_mod = importlib.util.module_from_spec(modbus_spec)
    sys.modules["fossibot_ha.sydpower.modbus"] = modbus_mod
    modbus_spec.loader.exec_module(modbus_mod)
    sydpower_pkg.modbus = modbus_mod

    # Load logger (used by connector/mqtt_client)
    logger_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower.logger",
        sydpower_dir / "logger.py",
    )
    logger_mod = importlib.util.module_from_spec(logger_spec)
    sys.modules["fossibot_ha.sydpower.logger"] = logger_mod
    logger_spec.loader.exec_module(logger_mod)
    sydpower_pkg.logger = logger_mod

    # Stub api_client (has aiohttp dependency we don't need)
    api_mock = MagicMock()
    sys.modules["fossibot_ha.sydpower.api_client"] = api_mock
    sydpower_pkg.api_client = api_mock

    # Load mqtt_client
    mqtt_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower.mqtt_client",
        sydpower_dir / "mqtt_client.py",
    )
    mqtt_mod = importlib.util.module_from_spec(mqtt_spec)
    sys.modules["fossibot_ha.sydpower.mqtt_client"] = mqtt_mod
    mqtt_spec.loader.exec_module(mqtt_mod)
    sydpower_pkg.mqtt_client = mqtt_mod

    # Load connector
    connector_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.sydpower.connector",
        sydpower_dir / "connector.py",
    )
    connector_mod = importlib.util.module_from_spec(connector_spec)
    sys.modules["fossibot_ha.sydpower.connector"] = connector_mod
    connector_spec.loader.exec_module(connector_mod)
    sydpower_pkg.connector = connector_mod

    # Load HA-level const (has no HA deps, only string constants)
    ha_const_spec = importlib.util.spec_from_file_location(
        "fossibot_ha.const",
        INTEGRATION_DIR / "const.py",
    )
    ha_const_mod = importlib.util.module_from_spec(ha_const_spec)
    sys.modules["fossibot_ha.const"] = ha_const_mod
    ha_const_spec.loader.exec_module(ha_const_mod)
    pkg.const = ha_const_mod

