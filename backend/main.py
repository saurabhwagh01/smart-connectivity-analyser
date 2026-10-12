from fastapi import FastAPI, HTTPException

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from pathlib import Path

import sqlite3
import json
import math
import sys

import subprocess

import re

import statistics
from datetime import datetime, timedelta

# ============================================================
# AI MODEL IMPORTS
# ============================================================

AI_BACKEND_DIR = Path(__file__).resolve().parent
if str(AI_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(AI_BACKEND_DIR))

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



    return connection





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
from backend.final_predictor import final_predictor, FINAL_PREDICTOR_READY
AI_MODELS_READY, AI_MODELS_MESSAGE = load_ai_models()




# ============================================================

# DATA MODEL

# ============================================================



class NetworkTest(BaseModel):



    timestamp: str | None = None



    download_mbps: float | None = None



    upload_mbps: float | None = None



    ping_ms: float | None = None



    jitter_ms: float | None = None



    packet_loss: float | None = None



    network_type: str | None = "Unknown"



    connectivity_score: float | None = None



    latitude: float | None = None



    longitude: float | None = None





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

# SIMPLE PING

# ============================================================



@app.get("/api/ping")

def ping():



    return {

        "message": "Backend is running",

        "status": "ok"

    }





# ============================================================

# NETWORK QUALITY

# WINDOWS PING

# ============================================================



@app.get("/api/network-quality")

def network_quality():



    target = "1.1.1.1"



    packet_count = 10



    timeout_ms = 2000



    command = [

        "ping",

        target,

        "-n",

        str(packet_count),

        "-w",

        str(timeout_ms)

    ]



    try:



        process = subprocess.run(

            command,

            capture_output=True,

            text=True,

            timeout=30

        )



        output = process.stdout



    except subprocess.TimeoutExpired:



        raise HTTPException(

            status_code=504,

            detail="Ping measurement timed out."

        )



    except Exception as error:



        raise HTTPException(

            status_code=500,

            detail=f"Ping measurement failed: {error}"

        )





    # ========================================================

    # PARSE INDIVIDUAL PING TIMES

    # ========================================================



    ping_times = []



    matches = re.findall(

        r"time[=<]\s*(\d+)\s*ms",

        output,

        re.IGNORECASE

    )





    for match in matches:



        try:



            ping_times.append(

                float(match)

            )



        except ValueError:

            pass





    # ========================================================

    # PACKET LOSS

    # ========================================================



    loss_match = re.search(

        r"\((\d+)%\s*loss\)",

        output,

        re.IGNORECASE

    )





    if loss_match:



        packet_loss = float(

            loss_match.group(1)

        )



    else:



        packet_loss = (

            (

                packet_count -

                len(ping_times)

            )

            / packet_count

        ) * 100





    # ========================================================

    # NO RESPONSE

    # ========================================================



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

            "status": "unreachable"

        }





    # ========================================================

    # PING STATISTICS

    # ========================================================



    average_ping = statistics.mean(

        ping_times

    )



    minimum_ping = min(

        ping_times

    )



    maximum_ping = max(

        ping_times

    )





    # ========================================================

    # JITTER

    #

    # Mean absolute difference between consecutive

    # successful ping measurements.

    # ========================================================



    if len(ping_times) >= 2:



        differences = []



        for i in range(

            1,

            len(ping_times)

        ):



            difference = abs(

                ping_times[i] -

                ping_times[i - 1]

            )



            differences.append(

                difference

            )





        jitter = statistics.mean(

            differences

        )



    else:



        jitter = 0.0





    # ========================================================

    # STATUS

    # ========================================================



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



        "packets_received": len(

            ping_times

        ),



        "packet_loss": round(

            packet_loss,

            2

        ),



        "ping_ms": round(

            average_ping,

            2

        ),



        "min_ping_ms": round(

            minimum_ping,

            2

        ),



        "max_ping_ms": round(

            maximum_ping,

            2

        ),



        "jitter_ms": round(

            jitter,

            2

        ),



        "samples": ping_times,



        "status": status

    }





# ============================================================

# SAVE NETWORK TEST

# ============================================================



@app.post("/api/network-test")

def save_network_test(data: NetworkTest):



    timestamp = (

        data.timestamp

        or datetime.now().isoformat()

    )





    connection = get_connection()



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



    connection.close()





    return {



        "status": "success",



        "message": "Network test saved",



        "id": test_id

    }





# ============================================================

# NETWORK HISTORY

# ============================================================



@app.get("/api/network-history")

def get_network_history(

    range: str = "recent"

):



    connection = get_connection()



    cursor = connection.cursor()





    if range == "hourly":



        since = datetime.now() - timedelta(

            hours=24

        )



    elif range == "daily":



        since = datetime.now() - timedelta(

            days=7

        )



    elif range == "weekly":



        since = datetime.now() - timedelta(

            days=30

        )



    elif range == "monthly":



        since = datetime.now() - timedelta(

            days=365

        )



    else:



        since = datetime.now() - timedelta(

            days=1

        )





    cursor.execute(

        """

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



        WHERE timestamp >= ?



        ORDER BY timestamp ASC

        """,



        (

            since.isoformat(),

        )

    )





    rows = cursor.fetchall()



    connection.close()





    return [

        dict(row)

        for row in rows

    ]






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
            detail=final_predictor.message,
        )

    try:
        predicted_score = final_predictor.predict()

        if predicted_score >= 75:
            quality = "Excellent"
        elif predicted_score >= 50:
            quality = "Good"
        elif predicted_score >= 25:
            quality = "Average"
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

        threshold = float(ai_anomaly_threshold or 0.05)
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



    connection = get_connection()



    cursor = connection.cursor()



    cursor.execute(

        "DELETE FROM network_tests"

    )



    connection.commit()



    connection.close()





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