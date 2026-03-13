# EMQX Setup Guide for Home Assistant

Step-by-step guide to set up EMQX as your local MQTT broker for the Fossibot integration (v2.0.0+).

> **Why EMQX?** — The BrightEMS app sends MQTT credentials that standard brokers like Mosquitto may reject. EMQX handles anonymous/pass-through authentication out of the box and is available as a Home Assistant add-on.

---

## Prerequisites

- Home Assistant with **Supervisor** (HAOS or Supervised install)
- **BrightEMS** app version **1.6.0** or later
- Battery and Home Assistant on the **same network**
- A **static IP** for your Home Assistant machine (e.g., `192.168.1.10`)

---

## Step 1: Install the EMQX Add-on

1. In Home Assistant, go to **Settings** > **Add-ons** > **Add-on Store**
2. Click the **three dots** (top right) > **Repositories**
3. Add the EMQX community repository if not already present:
   ```
   https://github.com/hassio-addons/repository
   ```
4. Search for **EMQX** and click **Install**
5. Once installed, go to the add-on **Configuration** tab
6. Start the add-on and enable **Start on boot** and **Watchdog**

---

## Step 2: Configure EMQX

### Open the Dashboard

1. Open the EMQX web dashboard at `http://<HA_IP>:18083`
2. Default credentials: `admin` / `public`
3. **Change the admin password** on first login

### Verify the TCP Listener (port 1883)

The Fossibot integration connects via **plain TCP MQTT on port 1883**. EMQX enables this by default, but verify:

1. Go to **Management** > **Listeners**
2. Confirm the **tcp:default** listener exists and is bound to `0.0.0.0:1883`
3. If missing, click **Add Listener**:
   - **Type**: `tcp`
   - **Name**: `default`
   - **Bind**: `0.0.0.0:1883`

### Allow Anonymous Connections

The battery authenticates with a platform-issued token that EMQX cannot validate locally. Allow anonymous access:

1. Go to **Access Control** > **Authentication**
2. Make sure **no authentication backends** are configured, **or** enable **Allow Anonymous**

> **Security note** — This means any device on your LAN can publish to EMQX. This is fine for a home network. If you need stricter control, create a username/password in EMQX and enter it in the integration config.

---

## Step 3: Configure BrightEMS App

1. Open the **BrightEMS** app (v1.6.0+) on your phone
2. Go to **Me** > **Settings** > **Local MQTT Broker Settings**
3. Enter your Home Assistant IP address (e.g., `192.168.1.10`)
4. Copy your **API Token** from this screen — you'll need it for the integration
5. Tap **Save**

> **Important:** Only the **master account** (the first user who bound the device) can configure MQTT settings. If you share the device with other accounts, the master must set this up.

After saving, the battery will start sending MQTT traffic to your local broker instead of the cloud. You can verify this in the EMQX dashboard under **Monitoring** > **Clients** — the battery should appear as a connected client within a few seconds.

---

## Step 4: Add the Integration in Home Assistant

1. Go to **Settings** > **Devices & Services**
2. Click **+ Add Integration** and search for **Fossibot**
3. Enter:
   - **API Token** — the token from BrightEMS app settings
   - **MQTT Broker Host** — your Home Assistant IP (e.g., `192.168.1.10`)
   - **MQTT Broker Port** — `1883` (default)
   - **MQTT Username** — leave empty if using anonymous auth
4. Click **Submit**

The integration will fetch your device list via the API, connect to EMQX, and create all entities automatically.

---

## Step 5: Verify Everything Works

### EMQX Dashboard

1. Open `http://<HA_IP>:18083` > **Monitoring** > **Clients**
2. You should see **two clients**: one from the battery, one from the Fossibot integration
3. Go to **Subscriptions** and confirm topics like `{device_mac}/device/response/state` are active

### Home Assistant

1. Go to **Settings** > **Devices & Services** > **Fossibot**
2. Open your device — sensor values (SoC, input/output power) should be updating
3. Toggle a switch (e.g., USB Output) to confirm two-way communication works

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Battery not appearing in EMQX clients | Confirm the IP in BrightEMS is correct. Reboot the battery after changing MQTT settings. Check that port 1883 is not blocked by a firewall |
| Integration says "cannot connect" | Verify EMQX is running and the TCP listener is on port 1883. Try `telnet <HA_IP> 1883` from another device |
| Battery connects but entities show "unavailable" | Check EMQX dashboard for message activity. The battery may need a power cycle after switching from cloud to local MQTT |
| Only cached/stale values, no updates | Ensure the battery is on the same network as HA. Check EMQX **Monitoring** > **Messages** for incoming publishes |
| "Authentication failed" in logs | Enable anonymous auth in EMQX, or create matching credentials in both EMQX and the integration config |
| EMQX add-on won't start | Check the add-on logs. Port 1883 may be in use by another MQTT broker (e.g., Mosquitto). Stop the other broker first |

---

## Using Mosquitto Instead of EMQX

If you prefer Mosquitto, it works too — just make sure to configure it to accept anonymous connections or create credentials that match what you enter in the integration:

1. Install the **Mosquitto broker** add-on
2. In the Mosquitto config, set `allow_anonymous: true` or create a user
3. Use the same broker IP and port when configuring the integration

The key difference is that EMQX accepts any credentials by default, while Mosquitto requires explicit configuration for anonymous access.

---

## FAQ

**Q: Does this replace the cloud connection entirely?**
A: MQTT traffic is fully local. However, the integration still calls `api.app.sydpower.com` to fetch your device list and sync online/offline state. Internet is required for initial setup and device discovery.

**Q: Can I use the HA Mosquitto add-on I already have?**
A: Yes! Any MQTT broker that accepts TCP connections on port 1883 works. See the Mosquitto section above.

**Q: Do I need AdGuard / DNS rewriting?**
A: No. That was needed in v1.x where the battery firmware always connected to the cloud. In v2.0.0+, the BrightEMS app natively directs the battery to your local broker.

**Q: What happens if my broker goes down?**
A: The integration will automatically reconnect with exponential backoff when the broker comes back. The battery firmware also reconnects automatically.
