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
