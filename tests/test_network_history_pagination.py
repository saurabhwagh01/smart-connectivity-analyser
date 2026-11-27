from test_network_test_validation import VALID_TEST, post_test


def save_history_record(client, timestamp, score):
    response = post_test(
        client,
        {
            **VALID_TEST,
            "timestamp": timestamp,
            "connectivity_score": score,
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_pages_are_stable_and_include_pagination_metadata(client):
    timestamp = "2026-11-01T10:00:00.000Z"
    inserted_ids = [
        save_history_record(client, timestamp, 60 + index)
        for index in range(5)
    ]

    pages = []
    for offset in (0, 2, 4):
        response = client.get(
            "/api/network-history",
            params={"range": "all", "limit": 2, "offset": offset},
        )

        assert response.status_code == 200
        payload = response.json()
        pages.extend(record["id"] for record in payload["data"])
        assert payload["pagination"] == {
            "limit": 2,
            "offset": offset,
            "total": 5,
            "has_more": offset < 4,
            "next_offset": offset + 2 if offset < 4 else None,
        }

    assert pages == inserted_ids


def test_limit_or_offset_alone_uses_defaults(client):
    inserted_ids = [
        save_history_record(
            client,
            f"2026-11-0{index + 1}T10:00:00.000Z",
            60 + index,
        )
        for index in range(3)
    ]

    first_page = client.get(
        "/api/network-history",
        params={"range": "all", "limit": 2},
    ).json()
    later_page = client.get(
        "/api/network-history",
        params={"range": "all", "offset": 1},
    ).json()

    assert [item["id"] for item in first_page["data"]] == inserted_ids[:2]
    assert first_page["pagination"]["offset"] == 0
    assert first_page["pagination"]["limit"] == 2
    assert [item["id"] for item in later_page["data"]] == inserted_ids[1:]
    assert later_page["pagination"]["limit"] == 100


def test_filters_are_applied_before_pagination(client):
    records = [
        ("2026-11-01T10:00:00.000Z", 70),
        ("2026-11-02T10:00:00.000Z", 80),
        ("2026-11-03T10:00:00.000Z", 90),
        ("2026-11-04T10:00:00.000Z", 95),
    ]
    for timestamp, score in records:
        save_history_record(client, timestamp, score)

    response = client.get(
        "/api/network-history",
        params={
            "start_date": "2026-11-01",
            "end_date": "2026-11-04",
            "min_score": 60,
            "max_score": 90,
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["connectivity_score"] for item in payload["data"]] == [80]
    assert payload["pagination"] == {
        "limit": 1,
        "offset": 1,
        "total": 3,
        "has_more": True,
        "next_offset": 2,
    }


def test_empty_pages_report_filtered_total(client):
    save_history_record(client, "2026-11-01T10:00:00.000Z", 80)

    response = client.get(
        "/api/network-history",
        params={"range": "all", "limit": 10, "offset": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "pagination": {
            "limit": 10,
            "offset": 5,
            "total": 1,
            "has_more": False,
            "next_offset": None,
        },
    }


def test_invalid_page_bounds_are_rejected(client):
    for params in ({"limit": 0}, {"limit": -1}, {"limit": 501}, {"offset": -1}):
        response = client.get(
            "/api/network-history",
            params={"range": "all", **params},
        )
        assert response.status_code == 422


def test_legacy_request_keeps_list_response(client):
    inserted_id = save_history_record(client, "2026-11-01T10:00:00.000Z", 80)

    response = client.get("/api/network-history", params={"range": "all"})

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert [item["id"] for item in response.json()] == [inserted_id]

