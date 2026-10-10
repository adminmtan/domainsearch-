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


def test_generate_rejects_invalid_domain_style():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 5,
        "domain_style": "emoji",
        "api_key": "sk-test",
    })
    assert resp.status_code == 400
    assert "domain_style" in resp.json["error"]


def test_generate_accepts_valid_domain_style(monkeypatch):
    """两个合法风格都能过校验。"""
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            return [{"domain": "abc", "reason": "r"}]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr("app.check_domains", lambda d, t, **kw: {x: "available" for x in d})
    client = app.test_client()
    for style in ("letters", "letters_and_digits"):
        resp = client.post("/api/generate", json={
            "description": "x",
            "min_len": 3, "max_len": 6, "tlds": ["com"], "count": 1,
            "domain_style": style,
            "api_key": "sk-test",
        })
        assert resp.status_code == 200, f"style={style}: {resp.status_code} {resp.get_data(as_text=True)[:200]}"


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

    def generate(self, description, min_len, max_len, count, domain_style=None):
        return [{"domain": d, "reason": f"reason for {d}"} for d in self.domains]


# ---------- SSE 流式生成 ----------

def _parse_sse_events(body: str):
    """解析 SSE 文本为 [(event_name, data_dict), ...]。"""
    events = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev = "message"
        data_lines = []
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        try:
            data = json.loads("\n".join(data_lines))
        except Exception:
            data = {"_raw": "\n".join(data_lines)}
        events.append((ev, data))
    return events


def test_stream_rejects_empty_description():
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "  ", "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 5,
    })
    assert resp.status_code == 400


def test_stream_stops_when_count_reached(monkeypatch):
    """循环应在 available 达到 count 时停止，并发 done 事件。"""
    # count=1：第一次 generator 返回 1 个候选就够 → 应只跑 1 批
    gen_calls = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            gen_calls["n"] += 1
            return [{"domain": f"d{gen_calls['n']}", "reason": "r"}]

    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr(
        "app.check_domains_with_errors",
        lambda domains, tlds, timeout: (
            {d: "available" for d in domains}, {}
        ),
    )
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    events = _parse_sse_events(resp.get_data(as_text=True))
    types = [t for t, _ in events]
    assert "start" in types
    assert "done" in types
    done = next(d for t, d in events if t == "done")
    assert len(done["domains"]) == 1
    assert done["stats"]["batches"] == 1
    assert gen_calls["n"] == 1


def test_stream_retries_when_no_available(monkeypatch):
    """第 1 批 0 个可注册 → 后端必须继续第 2 批。"""
    gen_calls = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            gen_calls["n"] += 1
            return [{"domain": f"d{gen_calls['n']}", "reason": "r"}]

    def fake_check(domains, tlds, timeout):
        # 第 1 批全 registered；第 2 批全 available
        result = {}
        for d in domains:
            if d.startswith("d1."):
                result[d] = "registered"
            else:
                result[d] = "available"
        return result, {}  # (statuses, errors) — dmcheck 流式 mock 形状

    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr("app.check_domains_with_errors", fake_check)
    # 该测试无 unknown 域名，不需要 mock retry；保留以防未来扩展。
    def fake_retry_stuck(domains, *, timeout, **kwargs):
        return {d: "unknown" for d in domains}, {d: "timeout after 5.0s" for d in domains}, 1
    monkeypatch.setattr("app.retry_unknown_domains", fake_retry_stuck)
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    types = [t for t, _ in events]
    assert "done" in types
    done = next(d for t, d in events if t == "done")
    assert done["stats"]["batches"] >= 2, f"应至少 2 批，实际 {done['stats']['batches']}"
    assert len(done["domains"]) == 1
    assert gen_calls["n"] >= 2


def test_stop_endpoint_rejects_unknown_job():
    client = app.test_client()
    resp = client.post("/api/stop/does-not-exist")
    assert resp.status_code == 404


def test_stop_endpoint_accepts_known_job(monkeypatch):
    """手动注册一个 job，stop 后状态应被置位。"""
    import app as app_module
    import threading
    evt = threading.Event()
    job_id = "test-job-1"
    with app_module._JOBS_LOCK:
        app_module._JOBS[job_id] = evt
    try:
        client = app.test_client()
        resp = client.post(f"/api/stop/{job_id}")
        assert resp.status_code == 200
        assert resp.json["success"] is True
        assert evt.is_set()
    finally:
        with app_module._JOBS_LOCK:
            app_module._JOBS.pop(job_id, None)


def test_stream_emits_log_events_in_order(monkeypatch):
    """验证事件顺序：start → batch_start → api_call → api_result → batch_done → done。"""
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            return [{"domain": "alpha", "reason": "r"}]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr(
        "app.check_domains_with_errors",
        lambda domains, tlds, timeout: (
            {d: "available" for d in domains}, {}
        ),
    )
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    types = [t for t, _ in events]
    # 顺序断言
    assert types[0] == "start"
    assert "batch_start" in types
    assert "api_call" in types
    assert "api_result" in types
    assert "batch_done" in types
    assert types[-1] == "done"


def test_stream_dedupes_candidates_across_batches(monkeypatch):
    """同一 domain 在多批中重复时，checker 不应被重复调用。"""
    call_count = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            call_count["n"] += 1
            # 第 1 批：alpha（已注册）
            # 第 2 批：alpha（重复）+ beta（可注册）→ 终止
            if call_count["n"] == 1:
                return [{"domain": "alpha", "reason": "r"}]
            return [
                {"domain": "alpha", "reason": "r"},  # 重复
                {"domain": "beta", "reason": "r"},
            ]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    def fake_check(domains, tlds, timeout):
        out = {}
        for d in domains:
            if d.startswith("alpha."):
                out[d] = "registered"
            else:
                out[d] = "available"
        return out, {}  # (statuses, errors)
    monkeypatch.setattr("app.check_domains_with_errors", fake_check)
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    # 新事件流：用 api_result 验证每批实际查了什么
    api_results = [d for t, d in events if t == "api_result"]
    # 至少 2 批
    assert len(api_results) >= 2
    # 第 1 批：summary.checked == 1 (alpha 出现)
    assert api_results[0]["summary"]["checked"] == 1
    # 第 2 批：summary.checked == 1 (alpha 重复被去重，beta 是新的)
    assert api_results[1]["summary"]["checked"] == 1


def test_stream_api_call_includes_url_and_model(monkeypatch):
    """用户要求日志体现接口/API：api_call 事件必须含 url 和 model。"""
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            return [{"domain": "alpha", "reason": "r"}]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr(
        "app.check_domains_with_errors",
        lambda domains, tlds, timeout: (
            {d: "available" for d in domains}, {}
        ),
    )
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
        "base_url": "https://my-proxy.example.com/v1",
        "model": "gpt-4o",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    api_calls = [d for t, d in events if t == "api_call"]
    # 第 1 个 api_call 应该是 dmcheck；先检查是否有 OpenAI 的 api 上下文
    batch_starts = [d for t, d in events if t == "batch_start"]
    assert batch_starts[0]["api"]["url"] == "https://my-proxy.example.com/v1/chat/completions"
    assert batch_starts[0]["api"]["model"] == "gpt-4o"
    # dmcheck api_call (新版用 whois 端点)
    assert api_calls[0]["api"]["url"] == "https://dmcheck.app/api/whois/<domain>"
    assert api_calls[0]["api"]["method"] == "GET"
    assert "domains" in api_calls[0]["api"]["params"]


def test_stream_api_result_includes_per_domain_status(monkeypatch):
    """用户要求"显示生成的每一批的结果"：api_result.items 须含每个候选的状态。"""
    call_count = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            call_count["n"] += 1
            # 第 1 批：alpha+beta；alpha 可注册，beta 已注册
            # 第 2 批：alpha 重复 + beta 重复 + gamma 新 → gamma 可注册 → 累计 2 个
            if call_count["n"] == 1:
                return [
                    {"domain": "alpha", "reason": "r"},
                    {"domain": "beta", "reason": "r"},
                ]
            return [
                {"domain": "alpha", "reason": "r"},
                {"domain": "beta", "reason": "r"},
                {"domain": "gamma", "reason": "r"},
            ]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr(
        "app.check_domains_with_errors",
        lambda domains, tlds, timeout: (
            {
                d: (
                    "available" if ("alpha" in d or "gamma" in d) else "registered"
                )
                for d in domains
            },
            {},
        ),
    )
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 2, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    api_results = [d for t, d in events if t == "api_result"]
    assert len(api_results) >= 1
    items = api_results[0]["items"]
    # 2 个候选 × 1 个 tld = 2 个 full domain
    assert len(items) == 2
    statuses = {it["domain"]: it["status"] for it in items}
    assert statuses["alpha.com"] == "available"
    assert statuses["beta.com"] == "registered"
    # summary 也要正确
    assert api_results[0]["summary"]["available"] == 1
    assert api_results[0]["summary"]["registered"] == 1


def test_stream_retries_unknown_domains_in_place(monkeypatch):
    """unknown 域名应原地重试，不立即丢弃。

    第 1 批：b.com 超时 → 重试 1 次后成功（available）；仍 unknown 跳到下批
    """
    # 禁用真实 sleep 避免拖慢测试
    # 注意：retry_unknown_domains 内部用 time.sleep，需直接 patch checker.time.sleep
    monkeypatch.setattr("checker.time.sleep", lambda *a, **kw: None)

    gen_calls = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            gen_calls["n"] += 1
            # 第 1 批只有 b.com 一个候选
            return [{"domain": "b", "reason": "r"}]

    # 记录每次 dmcheck 调用进来的域名集合
    calls_log = []
    def fake_check(domains, tlds, timeout):
        calls_log.append(list(domains))
        statuses, errors = {}, {}
        for d in domains:
            if d == "b.com" and len(calls_log) == 1:
                # 首次超时
                statuses[d] = "unknown"
                errors[d] = "timeout after 5.0s"
            elif d == "b.com":
                # 重试成功
                statuses[d] = "available"
            else:
                statuses[d] = "registered"
        return statuses, errors

    # mock _check_one 让 retry 阶段不发真实 HTTP。
    # 注意：retry 路径直接调 _check_one，与 check_domains_with_errors 是两个入口。
    # 但测试期望 retry_in_place 事件仍能触发、且 attempts 数 >= 2。
    # 我们让 _check_one 也按 calls_log 次数变化，模拟"首次 unknown，重试 available"。
    def fake_check_one(domain, timeout):
        # 注意：b.com 在 calls_log 末尾是首次出现，重试是在原 call 之后的独立调用
        if domain == "b.com":
            # 首次 check 走 check_domains_with_errors 已经被记 1 次；
            # 第一次进 _check_one 是第 1 次 retry（unknown 仍待救回），
            # 但这里我们简化为：第一次进 _check_one 返回 available 模拟"重试成功"。
            # 如果想测 2 次 retry，可在外层用计数器。
            return "available", ""
        return "registered", ""

    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr("app.check_domains_with_errors", fake_check)
    # 不 mock retry_unknown_domains：让真实函数走，它内部已调
    # check_domains_with_errors（mocked above）记录到 calls_log。
    # 真实 attempts=2 (1.0s + 3.0s 退避各 1 次) 满足 retries[0]["attempts"] >= 2 断言。
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    types = [t for t, _ in events]
    assert "done" in types
    done = next(d for t, d in events if t == "done")
    # 重试成功后应有 1 个可注册域名
    assert len(done["domains"]) == 1
    assert done["domains"][0]["domain"] == "b.com"
    # 不该进入下一批（一个候选 retry 就成功了）
    assert gen_calls["n"] == 1, f"应在原地重试，不该继续生成。实际 gen_calls={gen_calls['n']}"
    # 应有 retry_in_place 事件
    retries = [d for t, d in events if t == "retry_in_place"]
    assert len(retries) >= 1
    assert retries[0]["domains"] == ["b.com"]
    assert retries[0]["attempts"] >= 2  # 至少 2 次（首次 + 1 次重试）


def test_stream_keeps_unknown_after_max_retries_and_continues(monkeypatch):
    """unknown 域名在原地用完重试次数后保留 unknown，并继续下一批。"""
    monkeypatch.setattr("checker.time.sleep", lambda *a, **kw: None)

    gen_calls = {"n": 0}
    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            gen_calls["n"] += 1
            if gen_calls["n"] == 1:
                return [{"domain": "stuck", "reason": "r"}]
            return [{"domain": "ok", "reason": "r"}]

    calls_log = []
    def fake_check(domains, tlds, timeout):
        calls_log.append(list(domains))
        statuses, errors = {}, {}
        for d in domains:
            if d == "stuck.com":
                statuses["stuck.com"] = "unknown"
                errors["stuck.com"] = "timeout after 5.0s"
            elif d == "ok.com":
                statuses["ok.com"] = "available"
            else:
                statuses[d] = "registered"
        return statuses, errors

    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr("app.check_domains_with_errors", fake_check)
    # 不 mock retry_unknown_domains：让真实函数走 check_domains_with_errors
    # （mocked above），retry 两次 fake_check 都返 unknown → 真实 attempts=2，
    # stuck.com 仍 unknown 满足后续断言。
    client = app.test_client()
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    done = next(d for t, d in events if t == "done")
    assert len(done["domains"]) == 1
    assert done["domains"][0]["domain"] == "ok.com"
    # 至少 2 批：第 1 批 stuck 重试仍失败 → 生成第 2 批 → 拿到 ok
    assert gen_calls["n"] >= 2
    # stuck.com 出现过 3 次：原始 + 2 次原地重试
    stuck_calls = [c for c in calls_log if "stuck.com" in c]
    assert len(stuck_calls) == 3, f"stuck.com 应被调 3 次，实际 {len(stuck_calls)}"


def test_stream_retry_attempts_capped_at_max(monkeypatch):
    """验证原地重试次数上限 = 2（共调用 3 次：1 原始 + 2 重试）。"""
    monkeypatch.setattr("checker.time.sleep", lambda *a, **kw: None)

    class _G:
        def __init__(self, *a, **kw): pass
        def generate(self, *a, **kw):
            return [{"domain": "x", "reason": "r"}]

    calls_log = []
    def fake_check(domains, tlds, timeout):
        calls_log.append(list(domains))
        return {d: "unknown" for d in domains}, {d: "timeout after 5.0s" for d in domains}

    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G())
    monkeypatch.setattr("app.check_domains_with_errors", fake_check)
    # 不 mock retry_unknown_domains：让真实函数走 check_domains_with_errors
    # （mocked above），retry 两次 fake_check 都返 unknown → 真实 attempts=2，
    # stuck.com 仍 unknown 满足后续断言。
    client = app.test_client()
    # 用 count=1 + 一批后退出条件，但 unknown 不会被记入 available。
    # 我们通过 monkeypatch 限制打满循环。这里只验证 x.com 被检查次数。
    # 为避免死循环，monkeypatch 替换生成器，让第二次后结束：
    gen = {"n": 0}
    real_g = _G
    class _G2(real_g):
        def generate(self, *a, **kw):
            gen["n"] += 1
            if gen["n"] >= 3:
                # 让主循环的终止条件（len(available) >= count 永远不成立）
                # 借助 batch_no 限制：本测试通过 fake_check 阻止 available
                return [{"domain": "y", "reason": "r"}]
            return [{"domain": "x", "reason": "r"}]
    monkeypatch.setattr("app.OpenAIGenerator", lambda **kw: _G2())
    # 限制主循环迭代上限以避免死循环——直接用 count=1，但 unknown 永远不为 available
    # 实际上主循环只在 len(available)>=count 时退出，且不会停下 — 测试用 monkeypatch 限制。
    # 这里把 count 设成 1，并让第二轮生成一个 available
    gen["n"] = 0
    def check_with_yok(domains, tlds, timeout):
        calls_log.append(list(domains))
        statuses, errors = {}, {}
        for d in domains:
            if d == "y.com":
                statuses[d] = "available"
            else:
                statuses[d] = "unknown"
                errors[d] = "timeout after 5.0s"
        return statuses, errors
    monkeypatch.setattr("app.check_domains_with_errors", check_with_yok)
    resp = client.post("/api/generate-stream", json={
        "description": "x", "min_len": 4, "max_len": 10,
        "tlds": ["com"], "count": 1, "api_key": "sk-test",
    })
    events = _parse_sse_events(resp.get_data(as_text=True))
    done = next(d for t, d in events if t == "done")
    assert len(done["domains"]) == 1
    assert done["domains"][0]["domain"] == "y.com"
    # x.com 应被检查 3 次（原始 + 2 次重试），不会无限
    x_calls = [c for c in calls_log if "x.com" in c]
    assert len(x_calls) == 3, f"x.com 应被调 3 次（1 原始 + 2 重试），实际 {len(x_calls)}"