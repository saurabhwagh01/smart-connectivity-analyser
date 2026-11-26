"""Shared, validated configuration for network diagnostic profiles.

Profiles are validated at import time, so a broken config fails fast
when the server starts. GET /api/diagnostic-profiles exposes this
config, so the frontend never hardcodes profile definitions.
"""

from datetime import datetime, timezone
from enum import Enum
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Check(str, Enum):
    PING = "ping"
    JITTER = "jitter"
    PACKET_LOSS = "packet_loss"
    DOWNLOAD = "download"
    UPLOAD = "upload"


# Measured by the backend ping command.
BACKEND_CHECKS = frozenset({Check.PING, Check.JITTER, Check.PACKET_LOSS})
# Measured in the browser (Cloudflare speed test).
CLIENT_CHECKS = frozenset({Check.DOWNLOAD, Check.UPLOAD})


class DiagnosticProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    description: str
    checks: tuple[Check, ...] = Field(min_length=1)
    packet_count: int = Field(ge=1, le=100)
    estimated_seconds: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_profile(self):
        if len(set(self.checks)) != len(self.checks):
            raise ValueError("checks must not contain duplicates")
        if not set(self.checks) & BACKEND_CHECKS:
            raise ValueError("profile needs at least one backend check")
        if Check.JITTER in self.checks and self.packet_count < 2:
            raise ValueError("jitter needs packet_count >= 2")
        return self


DEFAULT_PACKET_COUNT = 10  # existing behaviour when no profile is given

_PROFILE_LIST = (
    DiagnosticProfile(
        id="quick",
        label="Quick Check",
        description="Fast status check: latency and packet loss.",
        checks=(Check.PING, Check.PACKET_LOSS),
        packet_count=4,
        estimated_seconds=5,
    ),
    DiagnosticProfile(
        id="detailed",
        label="Detailed Diagnosis",
        description=(
            "Latency, jitter, packet loss and download/upload speed "
            "(speed is measured in the browser)."
        ),
        checks=(
            Check.PING,
            Check.JITTER,
            Check.PACKET_LOSS,
            Check.DOWNLOAD,
            Check.UPLOAD,
        ),
        packet_count=20,
        estimated_seconds=40,
    ),
    DiagnosticProfile(
        id="stability",
        label="Stability Test",
        description=(
            "Longer run of latency, jitter and packet loss to see how "
            "consistent the connection is."
        ),
        checks=(Check.PING, Check.JITTER, Check.PACKET_LOSS),
        packet_count=40,
        estimated_seconds=45,
    ),
)

if len({p.id for p in _PROFILE_LIST}) != len(_PROFILE_LIST):
    raise ValueError("duplicate diagnostic profile ids")

PROFILES = {p.id: p for p in _PROFILE_LIST}


class UnknownProfileError(ValueError):
    pass


def get_profile(profile_id):
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise UnknownProfileError(profile_id) from None


def list_profiles():
    return [p.model_dump(mode="json") for p in _PROFILE_LIST]


def build_profile_result(profile, ping_result, measured_at=None):
    """Keep only the profile's documented checks and report each one's status.

    Statuses: "ok", "failed", "client_side" (browser measures it).
    A failed check never carries a fake value: it is returned as None.
    """
    selected = set(profile.checks)
    received = ping_result.get("packets_received", 0)
    result = {
        "profile": profile.id,
        "measured_at": measured_at or datetime.now(timezone.utc).isoformat(),
        "target": ping_result.get("target"),
        "packets_sent": ping_result.get("packets_sent"),
        "packets_received": received,
    }
    checks = {}

    if Check.PING in selected:
        ok = ping_result.get("ping_ms") is not None
        result["ping_ms"] = ping_result.get("ping_ms") if ok else None
        checks["ping"] = (
            {"status": "ok"}
            if ok
            else {"status": "failed", "reason": "No ping replies received."}
        )

    if Check.JITTER in selected:
        ok = received >= 2 and ping_result.get("jitter_ms") is not None
        result["jitter_ms"] = ping_result["jitter_ms"] if ok else None
        checks["jitter"] = (
            {"status": "ok"}
            if ok
            else {"status": "failed", "reason": "Jitter needs at least 2 ping replies."}
        )

    if Check.PACKET_LOSS in selected:
        packet_loss = ping_result.get("packet_loss")
        ok = (
            isinstance(packet_loss, (int, float))
            and not isinstance(packet_loss, bool)
            and math.isfinite(packet_loss)
            and 0 <= packet_loss <= 100
        )
        result["packet_loss"] = packet_loss if ok else None
        checks["packet_loss"] = (
            {"status": "ok"}
            if ok
            else {
                "status": "failed",
                "reason": "Packet-loss measurement is missing or invalid.",
            }
        )
    for check in (Check.DOWNLOAD, Check.UPLOAD):
        if check in selected:
            checks[check.value] = {
                "status": "client_side",
                "reason": "Measured in the browser, not by the backend.",
            }

    backend_statuses = [
        checks[c.value]["status"] for c in profile.checks if c in BACKEND_CHECKS
    ]
    if all(s == "ok" for s in backend_statuses):
        result["result_status"] = "complete"
    elif any(s == "ok" for s in backend_statuses):
        result["result_status"] = "partial"
    else:
        result["result_status"] = "failed"

    result["checks"] = checks
    return result