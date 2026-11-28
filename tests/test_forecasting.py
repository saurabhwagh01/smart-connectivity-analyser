from datetime import datetime, timedelta, timezone

import pytest

from backend import main
from backend.forecasting import (
    FORECAST_METRICS,
    generate_connectivity_forecast,
    parse_horizons,
)


def _insert_record(
    timestamp: str,
    *,
    download_mbps: float | None = 50.0,
    upload_mbps: float | None = 20.0,
    ping_ms: float | None = 25.0,
    jitter_ms: float | None = 3.0,
    packet_loss: float | None = 0.2,
    connectivity_score: float | None = 85.0,
):
    connection = main.get_connection()
    try:
        connection.execute(
            """
            INSERT INTO network_tests (
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                network_type,
                connectivity_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                "Wi-Fi",
                connectivity_score,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _seed_series(scores, downloads, pings, losses, start=None, step_hours=1):
    base = start or datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    for idx, (score, dl, ping, loss) in enumerate(
        zip(scores, downloads, pings, losses)
    ):
        ts = (base + timedelta(hours=idx * step_hours)).isoformat()
        _insert_record(
            ts,
            download_mbps=dl,
            upload_mbps=max(1.0, dl * 0.4),
            ping_ms=ping,
            jitter_ms=max(0.5, ping * 0.12),
            packet_loss=loss,
            connectivity_score=score,
        )


def test_parse_horizons_validation():
    assert parse_horizons(None) == [("1h", 1), ("6h", 6), ("24h", 24)]
    assert parse_horizons("1h, 6h, 1h") == [("1h", 1), ("6h", 6)]
    assert parse_horizons("12h") == [("12h", 12)]

    for bad in ("", "   ", "invalid", "0h", "-5h", "169h", "1h,", "1d"):
        with pytest.raises(ValueError):
            parse_horizons(bad)

    with pytest.raises(ValueError):
        parse_horizons(",".join(f"{i}h" for i in range(1, 12)))


def test_forecast_empty_database_uses_safe_sparse_fallback(client):
    response = client.get("/api/predict/forecast")
    assert response.status_code == 200
    body = response.json()

    assert body["success"] is True
    assert body["history_summary"]["total_records"] == 0
    assert body["history_summary"]["sufficient_history"] is False
    assert body["history_summary"]["fallback_used"] is True
    assert body["history_summary"]["method"] == "sparse_fallback"
    assert body["degradation_risk"]["level"] == "Insufficient Data"
    assert body["degradation_risk"]["score"] is None
    assert [h["horizon"] for h in body["horizons"]] == ["1h", "6h", "24h"]
    for h in body["horizons"]:
        assert h["degradation_risk"]["level"] == "Insufficient Data"
        assert h["degradation_risk"]["score"] is None
        for field in FORECAST_METRICS:
            assert h["metrics"][field]["predicted"] is None
            assert h["metrics"][field]["trend"] == "unavailable"


def test_forecast_single_record_sparse_fallback_bounds(client):
    _insert_record(
        "2026-11-26T10:00:00+00:00",
        download_mbps=60.0,
        upload_mbps=22.0,
        ping_ms=28.0,
        jitter_ms=4.0,
        packet_loss=0.5,
        connectivity_score=84.0,
    )

    response = client.get("/api/predict/forecast?horizons=1h,6h,24h")
    assert response.status_code == 200
    body = response.json()

    assert body["history_summary"]["total_records"] == 1
    assert body["history_summary"]["fallback_used"] is True
    assert body["history_summary"]["sufficient_history"] is False
    assert body["history_summary"]["method"] == "sparse_fallback"
    assert body["degradation_risk"]["level"] == "Insufficient Data"
    assert body["degradation_risk"]["score"] is None

    widths = []
    for h in body["horizons"]:
        assert h["degradation_risk"]["level"] == "Insufficient Data"
        assert h["degradation_risk"]["score"] is None
        conn = h["metrics"]["connectivity_score"]
        assert 0.0 <= conn["lower"] <= conn["predicted"] <= conn["upper"] <= 100.0
        widths.append(conn["upper"] - conn["lower"])
        for field in ("download_mbps", "upload_mbps", "ping_ms", "jitter_ms"):
            m = h["metrics"][field]
            assert 0.0 <= m["lower"] <= m["predicted"] <= m["upper"]
        loss = h["metrics"]["packet_loss"]
        assert 0.0 <= loss["lower"] <= loss["predicted"] <= loss["upper"] <= 100.0

    assert widths[0] <= widths[1] <= widths[2]


def test_forecast_rolling_trend_and_confidence_bounds(client):
    _seed_series(
        scores=[82, 84, 86, 85, 88, 90],
        downloads=[55, 58, 60, 59, 63, 66],
        pings=[28, 26, 25, 24, 22, 20],
        losses=[0.2, 0.1, 0.1, 0.2, 0.1, 0.0],
    )

    response = client.get("/api/predict/forecast?horizons=1h,6h,24h")
    assert response.status_code == 200
    body = response.json()

    assert body["history_summary"]["total_records"] == 6
    assert body["history_summary"]["sufficient_history"] is True
    assert body["history_summary"]["fallback_used"] is False
    assert body["history_summary"]["method"] == "rolling_trend_damped"
    assert body["history_summary"]["rolling_windows"]["6h"]["count"] == 6
    assert body["degradation_risk"]["level"] == "Low"
    assert body["degradation_risk"]["score"] < 35

    for h in body["horizons"]:
        for field, spec in FORECAST_METRICS.items():
            m = h["metrics"][field]
            assert m["predicted"] is not None
            assert m["lower"] <= m["predicted"] <= m["upper"]
            assert m["lower"] >= spec["min"]
            if spec["max"] is not None:
                assert m["upper"] <= spec["max"]


def test_forecast_risk_classification_moderate_and_high():
    base = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    moderate_records = [
        {
            "timestamp": (base + timedelta(hours=i)).isoformat(),
            "download_mbps": 50 - i * 1.5,
            "upload_mbps": 20 - i * 0.4,
            "ping_ms": 30 + i * 2.0,
            "jitter_ms": 4 + i * 0.5,
            "packet_loss": 0.1 + i * 0.1,
            "connectivity_score": 82 - i * 2.0,
        }
        for i in range(6)
    ]
    moderate_res = generate_connectivity_forecast(moderate_records, now=base)
    assert moderate_res["degradation_risk"]["level"] == "Moderate"
    assert 35 <= moderate_res["degradation_risk"]["score"] < 65
    assert len(moderate_res["degradation_risk"]["reasons"]) >= 1

    high_records = [
        {
            "timestamp": (base + timedelta(hours=i)).isoformat(),
            "download_mbps": 40 - i * 6.0,
            "upload_mbps": 12 - i * 1.5,
            "ping_ms": 70 + i * 22,
            "jitter_ms": 18 + i * 5,
            "packet_loss": 1.0 + i * 1.3,
            "connectivity_score": 68 - i * 9.0,
        }
        for i in range(6)
    ]
    high_res = generate_connectivity_forecast(high_records, now=base)
    assert high_res["degradation_risk"]["level"] == "High"
    assert high_res["degradation_risk"]["score"] >= 65
    assert len(high_res["degradation_risk"]["reasons"]) >= 1


def test_forecast_endpoint_validation_and_custom_horizons(client):
    _seed_series(
        scores=[80, 82, 83, 85],
        downloads=[50, 52, 53, 55],
        pings=[25, 24, 23, 22],
        losses=[0.1, 0.1, 0.0, 0.0],
    )

    ok_resp = client.get("/api/predict/forecast?horizons=1h,12h")
    assert ok_resp.status_code == 200
    assert [h["horizon"] for h in ok_resp.json()["horizons"]] == ["1h", "12h"]

    for bad_query in ("", "invalid", "0h", "-1h", "300h"):
        bad_resp = client.get(f"/api/predict/forecast?horizons={bad_query}")
        assert bad_resp.status_code == 422


def test_forecast_endpoint_returns_500_on_db_error(client, monkeypatch):
    def broken_conn():
        raise RuntimeError("sqlite unavailable")

    monkeypatch.setattr(main, "get_connection", broken_conn)
    response = client.get("/api/predict/forecast")
    assert response.status_code == 500
    assert "Failed to connect to database" in response.json()["detail"]
