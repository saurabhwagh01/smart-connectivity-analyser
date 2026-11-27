"""DNS resolution diagnostic.

Checks whether this machine can resolve a public domain name, how long it
takes, and, if it fails, a safe category. It never returns resolver
addresses, resolved IPs or raw error text.

What it can and cannot prove is documented in README.md.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from threading import BoundedSemaphore

# Fixed on purpose: never take the hostname from a request.
DNS_TEST_HOSTNAME = "example.com"
DNS_TIMEOUT_SECONDS = 3.0
_MAX_IN_FLIGHT_RESOLUTIONS = 2
_DNS_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_IN_FLIGHT_RESOLUTIONS,
    thread_name_prefix="dns-check",
)
_DNS_SLOTS = BoundedSemaphore(_MAX_IN_FLIGHT_RESOLUTIONS)


def _codes(*names, extra=()):
    found = {getattr(socket, name) for name in names if hasattr(socket, name)}
    return found | set(extra)


# gaierror codes differ per platform; the extras are Windows (WSA) codes.
NOT_FOUND_CODES = _codes("EAI_NONAME", "EAI_NODATA", extra=(11001, 11004))
RESOLVER_UNAVAILABLE_CODES = _codes("EAI_AGAIN", "EAI_FAIL", extra=(11002, 11003))


def classify_dns_error(error):
    """Map an exception to a safe, fixed failure category."""
    if isinstance(error, socket.gaierror):
        if error.errno in NOT_FOUND_CODES:
            return "not_found"
        if error.errno in RESOLVER_UNAVAILABLE_CODES:
            return "resolver_unavailable"
    return "unknown"


def check_dns(
    hostname=DNS_TEST_HOSTNAME,
    timeout_seconds=DNS_TIMEOUT_SECONDS,
    resolver=socket.getaddrinfo,
):
    """Resolve `hostname` and report the outcome. Never raises."""
    measured_at = datetime.now(timezone.utc).isoformat()
    result = {
        "check": "dns",
        "hostname": hostname,
        "status": "failed",
        "duration_ms": None,
        "failure_category": None,
        "measured_at": measured_at,
    }

    # getaddrinfo cannot be cancelled. A shared fixed-size pool and a
    # matching semaphore prevent timed-out workers accumulating per request.
    if not _DNS_SLOTS.acquire(blocking=False):
        result["failure_category"] = "capacity_exhausted"
        return result

    started = time.perf_counter()

    try:
        future = _DNS_EXECUTOR.submit(resolver, hostname, None)
    except Exception as error:
        _DNS_SLOTS.release()
        result["failure_category"] = classify_dns_error(error)
        result["duration_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        return result

    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        future.result(timeout=timeout_seconds)
    except FutureTimeout:
        result["failure_category"] = "timeout"
        return result
    except Exception as error:
        result["failure_category"] = classify_dns_error(error)
        result["duration_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        return result

    result["status"] = "ok"
    result["duration_ms"] = round(
        (time.perf_counter() - started) * 1000, 2
    )
    return result
