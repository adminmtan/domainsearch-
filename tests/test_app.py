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


def test_generate_includes_warning_when_fewer_available(monkeypatch):
    """审查重点 2: 当可用域名 < 请求数量时，响应必须含 warning 字段。"""
    # Mock generator to return candidates
    monkeypatch.setattr(
        "app.OpenAIGenerator",
        lambda **kw: _FakeGenerator(["mythforge", "codebase"]),
    )
    # Mock checker so only one is available
    monkeypatch.setattr(
        "app.check_domains",
        lambda domains, tlds, timeout: {d: ("available" if d == "mythforge.com" else "registered") for d in domains},
    )
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "开发者工具",
        "min_len": 4, "max_len": 12, "tlds": ["com"], "count": 5,
        "api_key": "sk-test",
    })
    assert resp.status_code == 200
    data = resp.json
    assert data["success"] is True
    assert len(data["domains"]) == 1
    assert data["stats"]["requested"] == 5
    assert data["stats"]["available"] == 1
    # New behavior: warning key is present when available < requested
    assert "warning" in data
    assert "1" in data["warning"] and "5" in data["warning"]


class _FakeGenerator:
    def __init__(self, *a, **kw):
        self.domains = ["mythforge", "codebase"]

    def generate(self, description, min_len, max_len, count):
        return [{"domain": d, "reason": f"reason for {d}"} for d in self.domains]