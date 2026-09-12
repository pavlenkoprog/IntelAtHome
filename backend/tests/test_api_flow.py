from fastapi.testclient import TestClient


def test_dataset_entity_investigation_flow(client: TestClient) -> None:
    dataset = client.post(
        "/api/v1/datasets",
        json={"name": "OSINT dump", "source_type": "csv", "description": "seed"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    entity = client.post(
        "/api/v1/entities",
        json={
            "name": "Alice",
            "entity_type": "person",
            "dataset_id": dataset_id,
            "description": "analyst",
        },
    )
    assert entity.status_code == 201
    entity_id = entity.json()["id"]

    investigation = client.post(
        "/api/v1/investigations",
        json={
            "title": "Case 001",
            "description": "first case",
            "entity_ids": [entity_id],
        },
    )
    assert investigation.status_code == 201
    body = investigation.json()
    assert body["title"] == "Case 001"
    assert body["entities"][0]["name"] == "Alice"

    assert client.get("/api/v1/datasets").status_code == 200
    assert client.get("/api/v1/entities").status_code == 200
    assert client.get("/api/v1/investigations").status_code == 200
    assert client.get("/").status_code == 200
