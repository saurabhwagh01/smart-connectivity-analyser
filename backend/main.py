from fastapi import FastAPI, HTTPException, Query

from fastapi.encoders import jsonable_encoder

from fastapi.exceptions import RequestValidationError

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from fastapi import Query
from backend.diagnostic_profiles import (
    DEFAULT_PACKET_COUNT,
    UnknownProfileError,
    build_profile_result,
    get_profile,
    list_profiles,
)
from backend.timestamps import (
    current_utc_timestamp,
    to_canonical_utc,
    utc_day_start,
)
from pathlib import Path
from backend.protocol_diagnostics import detect_network_protocols

import sqlite3
from contextlib import closing, contextmanager
import json
import logging
import math
import sys

import platform
import subprocess

import re

import statistics
from datetime import date, datetime, timedelta, timezone

from backend.dns_check import check_dns

# ============================================================
# AI MODEL IMPORTS
# ============================================================

AI_BACKEND_DIR = Path(__file__).resolve().parent
if str(AI_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(AI_BACKEND_DIR))

from anomaly_explanation import build_anomaly_explanation

try:
    import torch
    from ai_engine import (
        FEATURES,
        SEQUENCE_LENGTH,
        ConnectivityPredictor,
        TransformerAutoencoder,
        load_network_data,
        normalize_values,
        denormalize_value,
    )
    from final_predictor import (
        final_predictor,
        FINAL_PREDICTOR_READY,
    )
except Exception as error:
    torch = None
    AI_IMPORT_ERROR = str(error)
    FEATURES = ()
    SEQUENCE_LENGTH = 8
    ConnectivityPredictor = None
    TransformerAutoencoder = None
    load_network_data = lambda: []
    normalize_values = None
    denormalize_value = None
    final_predictor = None
    FINAL_PREDICTOR_READY = False
else:
    AI_IMPORT_ERROR = None






# ============================================================

# APPLICATION

# ============================================================



app = FastAPI(

    title="Smart Internet Connectivity Analyser",

    version="1.0.0"

)





app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



# ============================================================
# VALIDATION ERRORS
# ============================================================

def make_json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)

    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}

    if isinstance(value, list):
        return [make_json_safe(item) for item in value]

    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Same response as FastAPI's default handler. Rejected NaN or
    # Infinity inputs are echoed as strings, since they cannot be
    # encoded as JSON and would otherwise cause a 500 error.
    return JSONResponse(
        status_code=422,
        content={"detail": make_json_safe(jsonable_encoder(exc.errors()))},
    )





# ============================================================

# PATHS

# ============================================================



BASE_DIR = Path(__file__).resolve().parent.parent



DB_PATH = BASE_DIR / "network_history.db"



INDEX_FILE = BASE_DIR / "index.html"


# ============================================================
# STATIC FRONTEND FILES
# ============================================================

CSS_DIR = BASE_DIR / "css"
JS_DIR = BASE_DIR / "js"

app.mount(
    "/css",
    StaticFiles(directory=str(CSS_DIR)),
    name="css"
)

app.mount(
    "/js",
    StaticFiles(directory=str(JS_DIR)),
    name="js"
)



# ============================================================
# AI MODEL STATE
# ============================================================

AI_MODEL_DIR = BASE_DIR / "backend" / "models"
AI_PREDICTION_MODEL_PATH = AI_MODEL_DIR / "connectivity_predictor.pt"
AI_ANOMALY_MODEL_PATH = AI_MODEL_DIR / "anomaly_autoencoder.pt"
AI_SCALER_PATH = AI_MODEL_DIR / "scaler.json"

ai_prediction_model = None
ai_anomaly_model = None
ai_scaler = None
ai_anomaly_threshold = None


def load_ai_models():
    global ai_prediction_model
    global ai_anomaly_model
    global ai_scaler
    global ai_anomaly_threshold

    if torch is None:
        return False, f"PyTorch/AI import failed: {AI_IMPORT_ERROR}"

    required = [
        AI_ANOMALY_MODEL_PATH,
        AI_SCALER_PATH,
    ]

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return False, f"Missing AI files: {', '.join(missing)}"

    try:
        with open(AI_SCALER_PATH, "r", encoding="utf-8") as file:
            ai_scaler = json.load(file)

        ai_anomaly_model = TransformerAutoencoder()
        ai_anomaly_model.load_state_dict(
            torch.load(
                AI_ANOMALY_MODEL_PATH,
                map_location="cpu",
                weights_only=True,
            )
        )
        ai_anomaly_model.eval()

        # Establish an anomaly threshold from reconstruction errors
        # on the same real measurements used during training.
        data = load_network_data()
        errors = []

        with torch.no_grad():
            for item in data:
                normalized = normalize_values(item["values"], ai_scaler)
                sample = torch.tensor(
                    normalized,
                    dtype=torch.float32,
                ).reshape(1, 1, len(FEATURES))

                reconstructed = ai_anomaly_model(sample)
                target = sample[:, -1, :]
                error_value = torch.mean(
                    (reconstructed - target) ** 2
                ).item()
                errors.append(error_value)

        if errors:
            mean_error = sum(errors) / len(errors)
            variance = sum(
                (value - mean_error) ** 2
                for value in errors
            ) / len(errors)
            ai_anomaly_threshold = (
                mean_error + 2.0 * math.sqrt(variance)
            )
        else:
            ai_anomaly_threshold = 0.05

        return True, "AI anomaly model and final prediction model loaded successfully."

    except Exception as error:
        ai_prediction_model = None
        ai_anomaly_model = None
        ai_scaler = None
        ai_anomaly_threshold = None
        return False, f"AI model loading failed: {error}"



# ============================================================

# DATABASE

# ============================================================



def get_connection():

    connection = sqlite3.connect(DB_PATH)



    connection.row_factory = sqlite3.Row

    # canonical_utc(timestamp) lets queries filter and sort stored values,
    # including legacy formats, by their real UTC instant (issue #39).
    connection.create_function(
        "canonical_utc", 1, to_canonical_utc, deterministic=True
    )

    return connection


logger = logging.getLogger(__name__)

HISTORY_READ_ERROR = "Could not load network history. Please try again later."
HISTORY_SAVE_ERROR = "Could not save the network test. Please try again later."
HISTORY_DELETE_ERROR = "Could not delete network history. Please try again later."


@contextmanager
def history_database(error_message):
    """Open a history database connection and always close it.

    SQLite errors are logged with full details on the server and returned to
    the client as a 500 response with a fixed, user-friendly message, so
    internal error text and file paths are not exposed.
    """
    connection = None
    try:
        connection = get_connection()
        yield connection
    except sqlite3.Error:
        logger.exception("Network history database error: %s", error_message)
        raise HTTPException(status_code=500, detail=error_message)
    finally:
        if connection is not None:
            connection.close()





def initialize_database():



    connection = get_connection()



    cursor = connection.cursor()



    cursor.execute(

        """

        CREATE TABLE IF NOT EXISTS network_tests (

            id INTEGER PRIMARY KEY AUTOINCREMENT,



            timestamp TEXT NOT NULL,



            download_mbps REAL,



            upload_mbps REAL,



            ping_ms REAL,



            jitter_ms REAL,



            packet_loss REAL,



            network_type TEXT,



            connectivity_score REAL,



            latitude REAL,



            longitude REAL

        )

        """

    )



    connection.commit()



    connection.close()





initialize_database()
AI_MODELS_READY, AI_MODELS_MESSAGE = load_ai_models()




# ============================================================

# DATA MODEL

# ============================================================



MEASUREMENT_FIELDS = (
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
)


class NetworkTest(BaseModel):

    # Reject NaN and Infinity. They cannot be stored or returned
    # as valid JSON, and would break /api/network-history.
    model_config = ConfigDict(allow_inf_nan=False)



    timestamp: str | None = None



    download_mbps: float | None = Field(default=None, ge=0)



    upload_mbps: float | None = Field(default=None, ge=0)



    ping_ms: float | None = Field(default=None, ge=0)



    jitter_ms: float | None = Field(default=None, ge=0)



    packet_loss: float | None = Field(default=None, ge=0, le=100)



    network_type: str | None = Field(default="Unknown", max_length=50)



    connectivity_score: float | None = Field(default=None, ge=0, le=100)



    latitude: float | None = Field(default=None, ge=-90, le=90)



    longitude: float | None = Field(default=None, ge=-180, le=180)



    # Pydantic would otherwise store true/false as 1.0/0.0.
    @field_validator(
        *MEASUREMENT_FIELDS,
        "latitude",
        "longitude",
        mode="before",
    )
    @classmethod
    def reject_boolean_values(cls, value):
        if isinstance(value, bool):
            raise ValueError("Input should be a number, not a boolean")

        return value


    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value):
        if value is None or not value.strip():
            return None

        # Store one canonical UTC form (issue #39). Offsets are converted
        # to the same instant in UTC; a timestamp without an offset is
        # read as server local time, matching older stored records.
        canonical = to_canonical_utc(value)
        if canonical is None:
            raise ValueError(
                "timestamp must be an ISO 8601 date-time string"
            )

        return canonical


    @model_validator(mode="after")
    def validate_record(self):
        if all(getattr(self, field) is None for field in MEASUREMENT_FIELDS):
            raise ValueError(
                "At least one network measurement is required: "
                + ", ".join(MEASUREMENT_FIELDS)
            )

        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "latitude and longitude must be provided together"
            )

        return self





# ============================================================

# ROOT

# ============================================================



@app.get("/")

def root():



    if INDEX_FILE.exists():

        return FileResponse(INDEX_FILE)



    return {

        "message": "Smart Internet Connectivity Analyser API"

    }





# ============================================================

# HEALTH CHECK

# ============================================================



@app.get("/api/health")

def health():



    return {

        "status": "ok",

        "service": "Smart Internet Connectivity Analyser"

    }





# ============================================================
# LIVENESS AND READINESS
# ============================================================
# /api/health/live only reports that the API process is responding.
# /api/health/ready checks that the required SQLite history database is usable.
# Neither endpoint runs network diagnostics, trains models, or loads AI models.


def check_database_ready():
    """Return True when the history database exists and has its table.

    The file is opened read-only, so a probe can never create or change it,
    and every failure is reduced to False so no internal detail can leak.
    """
    try:
        # mode=ro prevents creating or changing the database; timeout=2
        # bounds a locked-database wait; closing() always frees the connection.
        with closing(
            sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True, timeout=2)
        ) as connection:
            # sqlite_master avoids reading or changing any user data.
            row = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'network_tests'"
            ).fetchone()
        return row is not None
    except Exception:
        # Every failure becomes False so no internal path or error text leaks.
        return False


@app.get("/api/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/api/health/ready")
def health_ready():
    database_ready = check_database_ready()

    body = {
        "status": "ready" if database_ready else "not_ready",
        "checks": {
            "database": "ok" if database_ready else "unavailable",
        },
        "optional": {
            "ai_models": "available" if AI_MODELS_READY else "unavailable",
        },
    }

    # A failed required dependency returns 503 with the same response schema.
    return JSONResponse(status_code=200 if database_ready else 503, content=body)


# ============================================================

@app.get("/api/dns-check")
def dns_check():
    # DNS failure is a measurement result, not a failure of the API itself.
    return check_dns()
@app.get("/api/network-protocols")
def network_protocols():
    """Report independent IPv4/IPv6 connectivity without changing ping data."""
    return detect_network_protocols()


# SIMPLE PING

# ============================================================



@app.get("/api/ping")

def ping():



    return {

        "message": "Backend is running",

        "status": "ok"

    }




# ============================================================
# PING OUTPUT PARSING
# ============================================================

# Matches one reply's round-trip time on Windows ("time=12ms",
# "time<1ms") and Linux/macOS ("time=12.4 ms").
PING_TIME_PATTERN = re.compile(
    r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms",
    re.IGNORECASE,
)

# Matches the packet-loss summary on Windows ("(0% loss)"),
# Linux ("25% packet loss") and macOS ("0.0% packet loss").
PACKET_LOSS_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)%\s*(?:packet\s+)?loss",
    re.IGNORECASE,
)


def parse_ping_output(output):
    """Return (ping_times_ms, packet_loss_percent) from ping output.

    packet_loss_percent is None when no loss summary is found.
    """
    ping_times = [
        float(value)
        for value in PING_TIME_PATTERN.findall(output)
    ]

    loss_match = PACKET_LOSS_PATTERN.search(output)
    packet_loss = float(loss_match.group(1)) if loss_match else None

    return ping_times, packet_loss


def build_ping_command(target, packet_count, timeout_seconds, system):
    """Return the ping command for the given operating system.

    system is a platform.system() value: "Windows", "Linux" or
    "Darwin" (macOS). The target goes last, because macOS stops
    reading options at the first non-option argument.
    """
    if system == "Windows":
        # -n: number of pings, -w: reply timeout in milliseconds.
        return [
            "ping",
            "-n", str(packet_count),
            "-w", str(timeout_seconds * 1000),
            target,
        ]

    if system == "Darwin":
        # -c: number of pings, -W: reply timeout in milliseconds.
        return [
            "ping",
            "-c", str(packet_count),
            "-W", str(timeout_seconds * 1000),
            target,
        ]

    # Linux and other Unix-like systems.
    # -c: number of pings, -W: reply timeout in seconds.
    return [
        "ping",
        "-c", str(packet_count),
        "-W", str(timeout_seconds),
        target,
    ]


def measure_ping(packet_count=DEFAULT_PACKET_COUNT):
    """Run the ping measurement. Raises HTTPException if ping cannot run."""
    target = "1.1.1.1"
    timeout_seconds = 2

    command = build_ping_command(
        target, packet_count, timeout_seconds, platform.system()
    )

    # 10 packets keeps the original 30 s limit; longer runs scale up.
    subprocess_timeout = max(30, packet_count * 2 + 10)

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
        output = process.stdout
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="The ping command is not available on this server.",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Ping measurement timed out.")
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"Ping measurement failed: {error}"
        )

    ping_times, packet_loss = parse_ping_output(output)

    # No replies and no loss summary means ping failed to run, which is
    # not the same as a real 100% packet loss.
    if not ping_times and packet_loss is None:
        reason = process.stderr.strip() or "ping produced no output"
        raise HTTPException(
            status_code=503, detail=f"Ping measurement failed: {reason}"
        )

    if packet_loss is None:
        packet_loss = ((packet_count - len(ping_times)) / packet_count) * 100

    if len(ping_times) == 0:
        return {
            "target": target,
            "packets_sent": packet_count,
            "packets_received": 0,
            "packet_loss": 100.0,
            "ping_ms": None,
            "min_ping_ms": None,
            "max_ping_ms": None,
            "jitter_ms": None,
            "status": "unreachable",
        }

    average_ping = statistics.mean(ping_times)

    # Jitter: mean absolute difference between consecutive replies.
    if len(ping_times) >= 2:
        jitter = statistics.mean(
            abs(ping_times[i] - ping_times[i - 1])
            for i in range(1, len(ping_times))
        )
    else:
        jitter = 0.0

    if average_ping <= 50:
        status = "excellent"
    elif average_ping <= 100:
        status = "good"
    elif average_ping <= 200:
        status = "average"
    else:
        status = "poor"

    return {
        "target": target,
        "packets_sent": packet_count,
        "packets_received": len(ping_times),
        "packet_loss": round(packet_loss, 2),
        "ping_ms": round(average_ping, 2),
        "min_ping_ms": round(min(ping_times), 2),
        "max_ping_ms": round(max(ping_times), 2),
        "jitter_ms": round(jitter, 2),
        "samples": ping_times,
        "status": status,
    }


@app.get("/api/diagnostic-profiles")
def get_diagnostic_profiles():
    return {"default": None, "profiles": list_profiles()}


@app.get("/api/network-quality")
def network_quality(profile: str | None = Query(default=None)):
    # No profile: exactly the original behaviour (backward compatible).
    if profile is None:
        return measure_ping(DEFAULT_PACKET_COUNT)

    try:
        selected = get_profile(profile)
    except UnknownProfileError:
        valid = [p["id"] for p in list_profiles()]
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown diagnostic profile '{profile}'.",
                "valid_profiles": valid,
            },
        )

    return build_profile_result(selected, measure_ping(selected.packet_count))


# ============================================================

# SAVE NETWORK TEST

# ============================================================



@app.post("/api/network-test")

def save_network_test(data: NetworkTest):



    timestamp = (

        data.timestamp

        or current_utc_timestamp()

    )





    with history_database(HISTORY_SAVE_ERROR) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO network_tests (
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                network_type,
                connectivity_score,
                latitude,
                longitude
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                data.download_mbps,
                data.upload_mbps,
                data.ping_ms,
                data.jitter_ms,
                data.packet_loss,
                data.network_type,
                data.connectivity_score,
                data.latitude,
                data.longitude
            )
        )
        connection.commit()
        test_id = cursor.lastrowid





    return {



        "status": "success",



        "message": "Network test saved",



        "id": test_id

    }





# ============================================================

# NETWORK HISTORY

# ============================================================


HISTORY_RANGE_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "recent": timedelta(days=1),
    # Preserve existing API range values for compatibility.
    "hourly": timedelta(hours=24),
    "daily": timedelta(days=7),
    "weekly": timedelta(days=30),
    "monthly": timedelta(days=365),
}

# Chronological order by UTC instant; id breaks ties between identical
# instants. Records whose timestamp cannot be parsed come last.
HISTORY_ORDER_BY = (
    " ORDER BY canonical_utc(timestamp) IS NULL ASC,"
    " canonical_utc(timestamp) ASC, id ASC"
)


def history_record(row):
    """Return a history row with its timestamp in canonical UTC form.

    The stored value is never changed. A legacy value that cannot be
    parsed is returned as stored, so the record stays accessible.
    """
    record = dict(row)
    record["timestamp"] = to_canonical_utc(record["timestamp"]) or record["timestamp"]
    return record

DEFAULT_NETWORK_HISTORY_PAGE_SIZE = 100
MAX_NETWORK_HISTORY_PAGE_SIZE = 500


@app.get("/api/network-history")
def get_network_history(
    range: str = "recent",
    start_date: date | None = None,
    end_date: date | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_score: float | None = Query(default=None, ge=0, le=100),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=MAX_NETWORK_HISTORY_PAGE_SIZE,
        description="Maximum number of records to return (1-500).",
    ),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Number of matching records to skip.",
    ),
):
    if range != "all" and range not in HISTORY_RANGE_WINDOWS:
        supported = ", ".join(["all", *HISTORY_RANGE_WINDOWS])
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported range '{range}'. Supported values: {supported}",
        )

    # Validate date range.
    if (
        start_date is not None
        and end_date is not None
        and start_date > end_date
    ):
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Validate connectivity score range.
    if (
        min_score is not None
        and max_score is not None
        and min_score > max_score
    ):
        raise HTTPException(
            status_code=422,
            detail="min_score must be less than or equal to max_score",
        )

    with history_database(HISTORY_READ_ERROR) as connection:
        cursor = connection.cursor()

        conditions = []
        parameters = []

        # Stored timestamps are compared by their UTC instant, so records
        # in different formats and offsets filter correctly (issue #39).
        # Canonical UTC strings have a fixed width, so text comparison of
        # canonical values is chronological. Values that cannot be parsed
        # become NULL and are left out of time filters.

        # Preserve the existing time-range behaviour
        # whenever a custom date range is not supplied.
        if start_date is None and end_date is None:
            if range != "all":
                duration = HISTORY_RANGE_WINDOWS[range]
                since = datetime.now(timezone.utc) - duration
                conditions.append("canonical_utc(timestamp) >= ?")
                parameters.append(to_canonical_utc(since.isoformat()))

        else:
            # Calendar dates are UTC days.
            if start_date is not None:
                conditions.append("canonical_utc(timestamp) >= ?")
                parameters.append(utc_day_start(start_date))

            if end_date is not None:
                # Exclusive upper boundary includes the entire end date.
                end_exclusive = end_date + timedelta(days=1)

                conditions.append("canonical_utc(timestamp) < ?")
                parameters.append(utc_day_start(end_exclusive))

        if min_score is not None:
            conditions.append("connectivity_score >= ?")
            parameters.append(min_score)

        if max_score is not None:
            conditions.append("connectivity_score <= ?")
            parameters.append(max_score)

        query = """
             SELECT
                id,
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                network_type,
                connectivity_score,
                latitude,
                longitude
            FROM network_tests
        """

        where_clause = (
            " WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        query += where_clause

        if limit is not None or offset is not None:
            page_limit = (
                limit if limit is not None else DEFAULT_NETWORK_HISTORY_PAGE_SIZE
            )
            page_offset = offset if offset is not None else 0

            # Count the filtered records before applying page bounds.
            cursor.execute(
                "SELECT COUNT(*) FROM network_tests" + where_clause,
                parameters,
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                query + HISTORY_ORDER_BY + " LIMIT ? OFFSET ?",
                parameters + [page_limit, page_offset],
            )
            records = [history_record(row) for row in cursor.fetchall()]
            next_offset = page_offset + len(records)
            has_more = next_offset < total

            return {
                "data": records,
                "pagination": {
                    "limit": page_limit,
                    "offset": page_offset,
                    "total": total,
                    "has_more": has_more,
                    "next_offset": next_offset if has_more else None,
                },
            }

        # Keep the original list response for existing callers.
        cursor.execute(query + HISTORY_ORDER_BY, parameters)
        return [history_record(row) for row in cursor.fetchall()]



# ============================================================
# AI STATUS
# ============================================================

@app.get("/api/ai/status")
def ai_status():
    data = load_network_data() if AI_IMPORT_ERROR is None else []

    return {
        "success": AI_MODELS_READY,
        "message": AI_MODELS_MESSAGE,
        "prediction_model": {
            "name": "HistGradientBoosting",
            "loaded": FINAL_PREDICTOR_READY,
        },
        "anomaly_model": {
            "name": "Transformer Autoencoder",
            "loaded": ai_anomaly_model is not None,
        },
        "records_available": len(data),
        "sequence_length": SEQUENCE_LENGTH,
    }


# ============================================================
# AI PREDICTION - HISTGRADIENTBOOSTING
# ============================================================

@app.get("/api/ai/prediction")
def ai_prediction():
    if not FINAL_PREDICTOR_READY:
        raise HTTPException(
            status_code=503,
            detail=getattr(final_predictor, "message", AI_MODELS_MESSAGE),
        )

    try:
        predicted_score = final_predictor.predict()

        if predicted_score >= 80:
            quality = "Excellent"
        elif predicted_score >= 60:
            quality = "Good"
        elif predicted_score >= 40:
            quality = "Fair"
        else:
            quality = "Poor"

        return {
            "success": True,
            "model": "HistGradientBoosting",
            "input_records": SEQUENCE_LENGTH,
            "training_records": final_predictor.record_count,
            "training_samples": final_predictor.training_samples,
            "predicted_connectivity_score": round(
                predicted_score,
                2,
            ),
            "predicted_quality": quality,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Prediction failed: {error}",
        )

# ============================================================
# AI ANOMALY
# ============================================================

@app.get("/api/ai/anomaly")
def ai_anomaly():
    if (
        not AI_MODELS_READY
        or ai_anomaly_model is None
        or ai_scaler is None
    ):
        raise HTTPException(
            status_code=503,
            detail=AI_MODELS_MESSAGE,
        )

    data = load_network_data()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="No complete network record is available.",
        )

    latest = data[-1]

    try:
        normalized = normalize_values(
            latest["values"],
            ai_scaler,
        )

        sample = torch.tensor(
            normalized,
            dtype=torch.float32,
        ).reshape(1, 1, len(FEATURES))

        with torch.no_grad():
            reconstructed = ai_anomaly_model(sample)
            target = sample[:, -1, :]
            reconstruction_error = torch.mean(
                (reconstructed - target) ** 2
            ).item()

        if not math.isfinite(reconstruction_error):
            raise ValueError(
                "The model returned a non-finite reconstruction error."
            )

        explanation = build_anomaly_explanation(
            FEATURES,
            latest["values"],
            target.reshape(-1).tolist(),
            reconstructed.reshape(-1).tolist(),
            ai_scaler,
        )

        threshold = float(ai_anomaly_threshold or 0.05)
        if not math.isfinite(threshold):
            raise ValueError("The anomaly threshold is not finite.")
        is_anomaly = reconstruction_error > threshold

        return {
            "success": True,
            "model": "Transformer Autoencoder",
            "timestamp": latest["timestamp"],
            "anomaly": bool(is_anomaly),
            "reconstruction_error": round(
                float(reconstruction_error),
                6,
            ),
            "threshold": round(threshold, 6),
            "status": (
                "Anomaly detected"
                if is_anomaly
                else "No anomaly detected"
            ),
            "explanation": explanation,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Anomaly detection failed: {error}",
        )


# ============================================================
# COMBINED AI ANALYSIS
# ============================================================

@app.get("/api/ai/analyze")
def ai_analyze():
    if not AI_MODELS_READY:
        return {
            "success": False,
            "available": False,
            "message": AI_MODELS_MESSAGE,
            "prediction": None,
            "anomaly": None,
        }

    return {
        "success": True,
        "prediction": ai_prediction(),
        "anomaly": ai_anomaly(),
    }


# ============================================================

# DELETE NETWORK HISTORY

# ============================================================



@app.delete("/api/network-history")

def delete_network_history():



    with history_database(HISTORY_DELETE_ERROR) as connection:
        connection.execute("DELETE FROM network_tests")
        connection.commit()





    return {

        "status": "success",

        "message": "Network history deleted"

    }





# ============================================================

# RUN SERVER

# ============================================================



if __name__ == "__main__":



    import uvicorn



    uvicorn.run(

        "backend.main:app",

        host="127.0.0.1",

        port=8000,

        reload=True

    )