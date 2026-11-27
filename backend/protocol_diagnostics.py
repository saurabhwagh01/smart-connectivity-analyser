"""Independent IPv4 and IPv6 connectivity diagnostics."""

import errno
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore


CHECK_HOST = "one.one.one.one"
CHECK_PORT = 443
CONNECT_TIMEOUT_SECONDS = 1.5
RESOLVER_TIMEOUT_SECONDS = 1.5
_RESOLVER_POOL = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="protocol-dns",
)
# getaddrinfo() cannot be cancelled once running. Admit only as many resolver
# calls as there are workers, and keep each slot occupied until that call ends.
_RESOLVER_SLOTS = BoundedSemaphore(2)


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def _resolve_addresses(family):
    resolver_slots = _RESOLVER_SLOTS
    if not resolver_slots.acquire(blocking=False):
        return None, "timeout"

    try:
        resolution = _RESOLVER_POOL.submit(
            socket.getaddrinfo,
            CHECK_HOST,
            CHECK_PORT,
            family=family,
            type=socket.SOCK_STREAM,
        )
    except Exception:
        resolver_slots.release()
        raise

    # A timed-out caller must not free capacity while getaddrinfo is still
    # running; the callback releases the slot only when the worker really ends.
    resolution.add_done_callback(
        lambda _future, slots=resolver_slots: slots.release()
    )
    try:
        return resolution.result(timeout=RESOLVER_TIMEOUT_SECONDS), None
    except TimeoutError:
        return None, "timeout"
    except socket.gaierror:
        return None, "dns_failure"


def _check_family(family):
    if family == socket.AF_INET6 and not socket.has_ipv6:
        return {"status": "unsupported", "reason": "not_supported"}

    try:
        addresses, error = _resolve_addresses(family)
    except OSError:
        return _unavailable("dns_failure")

    if error:
        return _unavailable(error)

    if not addresses:
        return _unavailable("dns_failure")

    saw_timeout = False
    saw_supported_socket = False
    for address in addresses:
        address_family, socket_type, protocol, _, sockaddr = address
        try:
            connection = socket.socket(
                address_family,
                socket_type,
                protocol,
            )
        except OSError as error:
            if (
                address_family == socket.AF_INET6
                and error.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT)
            ):
                return {"status": "unsupported", "reason": "not_supported"}
            continue

        saw_supported_socket = True
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(sockaddr)
            return {"status": "available", "reason": None}
        except (socket.timeout, TimeoutError):
            saw_timeout = True
        except OSError as error:
            if error.errno in (errno.ETIMEDOUT,):
                saw_timeout = True
        finally:
            connection.close()

    if saw_timeout:
        return _unavailable("timeout")
    if not saw_supported_socket:
        return _unavailable("connection_failure")
    return _unavailable("connection_failure")


def detect_network_protocols():
    """Check outbound IPv4 and IPv6 independently with bounded connects.

    The hostname and port are fixed to prevent this diagnostic from being
    used as an arbitrary network probe. Only safe result categories are
    returned; system resolver and socket details are not exposed.
    """
    ipv4 = _check_family(socket.AF_INET)
    ipv6 = _check_family(socket.AF_INET6)
    return {
        "connected": (
            ipv4["status"] == "available"
            or ipv6["status"] == "available"
        ),
        "ipv4": ipv4,
        "ipv6": ipv6,
    }

