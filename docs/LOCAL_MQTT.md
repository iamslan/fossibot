# Local MQTT Guide (LAN Mode)

Keep your Fossibot battery's MQTT data traffic entirely on your local network by redirecting DNS to a self-hosted EMQX broker on Home Assistant.

> **Note** — The REST API (`api.sydpower.com`) is still used for authentication and device discovery. Only the high-frequency MQTT data stream stays local.

---

## How It Works

```
┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
│   Battery    │──DNS──▶ │  AdGuard Home    │         │  HA + EMQX   │
│  (Fossibot)  │         │  DNS rewrite:    │         │  192.168.1.10│
│              │         │  mqtt.sydpower   │──────▶  │  port 8083   │
│              │────────────────MQTT─────────────────▶ │  /mqtt (WS)  │
└─────────────┘         └──────────────────┘         └──────────────┘
```

1. The battery firmware connects to `mqtt.sydpower.com` on port **8083** (MQTT over WebSocket)
2. **AdGuard Home** rewrites the DNS so `mqtt.sydpower.com` resolves to your Home Assistant IP
3. **EMQX** on Home Assistant accepts the connection on port 8083
4. The Fossibot HA integration also resolves to the local EMQX — both sides communicate locally

---

## Prerequisites

- Home Assistant with **Supervisor** (HAOS or Supervised install)
- A **static IP** for your Home Assistant machine (e.g., `192.168.1.10`)
- The battery and Home Assistant on the **same LAN**

---

## Step 1: Install & Configure EMQX

1. In Home Assistant, go to **Settings** > **Add-ons** > **Add-on Store**
2. Search for **EMQX** and install it
3. Start the add-on and open the **EMQX Dashboard** (default: `http://<HA_IP>:18083`)
4. Log in with the default credentials (`admin` / `public`) and change the password

### Configure WebSocket Listener

The battery connects via **MQTT over WebSocket** on port **8083** with path `/mqtt`. EMQX includes a default WebSocket listener on port 8083 — verify it is enabled:

1. Go to **Management** > **Listeners** in the EMQX Dashboard
2. Confirm the **ws:default** listener exists on port `8083`
3. If not, create a new WebSocket listener:
   - **Type**: `ws` (WebSocket)
   - **Bind**: `0.0.0.0:8083`

### Enable Anonymous Authentication

The battery authenticates with a cloud-issued token that EMQX cannot verify. Enable anonymous access so EMQX accepts any credentials:

1. Go to **Access Control** > **Authentication** in the EMQX Dashboard
2. Make sure **no authentication backends** are configured, or enable the **Allow Anonymous** option

> **Security note** — Anonymous access means any device on your LAN can connect to EMQX. This is acceptable for a home network but not recommended for shared/public networks.

---

## Step 2: Install & Configure AdGuard Home

1. In Home Assistant, go to **Settings** > **Add-ons** > **Add-on Store**
2. Search for **AdGuard Home** and install it
3. Start the add-on and open the AdGuard Home web UI
4. Complete the initial setup wizard

### Add DNS Rewrite

1. Go to **Filters** > **DNS rewrites**
2. Click **Add DNS rewrite** and enter:
   - **Domain**: `mqtt.sydpower.com`
   - **Answer**: `192.168.1.10` *(replace with your HA IP)*
3. Save

This tells AdGuard to resolve `mqtt.sydpower.com` to your local Home Assistant instead of the cloud server.

---

## Step 3: Configure Your Router's DHCP

For the DNS rewrite to work, all devices on your network (including the battery) must use AdGuard Home as their DNS server.

1. Open your **router's admin panel**
2. Find the **DHCP settings** (usually under LAN or Network)
3. Set the **primary DNS server** to your AdGuard Home IP (same as your HA IP, e.g., `192.168.1.10`)
4. Save and apply

> **Tip** — After changing DHCP DNS, devices pick up the new setting when they renew their lease. You can speed this up by rebooting the battery (turn it off and on).

---

## Step 4: Verify

### Check EMQX Dashboard

1. Open the EMQX Dashboard (`http://<HA_IP>:18083`)
2. Go to **Monitoring** > **Clients**
3. You should see connected clients — one from the battery and one from the Fossibot HA integration
4. Check **Subscriptions** to confirm topics like `{device_mac}/device/response/state` are active

### Check Home Assistant

1. Go to **Settings** > **Devices & Services** > **Fossibot**
2. Open your device — sensor values should be updating normally
3. Toggle a switch (e.g., USB Output) and confirm it works

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Battery not connecting to EMQX | Verify DNS rewrite is active. Run `nslookup mqtt.sydpower.com` from a device using AdGuard as DNS — it should return your HA IP |
| EMQX shows no clients | Check the WebSocket listener is on port `8083`. Check the battery is on the same network and using AdGuard as DNS |
| HA integration not connecting | Restart the Fossibot integration after setting up DNS. It re-resolves the MQTT host on each connection attempt |
| Entities not updating | Check EMQX dashboard for message activity. Ensure anonymous auth is enabled |
| Cloud API calls failing | The DNS rewrite should only affect `mqtt.sydpower.com`, not `api.sydpower.com`. Verify AdGuard only has the MQTT rewrite |

---

## Caveats

- **Internet is still required** for initial authentication and device discovery (REST API)
- **Only MQTT traffic is local** — the integration still calls `api.sydpower.com` for tokens and device lists
- If the battery firmware updates its MQTT hostname, you may need to add additional DNS rewrites
- This setup has been tested with the Fossibot F2400 and F3600 Pro — other models should work identically
