"""
Unit and integration tests for packet loss measurement and network quality API.
Covers:
- Formula: Packet Loss (%) = ((Sent - Received) / Sent) * 100
- 10 sent, 10 received -> 0%
- 10 sent, 9 received -> 10%
- 10 sent, 5 received -> 50%
- 10 sent, 0 received -> 100%
- Zero probes sent -> ValueError / 400 Bad Request (no division by zero)
- Invalid / malformed probe output handling
- Timeout handling (504)
- DNS resolution failure handling (502)
- Missing ping executable handling (501)
- Permission errors (403)
- Unsupported platform command construction
- API integration: successful, zero loss, partial loss, 100% loss, failure modes
"""

import subprocess
import socket
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

from backend.main import (
    parse_ping_output,
    execute_network_ping,
)


# ============================================================
# PHASE 5A: BACKEND UNIT TESTS - parse_ping_output & Calculation
# ============================================================

class TestPacketLossCalculation:
    """Test parse_ping_output logic and packet loss calculation formulas."""

    def test_ten_sent_ten_received_zero_percent(self):
        """10 probes sent, 10 received -> 0% packet loss."""
        output = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=21ms TTL=58
Reply from 1.1.1.1: bytes=32 time=19ms TTL=58
Reply from 1.1.1.1: bytes=32 time=22ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=23ms TTL=58
Reply from 1.1.1.1: bytes=32 time=18ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=21ms TTL=58

Ping statistics for 1.1.1.1:
    Packets: Sent = 10, Received = 10, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 18ms, Maximum = 23ms, Average = 20ms
"""
        result = parse_ping_output(output, 10)
        assert result["packets_sent"] == 10
        assert result["packets_received"] == 10
        assert result["packet_loss"] == 0.0
        assert len(result["ping_times"]) == 10

    def test_ten_sent_nine_received_ten_percent(self):
        """10 probes sent, 9 received -> 10% packet loss."""
        output = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=21ms TTL=58
Request timed out.
Reply from 1.1.1.1: bytes=32 time=22ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=23ms TTL=58
Reply from 1.1.1.1: bytes=32 time=18ms TTL=58
Reply from 1.1.1.1: bytes=32 time=20ms TTL=58
Reply from 1.1.1.1: bytes=32 time=21ms TTL=58

Ping statistics for 1.1.1.1:
    Packets: Sent = 10, Received = 9, Lost = 1 (10% loss),
Approximate round trip times in milli-seconds:
    Minimum = 18ms, Maximum = 23ms, Average = 20ms
"""
        result = parse_ping_output(output, 10)
        assert result["packets_sent"] == 10
        assert result["packets_received"] == 9
        assert result["packet_loss"] == 10.0
        assert len(result["ping_times"]) == 9

    def test_ten_sent_five_received_fifty_percent(self):
        """10 probes sent, 5 received -> 50% packet loss."""
        output = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=25ms TTL=58
Request timed out.
Reply from 1.1.1.1: bytes=32 time=25ms TTL=58
Request timed out.
Reply from 1.1.1.1: bytes=32 time=25ms TTL=58
Request timed out.
Reply from 1.1.1.1: bytes=32 time=25ms TTL=58
Request timed out.
Reply from 1.1.1.1: bytes=32 time=25ms TTL=58
Request timed out.

Ping statistics for 1.1.1.1:
    Packets: Sent = 10, Received = 5, Lost = 5 (50% loss),
"""
        result = parse_ping_output(output, 10)
        assert result["packets_sent"] == 10
        assert result["packets_received"] == 5
        assert result["packet_loss"] == 50.0
        assert len(result["ping_times"]) == 5

    def test_ten_sent_zero_received_one_hundred_percent(self):
        """10 probes sent, 0 received -> 100% packet loss."""
        output = """
Pinging 192.0.2.1 with 32 bytes of data:
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.

Ping statistics for 192.0.2.1:
    Packets: Sent = 10, Received = 0, Lost = 10 (100% loss),
"""
        result = parse_ping_output(output, 10)
        assert result["packets_sent"] == 10
        assert result["packets_received"] == 0
        assert result["packet_loss"] == 100.0
        assert len(result["ping_times"]) == 0

    def test_zero_probes_sent_raises_value_error_no_division_by_zero(self):
        """Zero probes sent raises ValueError and prevents division by zero."""
        with pytest.raises(ValueError, match="greater than zero"):
            parse_ping_output("Some ping text", 0)

        with pytest.raises(ValueError, match="greater than zero"):
            parse_ping_output("Some ping text", -5)

    def test_linux_output_parsing(self):
        """Test parsing Linux iputils ping output."""
        linux_out = """
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=14.2 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=58 time=15.1 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=58 time=13.9 ms

--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 13.900/14.400/15.100/0.512 ms
"""
        result = parse_ping_output(linux_out, 3)
        assert result["packets_sent"] == 3
        assert result["packets_received"] == 3
        assert result["packet_loss"] == 0.0
        assert len(result["ping_times"]) == 3
        assert result["ping_times"] == [14.2, 15.1, 13.9]

    def test_linux_partial_loss_parsing(self):
        """Test Linux output with 20% packet loss."""
        linux_out = """
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=58 time=20.0 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=58 time=22.0 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=58 time=21.0 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=58 time=19.5 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 4 received, 20% packet loss, time 4010ms
"""
        result = parse_ping_output(linux_out, 5)
        assert result["packets_sent"] == 5
        assert result["packets_received"] == 4
        assert result["packet_loss"] == 20.0
        assert len(result["ping_times"]) == 4

    def test_sub_millisecond_time_parsing(self):
        """Windows ping with time<1ms is parsed as 1ms."""
        win_sub_ms = """
Pinging 127.0.0.1 with 32 bytes of data:
Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
Reply from 127.0.0.1: bytes=32 time<1ms TTL=128

Ping statistics for 127.0.0.1:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
"""
        result = parse_ping_output(win_sub_ms, 2)
        assert result["packets_sent"] == 2
        assert result["packets_received"] == 2
        assert result["packet_loss"] == 0.0
        assert len(result["ping_times"]) == 2
        assert result["ping_times"] == [1.0, 1.0]

    def test_invalid_probe_output_fallback_to_zero_received(self):
        """Corrupt or non-ping output calculates 100% loss without crashing."""
        corrupt_out = "Some unparseable junk text without ping numbers"
        result = parse_ping_output(corrupt_out, 10)
        assert result["packets_sent"] == 10
        assert result["packets_received"] == 0
        assert result["packet_loss"] == 100.0


# ============================================================
# PHASE 5A: BACKEND UNIT TESTS - execute_network_ping & Error Handling
# ============================================================

class TestExecuteNetworkPing:
    """Test execution error scenarios in execute_network_ping."""

    def test_zero_packet_count_raises_http_400(self):
        """execute_network_ping with packet_count=0 raises 400 Bad Request."""
        with pytest.raises(HTTPException) as exc_info:
            execute_network_ping(packet_count=0)
        assert exc_info.value.status_code == 400

    def test_dns_resolution_failure_raises_http_502(self):
        """Unresolvable host raises 502 Bad Gateway."""
        with patch("socket.gethostbyname", side_effect=socket.gaierror(11001, "getaddrinfo failed")):
            with pytest.raises(HTTPException) as exc_info:
                execute_network_ping(target="nonexistent.invalid.example")
            assert exc_info.value.status_code == 502
            assert "DNS resolution failed" in exc_info.value.detail

    def test_missing_ping_executable_raises_http_501(self):
        """Missing ping binary raises 501 Not Implemented."""
        with patch("socket.gethostbyname", return_value="1.1.1.1"):
            with patch("shutil.which", return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    execute_network_ping()
                assert exc_info.value.status_code == 501
                assert "not found" in exc_info.value.detail

    def test_timeout_expired_raises_http_504(self):
        """Subprocess timeout raises 504 Gateway Timeout."""
        with patch("socket.gethostbyname", return_value="1.1.1.1"):
            with patch("shutil.which", return_value="/bin/ping"):
                with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ping", timeout=30)):
                    with pytest.raises(HTTPException) as exc_info:
                        execute_network_ping()
                    assert exc_info.value.status_code == 504
                    assert "timed out" in exc_info.value.detail

    def test_permission_error_raises_http_403(self):
        """PermissionError on restricted ICMP ping raises 403 Forbidden."""
        with patch("socket.gethostbyname", return_value="1.1.1.1"):
            with patch("shutil.which", return_value="/bin/ping"):
                with patch("subprocess.run", side_effect=PermissionError("Operation not permitted")):
                    with pytest.raises(HTTPException) as exc_info:
                        execute_network_ping()
                    assert exc_info.value.status_code == 403
                    assert "denied" in exc_info.value.detail

    def test_platform_command_selection(self):
        """Ensure correct ping flags are used for Windows, Linux, and macOS."""
        mock_proc = MagicMock()
        mock_proc.stdout = """
Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)
Reply from 1.1.1.1: bytes=32 time=15ms TTL=58
Reply from 1.1.1.1: bytes=32 time=16ms TTL=58
Reply from 1.1.1.1: bytes=32 time=14ms TTL=58
Reply from 1.1.1.1: bytes=32 time=15ms TTL=58
"""
        with patch("socket.gethostbyname", return_value="1.1.1.1"):
            with patch("shutil.which", return_value="ping"):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    # Windows
                    with patch("platform.system", return_value="Windows"):
                        execute_network_ping(target="1.1.1.1", packet_count=4, timeout_ms=1000)
                        call_args = mock_run.call_args[0][0]
                        assert "-n" in call_args
                        assert "-w" in call_args

                    # Linux
                    with patch("platform.system", return_value="Linux"):
                        execute_network_ping(target="1.1.1.1", packet_count=4, timeout_ms=1000)
                        call_args = mock_run.call_args[0][0]
                        assert "-c" in call_args
                        assert "-W" in call_args

                    # Darwin (macOS)
                    with patch("platform.system", return_value="Darwin"):
                        execute_network_ping(target="1.1.1.1", packet_count=4, timeout_ms=1000)
                        call_args = mock_run.call_args[0][0]
                        assert "-c" in call_args
                        assert "-W" in call_args


# ============================================================
# PHASE 5B: BACKEND INTEGRATION TESTS - /api/network-quality Endpoint
# ============================================================

class TestNetworkQualityApiIntegration:
    """Test /api/network-quality endpoint with various mock and real probe responses."""

    def test_api_network_quality_success_zero_loss(self, client):
        """API returns 0.0 packet loss and valid metrics for successful ping."""
        mock_result = {
            "packets_sent": 10,
            "packets_received": 10,
            "packet_loss": 0.0,
            "ping_times": [20.0, 22.0, 21.0, 19.0, 20.0, 21.0, 23.0, 18.0, 20.0, 21.0],
        }
        with patch("backend.main.execute_network_ping", return_value=mock_result):
            response = client.get("/api/network-quality")
            assert response.status_code == 200
            data = response.json()
            assert data["packet_loss"] == 0.0
            assert data["packets_sent"] == 10
            assert data["packets_received"] == 10
            assert data["ping_ms"] == 20.5
            assert data["min_ping_ms"] == 18.0
            assert data["max_ping_ms"] == 23.0
            assert isinstance(data["jitter_ms"], float)
            assert data["status"] == "excellent"

    def test_api_network_quality_partial_loss(self, client):
        """API returns accurate partial loss percentage (e.g. 20%)."""
        mock_result = {
            "packets_sent": 10,
            "packets_received": 8,
            "packet_loss": 20.0,
            "ping_times": [30.0, 35.0, 28.0, 32.0, 31.0, 29.0, 34.0, 30.0],
        }
        with patch("backend.main.execute_network_ping", return_value=mock_result):
            response = client.get("/api/network-quality")
            assert response.status_code == 200
            data = response.json()
            assert data["packet_loss"] == 20.0
            assert data["packets_sent"] == 10
            assert data["packets_received"] == 8
            assert data["status"] == "excellent"

    def test_api_network_quality_one_hundred_percent_loss(self, client):
        """API returns 100.0 packet loss and unreachable status when 0 packets are received."""
        mock_result = {
            "packets_sent": 10,
            "packets_received": 0,
            "packet_loss": 100.0,
            "ping_times": [],
        }
        with patch("backend.main.execute_network_ping", return_value=mock_result):
            response = client.get("/api/network-quality")
            assert response.status_code == 200
            data = response.json()
            assert data["packet_loss"] == 100.0
            assert data["packets_sent"] == 10
            assert data["packets_received"] == 0
            assert data["ping_ms"] is None
            assert data["jitter_ms"] is None
            assert data["status"] == "unreachable"

    def test_api_network_quality_timeout_returns_504(self, client):
        """API propagates 504 on timeout."""
        with patch("backend.main.execute_network_ping", side_effect=HTTPException(status_code=504, detail="Ping measurement timed out.")):
            response = client.get("/api/network-quality")
            assert response.status_code == 504
            assert "timed out" in response.json()["detail"]

    def test_api_network_quality_dns_failure_returns_502(self, client):
        """API propagates 502 on DNS failure."""
        with patch("backend.main.execute_network_ping", side_effect=HTTPException(status_code=502, detail="DNS resolution failed")):
            response = client.get("/api/network-quality")
            assert response.status_code == 502
            assert "DNS" in response.json()["detail"]
