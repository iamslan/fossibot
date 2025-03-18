# Fossibot Home Assistant Integration

A custom integration for Home Assistant that allows you to monitor and control your Fossibot power stations.

## ⚠️ Disclaimer

This integration is **unofficial** and not affiliated with or endorsed by Fossibot, Sydpower, or BrightEMS. 

**USE AT YOUR OWN RISK.** The author is not responsible for any damage to your devices, loss of data, or any other issues that may arise from using this integration. This is provided as-is with no warranty or guarantees of any kind.

This integration accesses the Fossibot cloud API and sends commands to your devices. While every effort has been made to ensure safe operation, unforeseen issues could potentially affect your device's functionality or firmware.

**Status:** This project is a new implementation of a relatively new API. Consider this code alpha.

Contributions are welcomed, both as issues, but more as pull requests :)

Please [join our Discord](https://discord.gg/NN6R5QNb) and help development by providing feedback and details about the batteries you are using.


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
- Fossibot F3600 Pro

## Installation
You can manually install this integration as an custom_component under Home Assistant or install it using HACS (Home Assistant Community Store).

### Manual installation
1. **Download** the `fossibot-ha` repository or folder.
2. **Copy** the `custom_components/fossibot-ha` folder from the downloaded files.
3. **Paste** the `fossibot-ha` folder into your Home Assistant's custom components directory:
   - Path: `<home_assistant_folder>/custom_components/fossibot-ha`
4. **Restart** Home Assistant to load the new integration.

### HACS installation
The `fossibot-ha` repository is also compatible with HACS (Home Assistant Community Store), making installation and updates easier.

1. **Install HACS** (if not already installed):
   - Follow instructions here: [HACS Installation Guide](https://hacs.xyz/docs/use/download/download/#to-download-hacs)
2. **Add `fossibot-ha` Repository** to HACS:
   - In Home Assistant, go to **HACS** > **Settings** tab.
   - Select **Custom Repositories** and add the repository URL `https://github.com/iamslan/fossibot-ha`.
3. **Install `fossibot-ha`** from HACS:
   - After adding the repository, find and install `fossibot-ha` under the HACS integrations.
4. **Restart** Home Assistant.

Following these steps should successfully install the `fossibot-ha` integration for use with your Home Assistant setup.

For more guidance on HACS, you can refer to the [HACS Getting Started Guide](https://hacs.xyz/docs/use/).

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
