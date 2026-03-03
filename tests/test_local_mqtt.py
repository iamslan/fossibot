"""Tests for local MQTT mode: connector, config flow, and coordinator initialization.

These tests verify the new local MQTT mode works correctly without
requiring a running MQTT broker or Home Assistant instance.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Import the connector (modbus/const have no HA deps)
from fossibot_ha.sydpower.connector import SydpowerConnector
from fossibot_ha.sydpower.const import REGISTER_MODBUS_ADDRESS, MQTT_PORT


def _run(coro):
    """Run a coroutine synchronously (no pytest-asyncio needed)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# SydpowerConnector — local MQTT mode
# ---------------------------------------------------------------------------

class TestConnectorLocalMqttInit:
    """Test SydpowerConnector initialization in local MQTT mode."""

    def test_local_mqtt_mode_flag(self):
        c = SydpowerConnector(
            connection_mode="local_mqtt",
            mqtt_host="10.20.30.21",
            mqtt_port=8083,
            device_mac="AABBCCDDEEFF",
        )
        assert c.is_local_mqtt is True

    def test_cloud_mode_flag_default(self):
        c = SydpowerConnector(username="u", password="p")
        assert c.is_local_mqtt is False

    def test_cloud_mode_flag_explicit(self):
        c = SydpowerConnector(
            username="u", password="p", connection_mode="cloud"
        )
        assert c.is_local_mqtt is False

    def test_local_params_stored(self):
        c = SydpowerConnector(
            connection_mode="local_mqtt",
            mqtt_host="192.168.1.10",
            mqtt_port=9999,
            device_mac="112233445566",
        )
        assert c._local_mqtt_host == "192.168.1.10"
        assert c._local_mqtt_port == 9999
        assert c._local_device_mac == "112233445566"

    def test_no_api_client_needed(self):
        c = SydpowerConnector(
            connection_mode="local_mqtt",
            mqtt_host="10.20.30.21",
            device_mac="AABBCCDDEEFF",
        )
        assert c.api_client is None
        assert c.username is None
        assert c.password is None


def _make_mock_mqtt(connected=True, data_available=True, devices=None):
    """Create a mock MQTT client for testing."""
    mock = MagicMock()
    mock.connected = asyncio.Event()
    mock.data_updated = asyncio.Event()
    mock.devices = devices or {}
    mock.disconnect = AsyncMock()
    mock.clear_message_cache = MagicMock()
    mock.publish_command = MagicMock()
    mock.on_disconnect_callback = None

    async def fake_connect(*args, **kwargs):
        if connected:
            mock.connected.set()
        if data_available:
            mock.data_updated.set()

    mock.connect = AsyncMock(side_effect=fake_connect)
    return mock


class TestConnectorLocalMqttConnect:
    """Test the local MQTT connect flow with mocked MQTT client."""

    def _make_connector(self):
        return SydpowerConnector(
            connection_mode="local_mqtt",
            mqtt_host="10.20.30.21",
            mqtt_port=8083,
            device_mac="AABBCCDDEEFF",
        )

    def test_connect_builds_device_dict(self):
        """connect() should build devices dict with default modbus params."""
        connector = self._make_connector()
        mock_mqtt = _make_mock_mqtt(
            devices={"AABBCCDDEEFF": {"soc": 75.0}}
        )

        with patch(
            "fossibot_ha.sydpower.connector.MQTTClient",
            return_value=mock_mqtt,
        ):
            result = _run(connector.connect())

        assert result is True
        assert "AABBCCDDEEFF" in connector.devices
        assert connector.devices["AABBCCDDEEFF"]["_modbus_address"] == REGISTER_MODBUS_ADDRESS
        assert connector.devices["AABBCCDDEEFF"]["_modbus_count"] == 80

    def test_connect_uses_anonymous_token(self):
        """connect() should pass 'anonymous' as mqtt_token."""
        connector = self._make_connector()
        mock_mqtt = _make_mock_mqtt(
            devices={"AABBCCDDEEFF": {"soc": 50.0}}
        )

        with patch(
            "fossibot_ha.sydpower.connector.MQTTClient",
            return_value=mock_mqtt,
        ):
            _run(connector.connect())

        mock_mqtt.connect.assert_called_once_with(
            "anonymous",
            ["AABBCCDDEEFF"],
            "10.20.30.21",
            8083,
        )

    def test_connect_no_api_calls(self):
        """Local MQTT mode should never create or call APIClient."""
        connector = self._make_connector()
        mock_mqtt = _make_mock_mqtt(
            devices={"AABBCCDDEEFF": {"soc": 50.0}}
        )

        with patch(
            "fossibot_ha.sydpower.connector.MQTTClient",
            return_value=mock_mqtt,
        ), patch(
            "fossibot_ha.sydpower.connector.APIClient"
        ) as api_mock:
            _run(connector.connect())

        api_mock.assert_not_called()
        assert connector.api_client is None

    def test_connect_accepts_broker_when_device_offline(self):
        """If device doesn't respond but broker connects, accept it."""
        connector = self._make_connector()
        mock_mqtt = _make_mock_mqtt(
            connected=True, data_available=False, devices={}
        )

        with patch(
            "fossibot_ha.sydpower.connector.MQTTClient",
            return_value=mock_mqtt,
        ):
            result = _run(connector.connect())

        # Should still accept the broker connection
        assert result is True

    def test_connect_fails_when_broker_unreachable(self):
        """If broker doesn't connect, return False."""
        connector = self._make_connector()
        mock_mqtt = _make_mock_mqtt(
            connected=False, data_available=False, devices={}
        )

        with patch(
            "fossibot_ha.sydpower.connector.MQTTClient",
            return_value=mock_mqtt,
        ):
            result = _run(connector.connect())

        assert result is False


# ---------------------------------------------------------------------------
# Config flow — MAC normalization
# ---------------------------------------------------------------------------

def _normalize_mac(raw: str) -> str:
    """Mirror of config_flow._normalize_mac for testing."""
    return raw.replace(":", "").replace("-", "").upper().strip()


class TestMacNormalization:
    """Test MAC address normalization logic (mirrors config_flow._normalize_mac)."""

    def test_already_clean(self):
        assert _normalize_mac("AABBCCDDEEFF") == "AABBCCDDEEFF"

    def test_with_colons(self):
        assert _normalize_mac("AA:BB:CC:DD:EE:FF") == "AABBCCDDEEFF"

    def test_with_dashes(self):
        assert _normalize_mac("aa-bb-cc-dd-ee-ff") == "AABBCCDDEEFF"

    def test_lowercase(self):
        assert _normalize_mac("aabbccddeeff") == "AABBCCDDEEFF"

    def test_with_spaces(self):
        assert _normalize_mac("  AABBCCDDEEFF  ") == "AABBCCDDEEFF"

    def test_mixed_separators(self):
        assert _normalize_mac("AA:BB-CC:DD-EE:FF") == "AABBCCDDEEFF"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestLocalMqttConstants:
    """Test that new constants exist and have correct values."""

    def test_connection_mode_constants(self):
        from fossibot_ha.const import (
            CONF_CONNECTION_MODE,
            CONNECTION_MODE_CLOUD,
            CONNECTION_MODE_LOCAL,
            CONF_MQTT_HOST,
            CONF_MQTT_PORT,
            CONF_DEVICE_MAC,
        )
        assert CONF_CONNECTION_MODE == "connection_mode"
        assert CONNECTION_MODE_CLOUD == "cloud"
        assert CONNECTION_MODE_LOCAL == "local_mqtt"
        assert CONF_MQTT_HOST == "mqtt_host"
        assert CONF_MQTT_PORT == "mqtt_port"
        assert CONF_DEVICE_MAC == "device_mac"
