import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import (
    app,
    discover_network_interfaces,
    validate_network_interface,
    build_ping_command,
)


@pytest.fixture
def client():
    return TestClient(app)


class TestNetworkInterfaceDiscovery:
    def test_discover_interfaces_structure(self):
        result = discover_network_interfaces()
        assert isinstance(result, dict)
        assert "supported" in result
        assert "interfaces" in result
        assert "selected" in result
        assert result["selected"] == "auto"

        # The first interface should always be the Automatic default
        assert len(result["interfaces"]) >= 1
        default_iface = result["interfaces"][0]
        assert default_iface["id"] == "auto"
        assert default_iface["is_default"] is True
        assert default_iface["status"] == "active"

    @patch("platform.system", return_value="Linux")
    @patch("socket.if_nameindex", return_value=[(1, "lo"), (2, "eth0"), (3, "wlan0")])
    def test_discover_interfaces_linux(self, mock_if, mock_sys):
        result = discover_network_interfaces()
        assert result["supported"] is True
        ids = [item["id"] for item in result["interfaces"]]
        assert "auto" in ids
        assert "eth0" in ids
        assert "wlan0" in ids
        assert "lo" not in ids  # loopback excluded

    @patch("platform.system", return_value="CustomOS")
    def test_discover_interfaces_unsupported_fallback(self, mock_sys):
        with patch("socket.if_nameindex", side_effect=AttributeError):
            result = discover_network_interfaces()
            assert result["supported"] is False
            assert result["selected"] == "auto"
            assert len(result["interfaces"]) == 1
            assert result["interfaces"][0]["id"] == "auto"


class TestNetworkInterfaceValidation:
    def test_validate_default_and_none(self):
        assert validate_network_interface(None) == "auto"
        assert validate_network_interface("") == "auto"
        assert validate_network_interface("auto") == "auto"
        assert validate_network_interface("default") == "auto"

    @patch("backend.main.discover_network_interfaces")
    def test_validate_valid_interface(self, mock_discover):
        mock_discover.return_value = {
            "supported": True,
            "interfaces": [
                {"id": "auto", "name": "Automatic", "status": "active", "is_default": True},
                {"id": "eth0", "name": "eth0", "status": "connected", "is_default": False},
            ],
            "selected": "auto",
        }
        assert validate_network_interface("eth0") == "eth0"
        assert validate_network_interface("ETH0") == "eth0"  # case-insensitive match

    @patch("backend.main.discover_network_interfaces")
    def test_validate_disconnected_interface(self, mock_discover):
        mock_discover.return_value = {
            "supported": True,
            "interfaces": [
                {"id": "auto", "name": "Automatic", "status": "active", "is_default": True},
                {"id": "eth1", "name": "eth1", "status": "disconnected", "is_default": False},
            ],
            "selected": "auto",
        }
        with pytest.raises(HTTPException) as exc_info:
            validate_network_interface("eth1")
        assert exc_info.value.status_code == 400
        assert "disconnected" in exc_info.value.detail.lower()

    @patch("backend.main.discover_network_interfaces")
    def test_validate_nonexistent_interface(self, mock_discover):
        mock_discover.return_value = {
            "supported": True,
            "interfaces": [
                {"id": "auto", "name": "Automatic", "status": "active", "is_default": True},
                {"id": "eth0", "name": "eth0", "status": "connected", "is_default": False},
            ],
            "selected": "auto",
        }
        with pytest.raises(HTTPException) as exc_info:
            validate_network_interface("nonexistent_adapter_xyz")
        assert exc_info.value.status_code == 400
        assert "invalid or does not exist" in exc_info.value.detail.lower()

    @patch("backend.main.discover_network_interfaces")
    def test_validate_fallback_on_unsupported_platform(self, mock_discover):
        mock_discover.return_value = {
            "supported": False,
            "interfaces": [{"id": "auto", "name": "Automatic", "status": "active", "is_default": True}],
            "selected": "auto",
        }
        # Unsupported platforms fall back safely to auto
        assert validate_network_interface("any_interface") == "auto"


class TestBuildPingCommandWithInterface:
    def test_command_without_interface(self):
        cmd_win = build_ping_command("1.1.1.1", 4, 2, "Windows")
        assert "-n" in cmd_win
        assert "1.1.1.1" in cmd_win

        cmd_linux = build_ping_command("1.1.1.1", 4, 2, "Linux")
        assert "-c" in cmd_linux
        assert "-I" not in cmd_linux

        cmd_darwin = build_ping_command("1.1.1.1", 4, 2, "Darwin")
        assert "-c" in cmd_darwin
        assert "-I" not in cmd_darwin

    def test_command_with_interface_linux(self):
        cmd = build_ping_command("1.1.1.1", 4, 2, "Linux", interface="eth0")
        assert "-I" in cmd
        idx = cmd.index("-I")
        assert cmd[idx + 1] == "eth0"
        assert cmd[-1] == "1.1.1.1"

    def test_command_with_interface_darwin(self):
        cmd = build_ping_command("1.1.1.1", 4, 2, "Darwin", interface="en0")
        assert "-I" in cmd
        idx = cmd.index("-I")
        assert cmd[idx + 1] == "en0"
        assert cmd[-1] == "1.1.1.1"

    def test_command_auto_interface_omits_flag(self):
        cmd = build_ping_command("1.1.1.1", 4, 2, "Linux", interface="auto")
        assert "-I" not in cmd


class TestNetworkInterfaceApiEndpoints:
    def test_get_network_interfaces_endpoint(self, client):
        response = client.get("/api/network-interfaces")
        assert response.status_code == 200
        data = response.json()
        assert "supported" in data
        assert "interfaces" in data
        assert isinstance(data["interfaces"], list)
        assert len(data["interfaces"]) >= 1

    @patch("backend.main.validate_network_interface")
    @patch("backend.main.subprocess.run")
    def test_network_quality_with_interface(self, mock_run, mock_val, client):
        mock_val.return_value = "eth0"
        mock_process = MagicMock()
        mock_process.stdout = "Reply from 1.1.1.1: bytes=32 time=15ms TTL=58\nReply from 1.1.1.1: bytes=32 time=16ms TTL=58\nPackets: Sent = 2, Received = 2, Lost = 0 (0% loss)"
        mock_run.return_value = mock_process

        response = client.get("/api/network-quality?interface=eth0")
        assert response.status_code == 200
        data = response.json()
        assert data["interface"] == "eth0"

    def test_network_quality_invalid_interface_returns_400(self, client):
        response = client.get("/api/network-quality?interface=completely_invalid_adapter_999")
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "invalid or does not exist" in data["detail"].lower()
