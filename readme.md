# Fossibot Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/iamslan/fossibot)](https://github.com/iamslan/fossibot/releases)
[![License: MIT](https://img.shields.io/github/license/iamslan/fossibot)](LICENSE)

A custom [Home Assistant](https://www.home-assistant.io/) integration to monitor and control **Fossibot / Sydpower** portable power stations via the BrightEMS cloud API.

> **Disclaimer** — This integration is unofficial and not affiliated with Fossibot, Sydpower, or BrightEMS. **Use at your own risk.** The authors are not responsible for any damage to your devices.

[Join our Discord](https://discord.gg/GPQ2bU5Q99) to help with development, report issues, or share feedback about your battery model.

---

## Features

- **11 sensors** — battery SoC (+ slave 1 & 2), power input/output, AC voltage & frequency
- **4 switches** — USB, DC, AC output toggles + AC silent charging
- **6 selects** — LED mode, USB/AC/DC standby time, screen rest time, sleep time
- **4 number controls** — max charging current, stop charge timer, discharge/charge limits
- **Dynamic MQTT** — endpoint auto-discovered from the API with fallback, fixing connectivity across regions
- **Write protection** — every register write validated against a safety whitelist
- **Auto-reconnection** — exponential backoff with connection verification
- **Per-device Modbus addressing** — extracted from API, not hardcoded

## Supported Devices

Compatible with power stations that use the **BrightEMS** app. All these brands share the same **SYDPOWER** platform:

| Brand | Models | Evidence |
|-------|--------|----------|
| **FOSSiBOT** | F2400, F3600, F3600 Pro, F1200 | Uses BrightEMS app, confirmed by multiple GitHub reverse-engineering projects |
| **AFERIY** | P210, P310 | Uses BrightEMS app, identical specs to Fossibot F2400/F3600 |
| **Eco Play (ECOPLAY)** | SYD2400, SYD3600, 3600 Pro | Literally uses "SYD" in model names, uses BrightEMS app, expansion battery called "SYD3600-Extra" |
| **ABOK Power** | Ark3600 | Uses BrightEMS app, listed as compatible in ESP-FBot project |

### Model cross-reference (SYDPOWER internal model -> brand equivalents)

- **SYDPOWER N052** (2400W/2048Wh) -> FOSSiBOT F2400 -> AFERIY P210 -> Eco Play SYD2400
- **SYDPOWER N051/N066** (3600W/3840Wh) -> FOSSiBOT F3600 Pro -> AFERIY P310 -> Eco Play SYD3600 -> ABOK Ark3600

If your BrightEMS-compatible model is not listed, please report your results on Discord or GitHub Issues.

## Installation

### HACS (recommended)

1. Open **HACS** > **Integrations** > **Custom Repositories**
2. Add `https://github.com/iamslan/fossibot` as an **Integration**
3. Search for **Fossibot** and install it
4. Restart Home Assistant

### Manual

1. Download this repository
2. Copy the `custom_components/fossibot-ha` folder to `<config>/custom_components/fossibot-ha`
3. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **+ Add Integration** and search for **Fossibot**
3. Enter your BrightEMS app credentials (username and password)
4. Click Submit

The integration will authenticate, discover your devices, and create all entities automatically.

## Entities

### Sensors (read-only)

| Entity | Unit | Description |
|--------|------|-------------|
| State of Charge | % | Main battery SoC |
| State of Charge Slave 1 | % | Expansion battery 1 SoC |
| State of Charge Slave 2 | % | Expansion battery 2 SoC |
| DC Input | W | Solar / DC input power |
| Total Input | W | Combined input power |
| AC Charging Rate | — | Current AC charging rate knob position |
| Total Output | W | Combined output power |
| AC Output Voltage | V | AC output voltage |
| AC Output Frequency | Hz | AC output frequency |
| AC Input Voltage | V | AC input voltage |
| AC Input Frequency | Hz | AC input frequency |

### Switches (on/off)

| Entity | Description |
|--------|-------------|
| USB Output | Toggle USB ports |
| DC Output | Toggle DC output |
| AC Output | Toggle AC inverter |
| AC Silent Charging | Toggle silent charging mode |

### Selects (dropdown)

| Entity | Options |
|--------|---------|
| LED Mode | Off, On, SOS, Flash |
| USB Standby Time | Off, 3 min, 5 min, 10 min, 30 min |
| AC Standby Time | Off, 8 hours, 16 hours, 24 hours |
| DC Standby Time | Off, 8 hours, 16 hours, 24 hours |
| Screen Rest Time | Off, 3 min, 5 min, 10 min, 30 min |
| Sleep Time | 5 min, 10 min, 30 min, 8 hours |

### Numbers (slider / input)

| Entity | Range | Unit | Description |
|--------|-------|------|-------------|
| Maximum Charging Current | 1–20 | A | AC charging current limit |
| Stop Charge After | 0–1440 | min | Auto-stop charging timer (0 = off) |
| Discharge Lower Limit | 0–100 | % | Minimum SoC before output cutoff |
| AC Charging Upper Limit | 0–100 | % | Maximum SoC to charge to |

## Architecture

```
custom_components/fossibot-ha/
  __init__.py          # Integration setup, platform loading
  config_flow.py       # UI-based configuration
  coordinator.py       # DataUpdateCoordinator (polling loop)
  entity.py            # FossibotEntity base class
  sensor.py            # 11 sensor entities (data-driven)
  switch.py            # 4 switch entities (data-driven)
  select.py            # 6 select entities (data-driven)
  number.py            # 4 number entities (data-driven)
  sydpower/
    api_client.py      # REST API (auth, MQTT token, device list)
    mqtt_client.py     # MQTT over WebSocket (paho-mqtt)
    connector.py       # Connection orchestration + fallback
    modbus.py          # Modbus encoding, CRC-16, safety validation
    const.py           # Endpoints, register addresses
    logger.py          # Rate-limited smart logger
```

**Key design decisions:**
- All entity definitions are data-driven (lists of dicts) — no per-entity boilerplate
- `WRITABLE_REGISTERS` safety map in `modbus.py` defines the exact set of allowed values per register, preventing accidental writes that could brick a device
- MQTT host is discovered from the API at runtime with a hardcoded fallback, so the integration works across all regions
- Per-device `modbus_address` is extracted from the API rather than assumed

## Debugging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.fossibot: debug
```

### Standalone discovery script

For debugging MQTT connectivity without Home Assistant:

```bash
pip install aiohttp paho-mqtt
python scripts/discover_mqtt.py <username> <password>
```

This dumps all API responses and tests MQTT connectivity against both the API-provided and fallback hosts.

## Limitations

- Requires internet — this is a cloud-based integration
- Depends on the Fossibot/Sydpower cloud service being operational
- API may change without notice (reverse-engineered endpoints)
- Slave battery SoC sensors only appear when expansion batteries are connected and report non-zero values

## Local / LAN Mode

Want to keep MQTT traffic on your local network? You can redirect the battery's MQTT connection to a self-hosted EMQX broker on Home Assistant using a DNS rewrite. See the **[Local MQTT Guide](docs/LOCAL_MQTT.md)** for step-by-step instructions.

## Contributing

Contributions are welcome — both issues and pull requests. If you have a Fossibot model not listed above, running the discovery script and sharing the (redacted) output helps a lot.

## Credits

Created by [@iamslan](https://github.com/iamslan) and [@alessandro-lac](https://github.com/alessandro-lac), based on reverse engineering the BrightEMS app's communication patterns.

## License

[MIT](LICENSE)
