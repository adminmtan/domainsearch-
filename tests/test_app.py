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


def test_static_responses_have_no_cache():
    """防止浏览器缓存旧版静态资源导致按钮事件未绑定等诡异问题。"""
    client = app.test_client()
    for path in ("/", "/static/app.js", "/static/style.css"):
        resp = client.get(path)
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc or "no-cache" in cc, (
            f"{path} missing no-cache header: {cc!r}"
        )


def test_validate_key_rejects_empty():
    client = app.test_client()
    resp = client.post("/api/validate-key", json={"api_key": ""})
    assert resp.status_code == 400
    assert resp.json["success"] is False


def test_validate_key_succeeds(monkeypatch):
    """成功路径：mock OpenAI client.models.list() 返回伪模型列表。"""
    class _M:
        def __init__(self, id):
            self.id = id
    class _ModelsResp:
        def __init__(self):
            self.data = [_M("gpt-4o-mini"), _M("gpt-4o")]
    class _ModelsAPI:
        def list(self):
            return _ModelsResp()
    class _Client:
        def __init__(self, **kw):
            self.kw = kw
        @property
        def models(self):
            return _ModelsAPI()
    import app as app_module
    monkeypatch.setattr(app_module, "OpenAI", _Client)

    client = app.test_client()
    resp = client.post("/api/validate-key", json={
        "api_key": "sk-good",
        "base_url": "https://api.openai.com/v1",
    })
    assert resp.status_code == 200
    data = resp.json
    assert data["success"] is True
    assert data["model_count"] == 2
    assert "gpt-4o-mini" in data["sample_models"]


def test_validate_key_fails_on_401(monkeypatch):
    """失败路径：OpenAI 返回 401 → success=False，错误信息含 '401' 或 'Invalid'。"""
    class _ModelsAPI:
        def list(self):
            import openai
            raise openai.AuthenticationError(
                message="Incorrect API key provided",
                response=type("R", (), {
                    "status_code": 401,
                    "headers": {},
                    "request": type("Req", (), {})(),
                })(),
                body=None,
            )
    class _Client:
        def __init__(self, **kw):
            pass
        @property
        def models(self):
            return _ModelsAPI()
    import app as app_module
    monkeypatch.setattr(app_module, "OpenAI", _Client)

    client = app.test_client()
    resp = client.post("/api/validate-key", json={
        "api_key": "sk-bad",
    })
    assert resp.status_code == 200
    data = resp.json
    assert data["success"] is False
    assert "error" in data
    # 不应回显 api_key
    assert "sk-bad" not in data["error"]


def test_validate_key_network_error_includes_base_url(monkeypatch):
    """网络错误的消息应包含 base_url，便于用户排查。"""
    class _ModelsAPI:
        def list(self):
            import openai
            raise openai.APIConnectionError(request=None)
    class _Client:
        def __init__(self, **kw):
            pass
        @property
        def models(self):
            return _ModelsAPI()
    import app as app_module
    monkeypatch.setattr(app_module, "OpenAI", _Client)

    client = app.test_client()
    resp = client.post("/api/validate-key", json={
        "api_key": "sk-x",
        "base_url": "https://my-proxy.example.com/v1",
    })
    assert resp.status_code == 200
    assert resp.json["success"] is False
    assert "https://my-proxy.example.com/v1" in resp.json["error"]


def test_validate_key_handles_network_error(monkeypatch):
    """网络/连接错误：返回 success=False + 可读错误。"""
    class _ModelsAPI:
        def list(self):
            import openai
            raise openai.APIConnectionError(request=None)
    class _Client:
        def __init__(self, **kw):
            pass
        @property
        def models(self):
            return _ModelsAPI()
    import app as app_module
    monkeypatch.setattr(app_module, "OpenAI", _Client)

    client = app.test_client()
    resp = client.post("/api/validate-key", json={"api_key": "sk-x"})
    assert resp.status_code == 200
    assert resp.json["success"] is False
    assert "error" in resp.json


def test_validate_key_uses_default_base_url(monkeypatch):
    """未传 base_url 时使用默认值。"""
    seen = {}
    class _ModelsAPI:
        def list(self):
            class _M:
                data = []
            return _M()
    class _Client:
        def __init__(self, **kw):
            seen.update(kw)
        @property
        def models(self):
            return _ModelsAPI()
    import app as app_module
    monkeypatch.setattr(app_module, "OpenAI", _Client)

    client = app.test_client()
    resp = client.post("/api/validate-key", json={"api_key": "sk-x"})
    assert resp.status_code == 200
    assert seen.get("base_url") == "https://api.openai.com/v1"
    assert seen.get("api_key") == "sk-x"


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