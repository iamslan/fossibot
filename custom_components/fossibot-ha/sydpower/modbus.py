# modbus.py
"""
Modbus command conversion functions for Fossibot devices.
"""

from typing import Dict, List, Tuple, Union
from .const import (
    REGISTER_MODBUS_ADDRESS, REGISTER_TOTAL_INPUT, REGISTER_DC_INPUT,
    REGISTER_MAXIMUM_CHARGING_CURRENT, REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
    REGISTER_AC_OUTPUT, REGISTER_LED, REGISTER_TOTAL_OUTPUT,
    REGISTER_ACTIVE_OUTPUT_LIST, REGISTER_STATE_OF_CHARGE, REGISTER_AC_SILENT_CHARGING
)

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
    """Compute checksum using the algorithm from JS function ta."""
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

def get_write_modbus(address: int, feature: int, value: int) -> List[int]:
    """Equivalent of getWriteModbus in JS."""
    a = int_to_high_low(value)
    return aa(address, feature, [a['high'], a['low']], False)

def get_read_modbus(address: int, count: int) -> List[int]:
    """Equivalent of getReadModbus in JS."""
    return ia(address, 0, count, False)

# Pre-defined commands
REGRequestSettings   = get_read_modbus(REGISTER_MODBUS_ADDRESS, 80)
REGDisableUSBOutput  = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 0)
REGEnableUSBOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
REGDisableDCOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 0)
REGEnableDCOutput    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 1)
REGDisableACOutput   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 0)
REGEnableACOutput    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 1)
REGDisableLED        = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 0)
REGEnableLEDAlways   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 1)
REGEnableLEDSOS      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 2)
REGEnableLEDFlash    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 3)

def parse_registers(registers: List[int], topic: str) -> Dict[str, Union[int, float, bool]]:
    """Parse device registers based on topic and return structured data."""
    device_update = {}
    
    if len(registers) == 81:
        if 'device/response/client/04' in topic:
            # Get register 41 value (active outputs list)
            register_value = registers[41]
            
            # Replicate the JavaScript logic exactly
            # This creates the exact same format as JS's:
            # ("0000000000000000" + e[41].toString(2).padStart(8, "0")).slice(-16)
            binary_str = format(register_value, '016b')
            
            device_update.update({
                "soc": round(registers[56] / 1000 * 100, 1),
                "dcInput": registers[4],
                "totalInput": registers[6],
                "totalOutput": registers[39],
                
                # IMPORTANT: Direct string indexing in Python is exactly the same
                # as array indexing in JavaScript after split
                "usbOutput": binary_str[6] == '1',   # Position 6: USB Output
                "dcOutput": binary_str[5] == '1',    # Position 5: DC Output
                "acOutput": binary_str[4] == '1',    # Position 4: AC Output
                "ledOutput": binary_str[3] == '1',   # Position 3: LED Output
            })
        elif 'device/response/client/data' in topic:
            device_update.update({
                "maximumChargingCurrent": registers[20],
                "acSilentCharging": (registers[57] == 1),
                "usbStandbyTime": registers[59],
                "acStandbyTime": registers[60],
                "dcStandbyTime": registers[61],
                "screenRestTime": registers[62],
                "stopChargeAfter": registers[63],
                "dischargeLowerLimit": registers[66],
                "acChargingUpperLimit": registers[67],
                "wholeMachineUnusedTime": registers[68]
            })
    elif len(registers) >= 57:
        # Partial update with just SOC
        device_update["soc"] = round(registers[56] / 1000 * 100, 1)
        
    return device_update