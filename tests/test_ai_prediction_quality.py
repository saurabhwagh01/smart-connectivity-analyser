import pytest

import backend.main as main


@pytest.mark.parametrize(
    "score, expected_quality",
    [
        (39, "Poor"),
        (40, "Fair"),
        (59, "Fair"),
        (60, "Good"),
        (79, "Good"),
        (80, "Excellent"),
    ],
)
def test_ai_prediction_quality_boundaries(
    client,
    monkeypatch,
    score,
    expected_quality,
):
    class FakePredictor:
        record_count = 100
        training_samples = 50


        def predict(self):
            return score

    monkeypatch.setattr(
        main,
        "final_predictor",
        FakePredictor(),
    )
    monkeypatch.setattr(
        main,
        "FINAL_PREDICTOR_READY",
        True,
    )

    response = client.get("/api/ai/prediction")

    assert response.status_code == 200

    result = response.json()

    assert result["predicted_connectivity_score"] == score
    assert result["predicted_quality"] == expected_quality