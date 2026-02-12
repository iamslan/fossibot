"""Tests for entity definitions: sensor, switch, select, number coverage and command completeness.

These verify that:
- Every parsed data key has a corresponding entity definition
- Every command referenced by switches/selects exists in the connector's COMMANDS dict
- Every writable register has a controllable entity (number, select, or switch)
- No duplicate unique_id patterns exist
"""

import pytest

from fossibot_ha.sydpower.modbus import (
    WRITABLE_REGISTERS,
    parse_registers,
)
from fossibot_ha.sydpower.const import (
    REGISTER_MAXIMUM_CHARGING_CURRENT,
    REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT, REGISTER_AC_OUTPUT,
    REGISTER_LED, REGISTER_AC_SILENT_CHARGING,
    REGISTER_USB_STANDBY_TIME, REGISTER_AC_STANDBY_TIME,
    REGISTER_DC_STANDBY_TIME, REGISTER_SCREEN_REST_TIME,
    REGISTER_STOP_CHARGE_AFTER, REGISTER_DISCHARGE_LIMIT,
    REGISTER_CHARGING_LIMIT, REGISTER_SLEEP_TIME,
)


# ---------------------------------------------------------------------------
# Inline definitions (mirroring the entity platform files)
#
# We can't import the actual HA entity files because they depend on
# homeassistant imports. Instead, we replicate the definition dicts
# and test invariants against the modbus layer.
# ---------------------------------------------------------------------------

# sensor.py — read-only sensors
SENSOR_KEYS = [
    "soc", "soc_s1", "soc_s2",
    "dcInput", "totalInput", "acChargingRate", "totalOutput",
    "acOutputVoltage", "acOutputFrequency", "acInputVoltage", "acInputFrequency",
]

# switch.py — boolean on/off entities
SWITCH_DEFINITIONS = [
    {"name": "USB Output", "key": "usbOutput", "on_command": "REGEnableUSBOutput", "off_command": "REGDisableUSBOutput"},
    {"name": "DC Output", "key": "dcOutput", "on_command": "REGEnableDCOutput", "off_command": "REGDisableDCOutput"},
    {"name": "AC Output", "key": "acOutput", "on_command": "REGEnableACOutput", "off_command": "REGDisableACOutput"},
    {"name": "AC Silent Charging", "key": "acSilentCharging", "on_command": "REGEnableACSilentChg", "off_command": "REGDisableACSilentChg"},
]

# select.py — LED mode (command-based)
LED_MODES = {
    "Off": "REGDisableLED",
    "On": "REGEnableLEDAlways",
    "SOS": "REGEnableLEDSOS",
    "Flash": "REGEnableLEDFlash",
}

# select.py — register-based selects (discrete option sets)
REGISTER_SELECT_KEYS = [
    {"key": "usbStandbyTime", "register": REGISTER_USB_STANDBY_TIME, "options_count": 5},
    {"key": "acStandbyTime", "register": REGISTER_AC_STANDBY_TIME, "options_count": 4},
    {"key": "dcStandbyTime", "register": REGISTER_DC_STANDBY_TIME, "options_count": 4},
    {"key": "screenRestTime", "register": REGISTER_SCREEN_REST_TIME, "options_count": 5},
    {"key": "wholeMachineUnusedTime", "register": REGISTER_SLEEP_TIME, "options_count": 4},
]

# number.py — continuous range entities
NUMBER_DEFINITIONS = [
    {"key": "maximumChargingCurrent", "register": REGISTER_MAXIMUM_CHARGING_CURRENT, "min": 1, "max": 20},
    {"key": "stopChargeAfter", "register": REGISTER_STOP_CHARGE_AFTER, "min": 0, "max": 1440},
    {"key": "dischargeLowerLimit", "register": REGISTER_DISCHARGE_LIMIT, "min": 0, "max": 100},
    {"key": "acChargingUpperLimit", "register": REGISTER_CHARGING_LIMIT, "min": 0, "max": 100},
]

# Connector COMMANDS dict (pre-defined byte sequences)
CONNECTOR_COMMANDS = {
    "REGRequestSettings",
    "REGDisableUSBOutput", "REGEnableUSBOutput",
    "REGDisableDCOutput", "REGEnableDCOutput",
    "REGDisableACOutput", "REGEnableACOutput",
    "REGDisableLED", "REGEnableLEDAlways",
    "REGEnableLEDSOS", "REGEnableLEDFlash",
    "REGDisableACSilentChg", "REGEnableACSilentChg",
}


# ---------------------------------------------------------------------------
# Full entity coverage: every parse_registers key has an entity
# ---------------------------------------------------------------------------

class TestEntityCoverage:
    """Every key emitted by parse_registers should have a corresponding entity."""

    @staticmethod
    def _all_parsed_keys():
        """Collect every key that parse_registers can produce."""
        keys = set()
        regs = [0] * 81
        regs[41] = 0xFFFF  # all outputs on
        regs[53] = 100     # slave 1 present
        regs[55] = 100     # slave 2 present
        keys.update(parse_registers(regs, "device/response/client/04").keys())
        keys.update(parse_registers(regs, "device/response/client/data").keys())
        return keys

    @staticmethod
    def _all_entity_keys():
        """Collect all data keys covered by any entity type."""
        keys = set(SENSOR_KEYS)
        keys.update(d["key"] for d in SWITCH_DEFINITIONS)
        keys.add("ledOutput")  # LED mode select
        keys.update(d["key"] for d in REGISTER_SELECT_KEYS)
        keys.update(d["key"] for d in NUMBER_DEFINITIONS)
        return keys

    def test_all_parsed_keys_have_entities(self):
        parsed = self._all_parsed_keys()
        entities = self._all_entity_keys()
        missing = parsed - entities
        assert missing == set(), (
            "Keys from parse_registers with no entity: %s" % missing
        )

    def test_no_entity_key_collisions(self):
        """No key should be claimed by multiple entity types."""
        sensor_keys = set(SENSOR_KEYS)
        switch_keys = {d["key"] for d in SWITCH_DEFINITIONS}
        select_keys = {"ledOutput"} | {d["key"] for d in REGISTER_SELECT_KEYS}
        number_keys = {d["key"] for d in NUMBER_DEFINITIONS}

        all_groups = [sensor_keys, switch_keys, select_keys, number_keys]
        all_keys = []
        for g in all_groups:
            all_keys.extend(g)
        assert len(all_keys) == len(set(all_keys)), "Duplicate key across entity types"


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------

class TestSensorDefinitions:
    def test_no_duplicate_sensor_keys(self):
        assert len(SENSOR_KEYS) == len(set(SENSOR_KEYS))

    def test_sensors_are_read_only(self):
        """No sensor key should correspond to a writable register entity."""
        number_keys = {d["key"] for d in NUMBER_DEFINITIONS}
        select_keys = {d["key"] for d in REGISTER_SELECT_KEYS}
        controllable = number_keys | select_keys
        overlap = set(SENSOR_KEYS) & controllable
        assert overlap == set(), (
            "These keys are sensors but should be number/select: %s" % overlap
        )


# ---------------------------------------------------------------------------
# Switch command completeness
# ---------------------------------------------------------------------------

class TestSwitchCommands:
    def test_all_switch_commands_in_connector(self):
        for defn in SWITCH_DEFINITIONS:
            assert defn["on_command"] in CONNECTOR_COMMANDS, (
                "%s on_command not in COMMANDS" % defn["name"]
            )
            assert defn["off_command"] in CONNECTOR_COMMANDS, (
                "%s off_command not in COMMANDS" % defn["name"]
            )

    def test_no_duplicate_switch_keys(self):
        keys = [d["key"] for d in SWITCH_DEFINITIONS]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Select (LED + register-based)
# ---------------------------------------------------------------------------

class TestSelectDefinitions:
    def test_all_led_commands_in_connector(self):
        for mode, command in LED_MODES.items():
            assert command in CONNECTOR_COMMANDS, (
                "LED mode '%s' → '%s' not in COMMANDS" % (mode, command)
            )

    def test_led_mode_count_matches_register(self):
        assert len(LED_MODES) == len(WRITABLE_REGISTERS[REGISTER_LED])

    def test_register_select_options_match_writable_registers(self):
        """Each register select should have exactly as many options as
        allowed values in WRITABLE_REGISTERS."""
        for defn in REGISTER_SELECT_KEYS:
            allowed = WRITABLE_REGISTERS[defn["register"]]
            assert defn["options_count"] == len(allowed), (
                "Select '%s' has %d options but register allows %d values"
                % (defn["key"], defn["options_count"], len(allowed))
            )

    def test_no_duplicate_select_keys(self):
        keys = [d["key"] for d in REGISTER_SELECT_KEYS]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Number
# ---------------------------------------------------------------------------

class TestNumberDefinitions:
    def test_all_number_registers_in_writable(self):
        for defn in NUMBER_DEFINITIONS:
            assert defn["register"] in WRITABLE_REGISTERS, (
                "Number '%s' register %d not in WRITABLE_REGISTERS"
                % (defn["key"], defn["register"])
            )

    def test_no_duplicate_number_keys(self):
        keys = [d["key"] for d in NUMBER_DEFINITIONS]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Writable register ↔ entity mapping
# ---------------------------------------------------------------------------

class TestWritableRegisterEntityMapping:
    """Every writable register should be reachable from some entity."""

    @staticmethod
    def _all_entity_registers():
        """Collect all register IDs that have a controllable entity."""
        regs = set()
        # Switches: boolean registers
        reg_map = {
            REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
            REGISTER_AC_OUTPUT, REGISTER_AC_SILENT_CHARGING,
        }
        regs.update(reg_map)
        # LED select
        regs.add(REGISTER_LED)
        # Register-based selects
        for defn in REGISTER_SELECT_KEYS:
            regs.add(defn["register"])
        # Numbers
        for defn in NUMBER_DEFINITIONS:
            regs.add(defn["register"])
        return regs

    def test_every_writable_register_has_entity(self):
        entity_regs = self._all_entity_registers()
        writable_regs = set(WRITABLE_REGISTERS.keys())
        missing = writable_regs - entity_regs
        assert missing == set(), (
            "Writable registers with no entity: %s" % missing
        )

    def test_boolean_registers_have_switches(self):
        for reg in [REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
                    REGISTER_AC_OUTPUT, REGISTER_AC_SILENT_CHARGING]:
            assert WRITABLE_REGISTERS[reg] == frozenset({0, 1})

    def test_led_register_has_select(self):
        switch_keys = {d["key"] for d in SWITCH_DEFINITIONS}
        assert "ledOutput" not in switch_keys
