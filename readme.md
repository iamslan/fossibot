# Fossibot Home Assistant Integration

A custom integration for Home Assistant that allows you to monitor and control your Fossibot power stations.

## ⚠️ Disclaimer

This integration is **unofficial** and not affiliated with or endorsed by Fossibot, Sydpower, or BrightEMS. 

**USE AT YOUR OWN RISK.** The author is not responsible for any damage to your devices, loss of data, or any other issues that may arise from using this integration. This is provided as-is with no warranty or guarantees of any kind.

This integration accesses the Fossibot cloud API and sends commands to your devices. While every effort has been made to ensure safe operation, unforeseen issues could potentially affect your device's functionality or firmware.

## Important Note on API Access

This integration accesses the Fossibot/BrightEMS cloud API using reverse-engineered API endpoints and authentication methods. Before using this integration:

1. Be aware that this might violate the Terms of Service of Fossibot/BrightEMS
2. The API could change at any time, potentially breaking this integration
3. API credentials and endpoints are included in the code for functionality

## Features

- **Monitor power station status**: Battery level, power input/output, and more
- **Control outputs**: Toggle USB, DC, AC, and LED outputs
- **Automatic reconnection**: Robust error handling and connection recovery
- **Regular updates**: Polls the Fossibot cloud API to keep data current

## Supported Devices

This integration should work with Fossibot/Sydpower power stations compatible with the BrightEMS app. It has been tested with:

- Fossibot F2400

## Installation


### Manual Installation

1. Copy the `fossibot` directory from this project into your Home Assistant's `custom_components` directory. If you don't have a `custom_components` directory, create one in your Home Assistant configuration directory.
2. Restart Home Assistant

## Configuration

After installation, you can add the integration through the Home Assistant UI:

1. Go to **Configuration** → **Devices & Services**
2. Click the **+ ADD INTEGRATION** button in the bottom right
3. Search for "Fossibot" and select it
4. Enter your BrightEMS/Fossibot app credentials (username and password)
5. Click Submit

## Entities Created

For each Fossibot power station, the following entities will be created:

### Sensors
- Battery State of Charge (%)
- DC Input Power (W)
- Total Input Power (W)
- Total Output Power (W)
- _(Additional sensors may be created based on device capabilities)_

### Switches
- USB Output
- DC Output
- AC Output
- LED Light

## Debugging

If you encounter issues with the integration, you can enable debug logging by adding the following to your `configuration.yaml` file:

```yaml
logger:
  default: info
  logs:
    custom_components.fossibot: debug
```

After restarting Home Assistant, detailed logs will be available in the Home Assistant log file.

## Development

This integration uses:
- Home Assistant's `DataUpdateCoordinator` for efficient data polling
- Async MQTT over WebSockets for real-time device communication
- REST API for authentication
- Modbus-style commands for device control

The code employs a modular approach with separate components for API client, MQTT handler, and device command processing.

## Limitations

- Requires internet connectivity to work (cloud-based)
- Depends on the Fossibot/Sydpower cloud service being operational
- May be affected by changes to the Fossibot API or app
- Authentication tokens may expire periodically, requiring reconnection

## Credits

This integration was created by leveraging code developed by iamslan, based on analyzing the BrightEMS app's communication patterns. The original reverse engineering work and analysis of the API was performed by iamslan.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
