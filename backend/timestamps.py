"""Canonical UTC timestamps for network test records (issue #39).

Every new record is stored in one canonical form, the same format the
browser's ``Date.toISOString()`` produces::

    2026-11-27T05:19:03.832Z

The form has a fixed width and is always UTC, so comparing two canonical
strings gives the same result as comparing the instants they represent.

Legacy records
--------------
Older records may hold other ISO 8601 forms. They are never rewritten in
the database; they are normalized when they are read:

* Timestamps with ``Z`` or an offset (``+05:30``, ``-05:00``) are
  converted to the same instant in UTC.
* Naive timestamps (no ``Z`` and no offset) were written by older backend
  versions with ``datetime.now()``, which is the server's local time. They
  are therefore interpreted in the server's local time zone, not as UTC.
* Values that are not valid ISO 8601 date-times cannot be placed in time.
  ``to_canonical_utc`` returns ``None`` for them instead of a malformed
  string, so they are never compared as if they were real timestamps.
"""

from datetime import date, datetime, time, timezone


def parse_timestamp(value):
    """Return ``value`` as a timezone-aware UTC datetime, or ``None``.

    ``None`` is returned for anything that is not a valid ISO 8601
    date-time string, so callers can handle malformed values explicitly.
    """
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        # Python < 3.11 does not accept a trailing "Z".
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            # Legacy naive timestamp: server local time (see module docs).
            parsed = parsed.astimezone()

        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def format_canonical_utc(moment):
    """Format an aware datetime as a canonical UTC timestamp string."""
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return utc.isoformat(timespec="milliseconds") + "Z"


def to_canonical_utc(value):
    """Return the canonical UTC form of a timestamp string, or ``None``."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return format_canonical_utc(parsed)


def current_utc_timestamp():
    """Return the current time as a canonical UTC timestamp string."""
    return format_canonical_utc(datetime.now(timezone.utc))


def utc_day_start(day):
    """Return midnight UTC at the start of ``day`` as a canonical string."""
    if not isinstance(day, date):
        raise TypeError("day must be a datetime.date")
    return format_canonical_utc(datetime.combine(day, time.min, tzinfo=timezone.utc))


def canonical_sort_key(timestamp, record_id):
    """Sort key for chronological order with a stable tie-breaker.

    Records with the same instant are ordered by database id. Records
    whose timestamp cannot be parsed sort after all valid records.
    """
    canonical = to_canonical_utc(timestamp)
    return (canonical is None, canonical or "", record_id)
