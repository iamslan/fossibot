# modbus.py
"""
Modbus command conversion functions for Fossibot devices.

SAFETY NOTE: Fossibot firmware does NOT validate register write values.
Writing an out-of-range value can permanently brick a device.  Every write
MUST go through ``get_write_modbus()``, which validates against the
WRITABLE_REGISTERS allowlist before encoding.
"""

from typing import Dict, FrozenSet, List, Union
from .const import (
    REGISTER_MODBUS_ADDRESS, REGISTER_TOTAL_INPUT, REGISTER_DC_INPUT,
    REGISTER_MAXIMUM_CHARGING_CURRENT, REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
    REGISTER_AC_OUTPUT, REGISTER_LED, REGISTER_TOTAL_OUTPUT,
    REGISTER_ACTIVE_OUTPUT_LIST, REGISTER_STATE_OF_CHARGE,
    REGISTER_AC_SILENT_CHARGING, REGISTER_USB_STANDBY_TIME,
    REGISTER_AC_STANDBY_TIME, REGISTER_DC_STANDBY_TIME,
    REGISTER_SCREEN_REST_TIME, REGISTER_STOP_CHARGE_AFTER,
    REGISTER_DISCHARGE_LIMIT, REGISTER_CHARGING_LIMIT, REGISTER_SLEEP_TIME,
)


# ---------------------------------------------------------------------------
# Writable-register safety map
#
# Each entry maps a register number to a frozenset of allowed integer values.
# ``get_write_modbus()`` refuses to encode a value that is not in this set.
#
# Source: Fossibot BrightEMS app reverse engineering (possibleValues arrays).
# Registers without possibleValues use bounded ranges with a safety margin.
# ---------------------------------------------------------------------------

WRITABLE_REGISTERS: Dict[int, FrozenSet[int]] = {
    # Charging current: 1-20 A
    REGISTER_MAXIMUM_CHARGING_CURRENT: frozenset(range(1, 21)),

    # Boolean outputs: 0 = off, 1 = on
    REGISTER_USB_OUTPUT: frozenset({0, 1}),
    REGISTER_DC_OUTPUT: frozenset({0, 1}),
    REGISTER_AC_OUTPUT: frozenset({0, 1}),

    # LED mode: 0=Off, 1=On, 2=SOS, 3=Flash
    REGISTER_LED: frozenset({0, 1, 2, 3}),

    # AC silent charging: 0=off, 1=on
    REGISTER_AC_SILENT_CHARGING: frozenset({0, 1}),

    # Standby timers (minutes)
    REGISTER_USB_STANDBY_TIME: frozenset({0, 3, 5, 10, 30}),
    REGISTER_AC_STANDBY_TIME: frozenset({0, 480, 960, 1440}),
    REGISTER_DC_STANDBY_TIME: frozenset({0, 480, 960, 1440}),

    # Screen rest time (seconds)
    REGISTER_SCREEN_REST_TIME: frozenset({0, 180, 300, 600, 1800}),

    # Sleep time (minutes)
    REGISTER_SLEEP_TIME: frozenset({5, 10, 30, 480}),

    # Stop charge after (minutes) - no possibleValues in app, allow 0-1440
    REGISTER_STOP_CHARGE_AFTER: frozenset(range(0, 1441)),

    # Discharge limit (permille in register, 0-1000 → 0-100%)
    REGISTER_DISCHARGE_LIMIT: frozenset(range(0, 1001)),

    # Charging limit (permille in register, 0-1000 → 0-100%)
    REGISTER_CHARGING_LIMIT: frozenset(range(0, 1001)),
}


class ModbusValidationError(ValueError):
    """Raised when a register write value is not in the allowed set."""


# ---------------------------------------------------------------------------
# Encoding helpers (names kept from original JS for traceability)
# ---------------------------------------------------------------------------

def int_to_high_low(value: int) -> Dict[str, int]:
    """Convert an integer to a high/low dictionary (16-bit)."""
    return {'low': value & 0xff, 'high': (value >> 8) & 0xff}


def high_low_to_int(high: int, low: int) -> int:
    """Convert high and low parts to a 16-bit integer."""
    return ((high & 0xff) << 8) | (low & 0xff)


def zi(e: int) -> Dict[str, int]:
    """Convert integer to high/low dict (alias for int_to_high_low)."""
    return {'low': e & 0xff, 'high': (e >> 8) & 0xff}


def ta(arr: List[int]) -> int:
    """CRC-16 checksum (Modbus variant)."""
    t = 0xffff
    for byte in arr:
        t ^= byte
        for _ in range(8):
            if t & 1:
                t = (t >> 1) ^ 40961
            else:
                t >>= 1
    return t & 0xffff


def sa(e: int, t: int, n: List[int], o: bool) -> List[int]:
    """Build the command array and append the checksum."""
    r = [e, t] + n
    cs = zi(ta(r))
    if o:
        r += [cs['low'], cs['high']]
    else:
        r += [cs['high'], cs['low']]
    return r


def aa(e: int, t: int, n: List[int], o: bool) -> List[int]:
    """Wrap getWriteModbus: convert feature number into two bytes and build command."""
    r = zi(t)
    return sa(e, 6, [r['high'], r['low']] + n, o)


def ia(e: int, t: int, n: int, o: bool) -> List[int]:
    """Wrap getReadModbus: prepare a read command."""
    r = zi(t)
    i_val = n & 0xff
    a_val = n >> 8
    return sa(e, 3, [r['high'], r['low'], a_val, i_val], o)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_write_modbus(address: int, feature: int, value: int) -> List[int]:
    """Encode a validated Modbus write command.

    Raises ModbusValidationError if the register is unknown or the value
    is not in the allowed set.
    """
    allowed = WRITABLE_REGISTERS.get(feature)
    if allowed is None:
        raise ModbusValidationError(
            "Register %d is not in WRITABLE_REGISTERS — refusing to write" % feature
        )
    if value not in allowed:
        raise ModbusValidationError(
            "Value %d is not allowed for register %d. Allowed: %s"
            % (value, feature, _format_allowed(allowed))
        )
    a = int_to_high_low(value)
    return aa(address, feature, [a['high'], a['low']], False)


def get_read_modbus(address: int, count: int) -> List[int]:
    """Encode a Modbus read command."""
    return ia(address, 0, count, False)


def _format_allowed(allowed: FrozenSet[int]) -> str:
    """Format an allowed-values set for error messages."""
    if len(allowed) <= 20:
        return "{%s}" % ", ".join(str(v) for v in sorted(allowed))
    lo, hi = min(allowed), max(allowed)
    return "{%d..%d} (%d values)" % (lo, hi, len(allowed))


# ---------------------------------------------------------------------------
# Pre-defined commands (validated at import time)
# ---------------------------------------------------------------------------

REGRequestSettings      = get_read_modbus(REGISTER_MODBUS_ADDRESS, 80)
REGDisableUSBOutput     = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 0)
REGEnableUSBOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
REGDisableDCOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 0)
REGEnableDCOutput       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 1)
REGDisableACOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 0)
REGEnableACOutput       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 1)
REGDisableLED           = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 0)
REGEnableLEDAlways      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 1)
REGEnableLEDSOS         = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 2)
REGEnableLEDFlash       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 3)
REGDisableACSilentChg   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_SILENT_CHARGING, 0)
REGEnableACSilentChg    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_SILENT_CHARGING, 1)


# ---------------------------------------------------------------------------
# Register parsing
# ---------------------------------------------------------------------------

def parse_registers(registers: List[int], topic: str) -> Dict[str, Union[int, float, bool]]:
    """Parse device registers based on topic and return structured data."""
    device_update = {}

    if len(registers) == 81:
        if 'device/response/client/04' in topic:
            # Get register 41 value (active outputs list)
            register_value = registers[41]

            # Replicate the JavaScript logic exactly
            # ("0000000000000000" + e[41].toString(2).padStart(8, "0")).slice(-16)
            binary_str = format(register_value, '016b')

            device_update.update({
                "soc": round(registers[56] / 1000 * 100, 1),
                "dcInput": registers[4],
                "totalInput": registers[6],
                "totalOutput": registers[39],
                "acOutputVoltage": (registers[18] / 10),
                "acOutputFrequency": (registers[19] / 10),
                "acInputVoltage": (registers[21] / 10),
                "acInputFrequency": (registers[22] / 100),

                # Direct string indexing matches JS array indexing after split
                "usbOutput": binary_str[6] == '1',   # Position 6: USB Output
                "dcOutput": binary_str[5] == '1',     # Position 5: DC Output
                "acOutput": binary_str[4] == '1',     # Position 4: AC Output
                "ledOutput": binary_str[3] == '1',    # Position 3: LED Output
            })
            if registers[53] > 0:
                device_update.update({
                    "soc_s1": round(registers[53] / 1000 * 100 - 1, 1),
                })
            if registers[55] > 0:
                device_update.update({
                    "soc_s2": round(registers[55] / 1000 * 100 - 1, 1),
                })
        elif 'device/response/client/data' in topic:
            device_update.update({
                "acChargingRate": registers[13],
                "maximumChargingCurrent": registers[20],
                "acSilentCharging": (registers[57] == 1),
                "usbStandbyTime": registers[59],
                "acStandbyTime": registers[60],
                "dcStandbyTime": registers[61],
                "screenRestTime": registers[62],
                "stopChargeAfter": registers[63],
                "dischargeLowerLimit": (registers[66] / 10),
                "acChargingUpperLimit": (registers[67] / 10),
                "wholeMachineUnusedTime": registers[68]
            })
    elif len(registers) >= 57:
        # Partial update with just SOC
        device_update["soc"] = round(registers[56] / 1000 * 100, 1)
        if registers[53] > 0:
            device_update["soc_s1"] = round(registers[53] / 1000 * 100 - 1, 1)
        if registers[55] > 0:
            device_update["soc_s2"] = round(registers[55] / 1000 * 100 - 1, 1)

    return device_update
