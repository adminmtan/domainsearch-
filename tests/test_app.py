import json
from app import app


def test_generate_rejects_empty_description():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "   ",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 5,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400
    assert resp.json["success"] is False


def test_generate_rejects_invalid_length_range():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 10, "max_len": 5, "tlds": ["com"], "count": 5,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400


def test_generate_rejects_count_out_of_range():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 100,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400


def test_generate_rejects_missing_api_key():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 5,
        "api_key": "",
    })
    assert resp.status_code == 400


def test_tlds_returns_list():
    client = app.test_client()
    resp = client.get("/api/tlds")
    assert resp.status_code == 200
    assert "tlds" in resp.json
    assert isinstance(resp.json["tlds"], list)
    assert "com" in resp.json["tlds"]
    assert len(resp.json["tlds"]) >= 10