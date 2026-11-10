"""Centralized UTC timestamp handling and normalization utility.

This module provides standard timestamp parsing, UTC normalization, date boundary
generation, and safe legacy timestamp interpretation for Smart Connectivity Analyser.

Legacy Naive Timestamp Interpretation Strategy:
-----------------------------------------------
Legacy database records and unannotated timestamp strings lack explicit timezone offsets.
These timestamps were originally produced by server-side `datetime.now().isoformat()` calls,
representing the local wall-clock system time of the machine where the measurement occurred.
Assuming that naive timestamps represent UTC would introduce a systematic chronological distortion
equal to the system's timezone offset (e.g., 5.5 hours in IST, -5 hours in EST).
Therefore, naive timestamps are interpreted in the system's local timezone (or an explicitly
provided `default_tz`) and converted to UTC instants before canonical formatting or comparison.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

CANONICAL_UTC_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def is_canonical_utc(timestamp_str: str) -> bool:
    """Check whether a string matches the canonical UTC ISO 8601 format (YYYY-MM-DDTHH:MM:SS.sssZ)."""
    if not isinstance(timestamp_str, str):
        return False
    return bool(CANONICAL_UTC_REGEX.match(timestamp_str))


def parse_iso_timestamp(
    timestamp_str: str,
    default_tz: tzinfo | None = None,
) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware UTC datetime.

    Supported formats:
    - UTC strings with trailing 'Z' (e.g. '2026-11-01T12:00:00.000Z', '2026-11-01T12:00:00Z')
    - Timezone-offset strings (e.g. '2026-11-01T17:30:00+05:30', '2026-11-01T04:00:00-08:00')
    - Naive ISO strings (e.g. '2026-11-01T12:00:00', '2026-11-01 12:00:00')

    Interpretation of naive timestamps:
    - If `default_tz` is provided, naive timestamps are assumed to be in `default_tz` and converted to UTC.
    - If `default_tz` is None, naive timestamps are interpreted as local system time via `.astimezone(timezone.utc)`.
    """
    if not isinstance(timestamp_str, str) or not timestamp_str.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 date-time string")

    raw = timestamp_str.strip()

    # Normalize trailing "Z" for Python versions that require "+00:00"
    iso_candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw

    try:
        dt = datetime.fromisoformat(iso_candidate)
    except (ValueError, TypeError) as error:
        raise ValueError(
            f"timestamp must be an ISO 8601 date-time string: {timestamp_str}"
        ) from error

    if dt.tzinfo is None:
        if default_tz is not None:
            dt = dt.replace(tzinfo=default_tz).astimezone(timezone.utc)
        else:
            # Presume system local time and convert to UTC
            dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt


def to_canonical_utc(
    value: str | datetime,
    default_tz: tzinfo | None = None,
) -> str:
    """Convert an ISO 8601 string or datetime object to canonical UTC format (YYYY-MM-DDTHH:MM:SS.sssZ)."""
    if isinstance(value, str):
        if is_canonical_utc(value):
            return value
        dt = parse_iso_timestamp(value, default_tz=default_tz)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            if default_tz is not None:
                dt = value.replace(tzinfo=default_tz).astimezone(timezone.utc)
            else:
                dt = value.astimezone(timezone.utc)
        else:
            dt = value.astimezone(timezone.utc)
    else:
        raise ValueError(f"Expected str or datetime, got {type(value).__name__}")

    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def get_current_utc_timestamp() -> str:
    """Generate a timezone-aware current UTC timestamp in canonical format."""
    return to_canonical_utc(datetime.now(timezone.utc))


def get_utc_date_boundaries(
    start_date: date | None,
    end_date: date | None,
) -> tuple[str | None, str | None]:
    """Generate inclusive start and exclusive end boundary strings in UTC for calendar date filtering.

    - `start_date`: returns start-of-day instant 'YYYY-MM-DDT00:00:00.000Z'.
    - `end_date`: returns start-of-next-day instant '(end_date + 1)T00:00:00.000Z'
      which is used with `< end_boundary` to inclusively cover the entire calendar day.
    """
    start_boundary: str | None = None
    if start_date is not None:
        start_dt = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            0,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )
        start_boundary = to_canonical_utc(start_dt)

    end_boundary: str | None = None
    if end_date is not None:
        end_exclusive_dt = datetime(
            end_date.year,
            end_date.month,
            end_date.day,
            0,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        ) + timedelta(days=1)
        end_boundary = to_canonical_utc(end_exclusive_dt)

    return start_boundary, end_boundary


def to_utc_sql(val: str | None) -> str | None:
    """SQLite custom SQL function: normalizes any stored timestamp to canonical UTC.

    Used inside SQL expressions (e.g. `WHERE to_utc_iso(timestamp) >= ?`) to ensure
    consistent instant comparison and chronological ordering across mixed historical formats.
    """
    if val is None:
        return None
    if isinstance(val, str) and is_canonical_utc(val):
        return val
    try:
        return to_canonical_utc(val)
    except Exception:
        return str(val)


def migrate_legacy_timestamps(
    database_path: Path | str,
    dry_run: bool = True,
    default_tz: tzinfo | None = None,
) -> dict[str, Any]:
    """Inspect and optionally convert legacy or non-canonical timestamps in network_tests.

    Legacy Naive Timestamp Interpretation Strategy:
    Legacy naive timestamps (those lacking timezone information) were originally produced
    by server-side `datetime.now().isoformat()` calls, representing the local wall-clock
    system time of the machine where the measurement occurred.
    Assuming that naive timestamps represent UTC would introduce a systematic time error
    equal to the system's timezone offset (e.g., 5 hours 30 minutes in IST).
    Therefore, naive timestamps are interpreted in the system's local timezone (or `default_tz`
    if explicitly provided) and converted to UTC instants before canonical formatting.

    Safety:
    - Defaults to `dry_run=True`, which scans and returns an audit report without modifying rows.
    - When `dry_run=False`, updates are performed inside an atomic transaction.
    - Historical records remain accessible without migration because runtime queries use
      `to_utc_iso()` SQL normalization.
    """
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()

        # Check if table exists
        table_exists = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_tests'"
        ).fetchone()
        if not table_exists:
            return {
                "status": "no_table",
                "total_records": 0,
                "migrated": 0,
                "dry_run": dry_run,
                "conversions": [],
            }

        rows = cursor.execute("SELECT id, timestamp FROM network_tests").fetchall()

        candidates: list[tuple[int, str, str]] = []
        for row in rows:
            rec_id = row["id"]
            orig_ts = row["timestamp"]
            if orig_ts is None:
                continue
            if not is_canonical_utc(orig_ts):
                try:
                    norm_ts = to_canonical_utc(orig_ts, default_tz=default_tz)
                    candidates.append((rec_id, orig_ts, norm_ts))
                except Exception:
                    pass

        if not dry_run and candidates:
            cursor.executemany(
                "UPDATE network_tests SET timestamp = ? WHERE id = ?",
                [(norm_ts, rec_id) for rec_id, _, norm_ts in candidates],
            )
            connection.commit()

        return {
            "status": "success",
            "total_records": len(rows),
            "migrated": len(candidates),
            "dry_run": dry_run,
            "conversions": candidates[:50],
        }

