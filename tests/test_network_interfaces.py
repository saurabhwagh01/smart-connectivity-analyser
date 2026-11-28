import socket
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.main as main


def _ipv4(value):
    return SimpleNamespace(family=socket.AF_INET, address=value)


def _install_snapshot(monkeypatch, *, system="Linux", adapters=None):
    adapters = adapters or {
        "eth0": {
            "up": True,
            "addresses": [_ipv4("192.168.10.20")],
        },
    }

    class FakePsutil:
        @staticmethod
        def net_if_stats():
            return {
                name: SimpleNamespace(isup=details["up"])
                for name, details in adapters.items()
            }

        @staticmethod
        def net_if_addrs():
            return {
                name: details["addresses"]
                for name, details in adapters.items()
            }

    monkeypatch.setattr(main.platform, "system", lambda: system)
    monkeypatch.setattr(main, "psutil", FakePsutil)


def _fake_ping(monkeypatch, stdout):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    return commands


LINUX_OUTPUT = """
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.4 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.9 ms
4 packets transmitted, 2 received, 50% packet loss
"""


def test_discovery_returns_auto_and_only_minimal_interface_metadata(monkeypatch):
    _install_snapshot(
        monkeypatch,
        adapters={
            "lo": {"up": True, "addresses": [_ipv4("127.0.0.1")]},
            "eth0": {"up": True, "addresses": [_ipv4("192.168.10.20")]},
            "wlan0": {"up": False, "addresses": [_ipv4("192.168.20.30")]},
            "veth-no-ipv4": {"up": True, "addresses": []},
        },
    )

    result = main.discover_network_interfaces()

    assert result["supported"] is True
    assert result["selected"] == "auto"
    assert result["interfaces"][0]["id"] == "auto"
    assert [item["id"] for item in result["interfaces"]] == ["auto", "eth0", "wlan0"]
    assert result["interfaces"][1]["status"] == "connected"
    assert result["interfaces"][2]["status"] == "disconnected"
    assert all("address" not in item and "mac" not in item for item in result["interfaces"])


def test_windows_discovery_falls_back_to_automatic(monkeypatch):
    _install_snapshot(monkeypatch, system="Windows")

    result = main.discover_network_interfaces()

    assert result == {
        "supported": False,
        "interfaces": [{
            "id": "auto",
            "name": "Automatic (System default)",
            "status": "active",
            "is_default": True,
        }],
        "selected": "auto",
    }


def test_automatic_mode_does_not_require_discovery():
    assert main.validate_network_interface(None) == "auto"
    assert main.validate_network_interface("") == "auto"
    assert main.validate_network_interface("auto") == "auto"
    assert main.validate_network_interface("default") == "auto"


def test_invalid_interface_is_rejected(monkeypatch):
    _install_snapshot(monkeypatch)

    with pytest.raises(HTTPException) as error:
        main.validate_network_interface("missing0")

    assert error.value.status_code == 400
    assert "no longer available" in error.value.detail


def test_disconnected_interface_is_rejected(monkeypatch):
    _install_snapshot(
        monkeypatch,
        adapters={"wlan0": {"up": False, "addresses": [_ipv4("192.168.1.8")]}},
    )

    with pytest.raises(HTTPException) as error:
        main.validate_network_interface("wlan0")

    assert error.value.status_code == 400
    assert "disconnected" in error.value.detail


def test_selected_interface_is_bound_on_linux(monkeypatch, client):
    _install_snapshot(monkeypatch)
    commands = _fake_ping(monkeypatch, LINUX_OUTPUT)

    response = client.get("/api/network-quality?interface=eth0")

    assert response.status_code == 200
    assert commands
    assert commands[0][commands[0].index("-I") + 1] == "eth0"


def test_selected_interface_is_bound_on_macos():
    command = main.build_ping_command("1.1.1.1", 4, 2, "Darwin", interface="en0")

    assert command == ["ping", "-c", "4", "-W", "2000", "-b", "en0", "1.1.1.1"]


def test_selected_interface_is_rejected_when_platform_binding_is_unsupported(monkeypatch):
    _install_snapshot(monkeypatch, system="Windows")

    with pytest.raises(HTTPException) as error:
        main.validate_network_interface("Ethernet")

    assert error.value.status_code == 400
    assert "not supported" in error.value.detail
    with pytest.raises(ValueError):
        main.build_ping_command("1.1.1.1", 4, 2, "Windows", interface="Ethernet")


def test_removed_interface_is_rejected_before_ping_runs(monkeypatch, client):
    adapters = {"eth0": {"up": True, "addresses": [_ipv4("192.168.10.20")]}}

    class MutablePsutil:
        @staticmethod
        def net_if_stats():
            return {
                name: SimpleNamespace(isup=details["up"])
                for name, details in adapters.items()
            }

        @staticmethod
        def net_if_addrs():
            return {
                name: details["addresses"]
                for name, details in adapters.items()
            }

    monkeypatch.setattr(main.platform, "system", lambda: "Linux")
    monkeypatch.setattr(main, "psutil", MutablePsutil)

    listed = client.get("/api/network-interfaces")
    assert listed.status_code == 200
    assert any(item["id"] == "eth0" for item in listed.json()["interfaces"])

    # Simulate unplugging the adapter after the picker was populated.
    adapters.clear()
    commands = _fake_ping(monkeypatch, LINUX_OUTPUT)
    response = client.get("/api/network-quality?interface=eth0")

    assert response.status_code == 400
    assert "no longer available" in response.json()["detail"]
    assert commands == []


def test_network_interfaces_endpoint_uses_safe_automatic_fallback(monkeypatch, client):
    _install_snapshot(monkeypatch, system="Windows")

    response = client.get("/api/network-interfaces")

    assert response.status_code == 200
    assert response.json()["supported"] is False
    assert response.json()["selected"] == "auto"
    assert len(response.json()["interfaces"]) == 1
