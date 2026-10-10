"""wechat_pusher 单元测试（HTTP 调用方式）。

所有 HTTP 调用都用 monkeypatch 模拟，不真发请求。
"""
from __future__ import annotations

import json
import os
import importlib


def _reload(**env):
    for k, v in env.items():
        os.environ[k] = v
    import wechat_pusher
    importlib.reload(wechat_pusher)
    return wechat_pusher


class _FakeResp:
    def __init__(self, ok=True, status_code=200, json_data=None, text=""):
        self.ok = ok
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


def test_is_configured_true_when_bot_health_ok(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    monkeypatch.setattr(wechat_pusher.requests, "get",
        lambda url, headers=None, timeout=None: _FakeResp(json_data={"ok": True}))

    assert wechat_pusher.is_configured() is True


def test_is_configured_false_when_bot_unreachable(monkeypatch):
    import requests as _req
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    monkeypatch.setattr(wechat_pusher.requests, "get",
        lambda url, headers=None, timeout=None: _FakeResp(ok=False, status_code=0))

    assert wechat_pusher.is_configured() is False


def test_get_status_returns_contacts(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    contacts = [
        {"peerId": "u123", "displayName": "张三", "lastText": "你好", "lastTs": 1700000000},
        {"peerId": "u456", "displayName": "李四", "lastText": "好的", "lastTs": 1699999999},
    ]
    monkeypatch.setattr(wechat_pusher.requests, "get",
        lambda url, headers=None, timeout=None: _FakeResp(json_data={
            "ok": True, "status": "connected", "contacts": contacts
        }))

    result = wechat_pusher.get_status()
    assert result["status"] == "connected"
    assert len(result["contacts"]) == 2


def test_push_result_sends_text_to_target(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    monkeypatch.setenv("WECHAT_BOT_TOKEN", "secret")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    captured = {}
    def fake_get(url, headers=None, timeout=None):
        captured["get_url"] = url
        return _FakeResp(json_data={"ok": True, "status": "connected", "contacts": []})

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["post_url"] = url
        captured["post_body"] = json
        captured["headers"] = headers
        return _FakeResp(json_data={"ok": True})

    monkeypatch.setattr(wechat_pusher.requests, "get", fake_get)
    monkeypatch.setattr(wechat_pusher.requests, "post", fake_post)

    domains = [{"domain": "mythforge.com", "reason": "好记"}]
    stats = {"requested": 1, "batches": 1, "elapsed": 0.5}
    result = wechat_pusher.push_result("我的项目", domains, stats, peer_id="u123")

    assert result["ok"] is True
    assert captured["post_body"]["peerId"] == "u123"
    assert "mythforge.com" in captured["post_body"]["text"]
    assert captured["headers"]["X-Bot-Token"] == "secret"


def test_push_result_no_peer_id_returns_needs_target(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    monkeypatch.delenv("WECHAT_DEFAULT_PEER", raising=False)
    import wechat_pusher
    importlib.reload(wechat_pusher)

    result = wechat_pusher.push_result("x", [], {}, peer_id=None)
    assert result["ok"] is False
    assert result["needs_target"] is True


def test_push_result_uses_default_peer_from_env(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    monkeypatch.setenv("WECHAT_DEFAULT_PEER", "u_default")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    captured = {}
    def fake_get(url, headers=None, timeout=None):
        return _FakeResp(json_data={"ok": True, "status": "connected", "contacts": []})
    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return _FakeResp(json_data={"ok": True})
    monkeypatch.setattr(wechat_pusher.requests, "get", fake_get)
    monkeypatch.setattr(wechat_pusher.requests, "post", fake_post)

    wechat_pusher.push_result("x", [], {})
    assert captured["body"]["peerId"] == "u_default"


def test_push_result_not_connected_returns_error(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    monkeypatch.setenv("WECHAT_DEFAULT_PEER", "u123")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    def fake_get(url, headers=None, timeout=None):
        return _FakeResp(json_data={"ok": True, "status": "disconnected", "contacts": []})
    monkeypatch.setattr(wechat_pusher.requests, "get", fake_get)

    result = wechat_pusher.push_result("x", [], {})
    assert result["ok"] is False
    assert "未连接" in result["error"]


def test_push_test(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    import wechat_pusher
    importlib.reload(wechat_pusher)

    captured = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return _FakeResp(json_data={"ok": True})
    monkeypatch.setattr(wechat_pusher.requests, "post", fake_post)

    result = wechat_pusher.push_test("u123")
    assert result["ok"] is True
    assert "连通性测试" in captured["body"]["text"]
