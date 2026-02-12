"""Tests for sydpower Modbus encoding, decoding, CRC, and validation.

These tests run WITHOUT Home Assistant — only the pure-Python modbus module
is exercised.
"""

import pytest

from fossibot_ha.sydpower.modbus import (
    int_to_high_low,
    high_low_to_int,
    zi,
    ta,
    sa,
    aa,
    ia,
    get_write_modbus,
    get_read_modbus,
    parse_registers,
    ModbusValidationError,
    WRITABLE_REGISTERS,
    # Pre-defined commands
    REGRequestSettings,
    REGDisableUSBOutput,
    REGEnableUSBOutput,
    REGDisableDCOutput,
    REGEnableDCOutput,
    REGDisableACOutput,
    REGEnableACOutput,
    REGDisableLED,
    REGEnableLEDAlways,
    REGEnableLEDSOS,
    REGEnableLEDFlash,
    REGDisableACSilentChg,
    REGEnableACSilentChg,
)
from fossibot_ha.sydpower.const import (
    REGISTER_MODBUS_ADDRESS,
    REGISTER_MAXIMUM_CHARGING_CURRENT,
    REGISTER_USB_OUTPUT,
    REGISTER_DC_OUTPUT,
    REGISTER_AC_OUTPUT,
    REGISTER_LED,
    REGISTER_AC_SILENT_CHARGING,
    REGISTER_USB_STANDBY_TIME,
    REGISTER_AC_STANDBY_TIME,
    REGISTER_DC_STANDBY_TIME,
    REGISTER_SCREEN_REST_TIME,
    REGISTER_STOP_CHARGE_AFTER,
    REGISTER_DISCHARGE_LIMIT,
    REGISTER_CHARGING_LIMIT,
    REGISTER_SLEEP_TIME,
)


# ---------------------------------------------------------------------------
# int_to_high_low / high_low_to_int round-trip
# ---------------------------------------------------------------------------

class TestHighLow:
    """Test 16-bit high/low byte conversion."""

    def test_zero(self):
        result = int_to_high_low(0)
        assert result == {"low": 0, "high": 0}

    def test_255(self):
        result = int_to_high_low(255)
        assert result == {"low": 255, "high": 0}

    def test_256(self):
        result = int_to_high_low(256)
        assert result == {"low": 0, "high": 1}

    def test_0xABCD(self):
        result = int_to_high_low(0xABCD)
        assert result == {"low": 0xCD, "high": 0xAB}

    def test_round_trip(self):
        for val in [0, 1, 127, 255, 256, 1000, 0xFFFF]:
            hl = int_to_high_low(val)
            assert high_low_to_int(hl["high"], hl["low"]) == val

    def test_zi_matches_int_to_high_low(self):
        for val in [0, 42, 1000, 0xFFFF]:
            assert zi(val) == int_to_high_low(val)


# ---------------------------------------------------------------------------
# CRC-16 (ta)
# ---------------------------------------------------------------------------

class TestCRC:
    """Test CRC-16 checksum function."""

    def test_empty(self):
        assert ta([]) == 0xFFFF

    def test_deterministic(self):
        data = [17, 6, 0, 24, 0, 1]
        assert ta(data) == ta(data)

    def test_different_data_different_crc(self):
        assert ta([1, 2, 3]) != ta([1, 2, 4])

    def test_known_modbus_address(self):
        """CRC of [REGISTER_MODBUS_ADDRESS] should be non-trivial."""
        result = ta([REGISTER_MODBUS_ADDRESS])
        assert result != 0
        assert result != 0xFFFF


# ---------------------------------------------------------------------------
# Command structure (sa, aa, ia)
# ---------------------------------------------------------------------------

class TestCommandBuilding:
    """Test low-level command assembly."""

    def test_sa_appends_checksum(self):
        cmd = sa(17, 6, [0, 24, 0, 1], False)
        # 2 (header) + 4 (payload) + 2 (checksum) = 8 bytes
        assert len(cmd) == 8
        assert cmd[0] == 17   # address
        assert cmd[1] == 6    # function code (write)

    def test_sa_swap_order(self):
        cmd_normal = sa(17, 6, [0, 24, 0, 1], False)
        cmd_swapped = sa(17, 6, [0, 24, 0, 1], True)
        # Checksums should be in opposite byte order
        assert cmd_normal[-2:] == cmd_swapped[-2:][::-1]

    def test_aa_write_command_structure(self):
        cmd = aa(17, 24, [0, 1], False)
        assert cmd[0] == 17  # address
        assert cmd[1] == 6   # function code 6 = write
        assert len(cmd) == 8  # addr + fc + reg_h + reg_l + val_h + val_l + crc_h + crc_l

    def test_ia_read_command_structure(self):
        cmd = ia(17, 0, 80, False)
        assert cmd[0] == 17  # address
        assert cmd[1] == 3   # function code 3 = read
        assert len(cmd) == 8

    def test_get_read_modbus_matches_ia(self):
        assert get_read_modbus(17, 80) == ia(17, 0, 80, False)


# ---------------------------------------------------------------------------
# Pre-defined commands: sanity checks
# ---------------------------------------------------------------------------

class TestPredefinedCommands:
    """Verify pre-defined commands are valid byte arrays."""

    def test_all_predefined_are_lists(self):
        for cmd in [
            REGRequestSettings, REGDisableUSBOutput, REGEnableUSBOutput,
            REGDisableDCOutput, REGEnableDCOutput, REGDisableACOutput,
            REGEnableACOutput, REGDisableLED, REGEnableLEDAlways,
            REGEnableLEDSOS, REGEnableLEDFlash, REGDisableACSilentChg,
            REGEnableACSilentChg,
        ]:
            assert isinstance(cmd, list)
            assert all(isinstance(b, int) for b in cmd)
            assert all(0 <= b <= 255 for b in cmd)

    def test_write_commands_length(self):
        """All write commands should be 8 bytes."""
        for cmd in [
            REGDisableUSBOutput, REGEnableUSBOutput,
            REGDisableDCOutput, REGEnableDCOutput,
            REGDisableACOutput, REGEnableACOutput,
            REGDisableLED, REGEnableLEDAlways,
            REGEnableLEDSOS, REGEnableLEDFlash,
            REGDisableACSilentChg, REGEnableACSilentChg,
        ]:
            assert len(cmd) == 8

    def test_read_settings_length(self):
        """Read command should be 8 bytes."""
        assert len(REGRequestSettings) == 8

    def test_all_start_with_address(self):
        """All commands should start with the Modbus address."""
        for cmd in [
            REGRequestSettings, REGDisableUSBOutput, REGEnableUSBOutput,
            REGDisableDCOutput, REGEnableDCOutput,
        ]:
            assert cmd[0] == REGISTER_MODBUS_ADDRESS

    def test_enable_disable_differ(self):
        """Enable and disable variants should produce different byte sequences."""
        assert REGEnableUSBOutput != REGDisableUSBOutput
        assert REGEnableDCOutput != REGDisableDCOutput
        assert REGEnableACOutput != REGDisableACOutput
        assert REGEnableACSilentChg != REGDisableACSilentChg


# ---------------------------------------------------------------------------
# WRITABLE_REGISTERS safety map
# ---------------------------------------------------------------------------

class TestWritableRegisters:
    """Test the WRITABLE_REGISTERS safety map completeness and correctness."""

    def test_all_expected_registers_present(self):
        expected = {
            REGISTER_MAXIMUM_CHARGING_CURRENT,
            REGISTER_USB_OUTPUT,
            REGISTER_DC_OUTPUT,
            REGISTER_AC_OUTPUT,
            REGISTER_LED,
            REGISTER_AC_SILENT_CHARGING,
            REGISTER_USB_STANDBY_TIME,
            REGISTER_AC_STANDBY_TIME,
            REGISTER_DC_STANDBY_TIME,
            REGISTER_SCREEN_REST_TIME,
            REGISTER_SLEEP_TIME,
            REGISTER_STOP_CHARGE_AFTER,
            REGISTER_DISCHARGE_LIMIT,
            REGISTER_CHARGING_LIMIT,
        }
        assert expected == set(WRITABLE_REGISTERS.keys())

    def test_all_values_are_frozensets(self):
        for reg, allowed in WRITABLE_REGISTERS.items():
            assert isinstance(allowed, frozenset), (
                "Register %d should use frozenset" % reg
            )

    def test_boolean_registers(self):
        """Boolean registers should only allow 0 and 1."""
        for reg in [
            REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
            REGISTER_AC_OUTPUT, REGISTER_AC_SILENT_CHARGING,
        ]:
            assert WRITABLE_REGISTERS[reg] == frozenset({0, 1})

    def test_led_modes(self):
        assert WRITABLE_REGISTERS[REGISTER_LED] == frozenset({0, 1, 2, 3})

    def test_charging_current_range(self):
        allowed = WRITABLE_REGISTERS[REGISTER_MAXIMUM_CHARGING_CURRENT]
        assert 0 not in allowed   # 0 A would be invalid
        assert 1 in allowed       # min
        assert 20 in allowed      # max
        assert 21 not in allowed  # over max

    def test_usb_standby_time(self):
        assert WRITABLE_REGISTERS[REGISTER_USB_STANDBY_TIME] == frozenset({0, 3, 5, 10, 30})

    def test_ac_standby_time(self):
        assert WRITABLE_REGISTERS[REGISTER_AC_STANDBY_TIME] == frozenset({0, 480, 960, 1440})

    def test_dc_standby_time(self):
        assert WRITABLE_REGISTERS[REGISTER_DC_STANDBY_TIME] == frozenset({0, 480, 960, 1440})

    def test_screen_rest_time(self):
        assert WRITABLE_REGISTERS[REGISTER_SCREEN_REST_TIME] == frozenset({0, 180, 300, 600, 1800})

    def test_sleep_time(self):
        assert WRITABLE_REGISTERS[REGISTER_SLEEP_TIME] == frozenset({5, 10, 30, 480})

    def test_discharge_limit_boundaries(self):
        allowed = WRITABLE_REGISTERS[REGISTER_DISCHARGE_LIMIT]
        assert 0 in allowed
        assert 1000 in allowed
        assert -1 not in allowed
        assert 1001 not in allowed

    def test_charging_limit_boundaries(self):
        allowed = WRITABLE_REGISTERS[REGISTER_CHARGING_LIMIT]
        assert 0 in allowed
        assert 1000 in allowed
        assert -1 not in allowed
        assert 1001 not in allowed


# ---------------------------------------------------------------------------
# get_write_modbus validation
# ---------------------------------------------------------------------------

class TestWriteValidation:
    """Test that get_write_modbus rejects bad values."""

    def test_valid_write_succeeds(self):
        result = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
        assert isinstance(result, list)
        assert len(result) == 8

    def test_unknown_register_raises(self):
        with pytest.raises(ModbusValidationError, match="not in WRITABLE_REGISTERS"):
            get_write_modbus(REGISTER_MODBUS_ADDRESS, 999, 0)

    def test_out_of_range_value_raises(self):
        with pytest.raises(ModbusValidationError, match="not allowed for register"):
            get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                REGISTER_USB_OUTPUT,
                2,  # only 0 or 1 allowed
            )

    def test_charging_current_zero_raises(self):
        with pytest.raises(ModbusValidationError):
            get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                REGISTER_MAXIMUM_CHARGING_CURRENT,
                0,
            )

    def test_charging_current_21_raises(self):
        with pytest.raises(ModbusValidationError):
            get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                REGISTER_MAXIMUM_CHARGING_CURRENT,
                21,
            )

    def test_charging_current_valid_range(self):
        for val in range(1, 21):
            result = get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                REGISTER_MAXIMUM_CHARGING_CURRENT,
                val,
            )
            assert len(result) == 8

    def test_led_invalid_mode_raises(self):
        with pytest.raises(ModbusValidationError):
            get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 4)

    def test_usb_standby_invalid_raises(self):
        with pytest.raises(ModbusValidationError):
            get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                REGISTER_USB_STANDBY_TIME,
                7,  # not in {0, 3, 5, 10, 30}
            )

    def test_negative_value_raises(self):
        with pytest.raises(ModbusValidationError):
            get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, -1)

    def test_read_only_register_raises(self):
        """Attempting to write to a read-only register (like SOC) should fail."""
        from fossibot_ha.sydpower.const import REGISTER_STATE_OF_CHARGE
        with pytest.raises(ModbusValidationError):
            get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_STATE_OF_CHARGE, 500)

    def test_validated_write_matches_unvalidated_encoding(self):
        """The validated path should produce the same bytes as the raw encoding."""
        # Build expected result manually using the low-level functions
        from fossibot_ha.sydpower.modbus import aa, int_to_high_low
        a = int_to_high_low(1)
        expected = aa(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, [a['high'], a['low']], False)
        actual = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
        assert actual == expected


# ---------------------------------------------------------------------------
# parse_registers
# ---------------------------------------------------------------------------

class TestParseRegisters:
    """Test register data parsing."""

    @staticmethod
    def _make_registers(length=81, overrides=None):
        """Create a zeroed register array with optional overrides."""
        regs = [0] * length
        if overrides:
            for idx, val in overrides.items():
                regs[idx] = val
        return regs

    def test_04_topic_basic_soc(self):
        regs = self._make_registers(overrides={56: 750})  # 750/1000*100 = 75.0%
        result = parse_registers(regs, "device/response/client/04")
        assert result["soc"] == 75.0

    def test_04_topic_outputs_all_off(self):
        regs = self._make_registers(overrides={41: 0})
        result = parse_registers(regs, "device/response/client/04")
        assert result["usbOutput"] is False
        assert result["dcOutput"] is False
        assert result["acOutput"] is False
        assert result["ledOutput"] is False

    def test_04_topic_usb_on(self):
        # USB is bit 6 in 16-bit binary: 0b0000001000000000 = 512
        # Wait, let me recalculate.
        # binary_str = format(value, '016b')
        # usbOutput = binary_str[6] == '1' → bit at position 6 from left
        # Position 6 from left in 16 bits = bit 9 from right = 2^9 = 512
        regs = self._make_registers(overrides={41: 512})
        result = parse_registers(regs, "device/response/client/04")
        assert result["usbOutput"] is True
        assert result["dcOutput"] is False

    def test_04_topic_dc_on(self):
        # dcOutput = binary_str[5] == '1' → bit 10 from right = 2^10 = 1024
        regs = self._make_registers(overrides={41: 1024})
        result = parse_registers(regs, "device/response/client/04")
        assert result["dcOutput"] is True
        assert result["usbOutput"] is False

    def test_04_topic_ac_on(self):
        # acOutput = binary_str[4] == '1' → bit 11 from right = 2^11 = 2048
        regs = self._make_registers(overrides={41: 2048})
        result = parse_registers(regs, "device/response/client/04")
        assert result["acOutput"] is True

    def test_04_topic_led_on(self):
        # ledOutput = binary_str[3] == '1' → bit 12 from right = 2^12 = 4096
        regs = self._make_registers(overrides={41: 4096})
        result = parse_registers(regs, "device/response/client/04")
        assert result["ledOutput"] is True

    def test_04_topic_all_outputs_on(self):
        # All four: 512 + 1024 + 2048 + 4096 = 7680
        regs = self._make_registers(overrides={41: 7680})
        result = parse_registers(regs, "device/response/client/04")
        assert result["usbOutput"] is True
        assert result["dcOutput"] is True
        assert result["acOutput"] is True
        assert result["ledOutput"] is True

    def test_04_topic_ac_values(self):
        regs = self._make_registers(overrides={18: 2200, 19: 500, 21: 1200, 22: 5000})
        result = parse_registers(regs, "device/response/client/04")
        assert result["acOutputVoltage"] == 220.0
        assert result["acOutputFrequency"] == 50.0
        assert result["acInputVoltage"] == 120.0
        assert result["acInputFrequency"] == 50.0

    def test_04_topic_slave_soc(self):
        regs = self._make_registers(overrides={53: 800, 55: 600})
        result = parse_registers(regs, "device/response/client/04")
        assert "soc_s1" in result
        assert "soc_s2" in result
        # 800/1000*100 - 1 = 79.0
        assert result["soc_s1"] == 79.0
        # 600/1000*100 - 1 = 59.0
        assert result["soc_s2"] == 59.0

    def test_04_topic_slave_soc_zero_excluded(self):
        regs = self._make_registers(overrides={53: 0, 55: 0})
        result = parse_registers(regs, "device/response/client/04")
        assert "soc_s1" not in result
        assert "soc_s2" not in result

    def test_data_topic(self):
        regs = self._make_registers(overrides={
            13: 5,      # acChargingRate
            20: 15,     # maximumChargingCurrent
            57: 1,      # acSilentCharging (on)
            59: 10,     # usbStandbyTime
            60: 480,    # acStandbyTime
            61: 960,    # dcStandbyTime
            62: 300,    # screenRestTime
            63: 120,    # stopChargeAfter
            66: 200,    # dischargeLowerLimit (200/10 = 20.0%)
            67: 900,    # acChargingUpperLimit (900/10 = 90.0%)
            68: 30,     # wholeMachineUnusedTime
        })
        result = parse_registers(regs, "device/response/client/data")
        assert result["acChargingRate"] == 5
        assert result["maximumChargingCurrent"] == 15
        assert result["acSilentCharging"] is True
        assert result["usbStandbyTime"] == 10
        assert result["acStandbyTime"] == 480
        assert result["dcStandbyTime"] == 960
        assert result["screenRestTime"] == 300
        assert result["stopChargeAfter"] == 120
        assert result["dischargeLowerLimit"] == 20.0
        assert result["acChargingUpperLimit"] == 90.0
        assert result["wholeMachineUnusedTime"] == 30

    def test_data_topic_silent_charging_off(self):
        regs = self._make_registers(overrides={57: 0})
        result = parse_registers(regs, "device/response/client/data")
        assert result["acSilentCharging"] is False

    def test_partial_update_soc_only(self):
        regs = self._make_registers(length=57, overrides={56: 500})
        result = parse_registers(regs, "device/response/client/04")
        assert result["soc"] == 50.0
        assert "totalInput" not in result  # not a full 81-register update

    def test_partial_update_with_slaves(self):
        regs = self._make_registers(length=60, overrides={53: 700, 55: 0, 56: 500})
        result = parse_registers(regs, "device/response/client/04")
        assert result["soc"] == 50.0
        assert result["soc_s1"] == 69.0
        assert "soc_s2" not in result

    def test_short_registers_ignored(self):
        regs = self._make_registers(length=10)
        result = parse_registers(regs, "device/response/client/04")
        assert result == {}

    def test_unknown_topic_ignored(self):
        regs = self._make_registers()
        result = parse_registers(regs, "device/response/client/unknown")
        assert result == {}


# ---------------------------------------------------------------------------
# CRC integrity: encode → decode round-trip
# ---------------------------------------------------------------------------

class TestCRCIntegrity:
    """Verify CRC is consistent across encode operations."""

    def test_same_command_same_crc(self):
        """Two identical writes should produce identical byte sequences."""
        cmd1 = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
        cmd2 = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
        assert cmd1 == cmd2

    def test_different_values_different_crc(self):
        """Different values for same register should produce different CRCs."""
        cmd0 = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 0)
        cmd1 = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
        assert cmd0 != cmd1
        # But same length
        assert len(cmd0) == len(cmd1)

    def test_crc_verifiable(self):
        """CRC of the payload (without CRC bytes) should match the appended CRC."""
        cmd = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 2)
        payload = cmd[:-2]
        computed_crc = ta(payload)
        # CRC is appended as [high, low] when o=False
        appended_crc = (cmd[-2] << 8) | cmd[-1]
        assert computed_crc == appended_crc
