"""版本 + 在线更新 API 测试。"""
import json
from unittest import mock

import pytest

from app import app
from version import is_newer, parse_semver
import updater


# ── 纯函数 ─────────────────────────────────────────────────────────────

def test_parse_semver_basic():
    assert parse_semver("1.0.1") == (1, 0, 1)
    assert parse_semver("v2.3.4") == (2, 3, 4)


def test_parse_semver_invalid():
    assert parse_semver("1.0") is None
    assert parse_semver("1.0.1.2") is None
    assert parse_semver("abc") is None
    assert parse_semver("") is None


def test_is_newer_patch_bump():
    assert is_newer("1.0.2", "1.0.1") is True
    assert is_newer("1.0.10", "1.0.9") is True


def test_is_newer_minor_bump():
    assert is_newer("1.1.0", "1.0.99") is True


def test_is_newer_major_bump():
    assert is_newer("2.0.0", "1.9.9") is True


def test_is_newer_equal_or_older():
    assert is_newer("1.0.1", "1.0.1") is False
    assert is_newer("1.0.0", "1.0.1") is False
    assert is_newer("0.9.9", "1.0.0") is False


def test_is_newer_garbage_safe():
    """非法版本号一律返回 False（不抛异常）。"""
    assert is_newer("garbage", "1.0.0") is False
    assert is_newer("1.0.1", "garbage") is False


# ── /api/version ──────────────────────────────────────────────────────

def test_api_version_returns_semver():
    client = app.test_client()
    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "version" in data
    # 必须能 parse 为 semver
    assert parse_semver(data["version"]) is not None
    assert data["github"]["owner"] == "adminmtan"
    assert data["environment"]["image"].startswith("ghcr.io/")


def test_api_version_env_override(monkeypatch):
    """APP_VERSION 环境变量应覆盖 version.py 的默认值。"""
    monkeypatch.setenv("APP_VERSION", "1.2.3-test")
    client = app.test_client()
    resp = client.get("/api/version")
    assert resp.json["version"] == "1.2.3-test"


# ── /api/update/check ─────────────────────────────────────────────────

def test_update_check_no_update(monkeypatch):
    """远端 = 本地 → update_available=False。"""
    fake = {
        "tag_name": "v1.0.1",
        "html_url": "https://github.com/adminmtan/domainsearch-/releases/tag/v1.0.1",
        "body": "notes",
        "published_at": "2026-10-10T00:00:00Z",
    }
    monkeypatch.setattr(updater, "_cache", {"ts": 0.0, "result": None})

    def fake_urlopen(req, timeout):
        class _R:
            def read(self_inner):
                return json.dumps(fake).encode("utf-8")
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
        return _R()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    result = updater.check_for_update("1.0.1", force=True)
    assert result["ok"] is True
    assert result["update_available"] is False
    assert result["latest"] == "v1.0.1"


def test_update_check_has_update(monkeypatch):
    """远端 > 本地 → update_available=True。"""
    fake = {
        "tag_name": "v1.0.5",
        "html_url": "https://github.com/.../releases/tag/v1.0.5",
        "body": "- fix: ...\n- feat: ...",
        "published_at": "2026-10-10T00:00:00Z",
    }
    monkeypatch.setattr(updater, "_cache", {"ts": 0.0, "result": None})

    def fake_urlopen(req, timeout):
        class _R:
            def read(self_inner): return json.dumps(fake).encode("utf-8")
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
        return _R()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    result = updater.check_for_update("1.0.1", force=True)
    assert result["ok"] is True
    assert result["update_available"] is True
    assert result["latest"] == "v1.0.5"
    assert "fix" in result["notes"]


def test_update_check_github_error(monkeypatch):
    """远端 4xx/5xx → ok=False + reason。"""
    import urllib.error
    monkeypatch.setattr(updater, "_cache", {"ts": 0.0, "result": None})

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            "https://api.github.com/...", 404, "Not Found", {}, None,
        )

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    result = updater.check_for_update("1.0.1", force=True)
    assert result["ok"] is False
    assert "404" in result["reason"]


def test_update_check_uses_cache(monkeypatch):
    """5 分钟内重复调用不重新打 GitHub。"""
    cached = {"ok": True, "current": "1.0.1", "latest": "v1.0.5",
              "update_available": True}
    monkeypatch.setattr(
        updater, "_cache",
        {"ts": updater.time.time() - 10, "result": cached},
    )

    def explode(*a, **kw):
        raise AssertionError("urlopen 不应被调用（缓存命中）")

    monkeypatch.setattr(updater.urllib.request, "urlopen", explode)
    result = updater.check_for_update("1.0.1", force=False)
    assert result is cached


# ── /api/update/apply ─────────────────────────────────────────────────

def test_update_apply_non_docker_returns_manual_steps(monkeypatch):
    """不在容器内 → 返回 manual_required + 步骤。"""
    monkeypatch.setattr(updater, "detect_environment", lambda: {
        "in_docker": False,
        "has_docker_sock": False,
        "compose_file": None,
        "can_self_update_docker": False,
        "image": "ghcr.io/adminmtan/yuming",
    })
    result = updater.apply_update()
    assert result["ok"] is False
    assert result["mode"] == "manual_required"
    assert isinstance(result["steps"], list)
    assert len(result["steps"]) > 0


def test_update_apply_docker_no_socket_returns_manual(monkeypatch):
    """容器内但没 socket → manual_required（不是后台模式）。"""
    monkeypatch.setattr(updater, "detect_environment", lambda: {
        "in_docker": True,
        "has_docker_sock": False,
        "compose_file": "/app/docker-compose.yml",
        "can_self_update_docker": False,
        "image": "ghcr.io/adminmtan/yuming",
    })
    result = updater.apply_update()
    assert result["ok"] is False
    assert result["mode"] == "manual_required"
    # 容器内的步骤要引导用户在宿主机跑
    assert any("宿主机" in s for s in result["steps"])


def test_update_apply_docker_with_socket_runs_background(monkeypatch, tmp_path):
    """完整 Docker 环境：写脚本 + 启动后台进程。"""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("version: '3.8'\nservices:\n  yuming:\n    image: test\n")

    monkeypatch.setattr(updater, "detect_environment", lambda: {
        "in_docker": True,
        "has_docker_sock": True,
        "compose_file": str(compose),
        "can_self_update_docker": True,
        "image": "ghcr.io/adminmtan/yuming",
    })
    # 把脚本写到 tmp，避免污染真实 /tmp
    fake_script = str(tmp_path / "update.sh")
    monkeypatch.setattr(updater, "_UPDATE_SCRIPT", fake_script)
    monkeypatch.setattr(updater, "_UPDATE_LOG", str(tmp_path / "update.log"))
    monkeypatch.setattr(updater, "_UPDATE_DONE", str(tmp_path / "update.done"))

    popen_calls: list = []
    class _FakePopen:
        def __init__(self, args, **kw):
            popen_calls.append((args, kw))
    monkeypatch.setattr(updater.subprocess, "Popen", _FakePopen)

    result = updater.apply_update()
    assert result["ok"] is True
    assert result["mode"] == "background"
    assert "yuming" in result["image"]
    # 脚本写出来了
    import os
    assert os.path.isfile(fake_script)
    # 脚本内容包含关键命令
    content = open(fake_script, encoding="utf-8").read()
    assert "docker compose pull" in content
    assert "docker compose up -d" in content
    # Popen 调用了 setsid
    assert popen_calls
    assert popen_calls[0][0][0] == "setsid"


def test_update_apply_respects_target_tag(monkeypatch, tmp_path):
    """显式传 target=1.0.5 时，脚本里写死的 image_ref 应该是 1.0.5。"""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("version: '3.8'\n")
    monkeypatch.setattr(updater, "detect_environment", lambda: {
        "in_docker": True, "has_docker_sock": True,
        "compose_file": str(compose), "can_self_update_docker": True,
        "image": "ghcr.io/adminmtan/yuming",
    })
    fake_script = str(tmp_path / "u.sh")
    monkeypatch.setattr(updater, "_UPDATE_SCRIPT", fake_script)
    monkeypatch.setattr(updater, "_UPDATE_LOG", str(tmp_path / "u.log"))
    monkeypatch.setattr(updater, "_UPDATE_DONE", str(tmp_path / "u.done"))
    monkeypatch.setattr(
        updater.subprocess, "Popen",
        lambda *a, **kw: type("P", (), {"__init__": lambda s, *a, **kw: None})(),
    )
    result = updater.apply_update(target="1.0.5")
    assert "1.0.5" in result["image"]
    content = open(fake_script, encoding="utf-8").read()
    assert "1.0.5" in content


# ── HTTP 路由 ─────────────────────────────────────────────────────────

def test_http_version_ok():
    client = app.test_client()
    resp = client.get("/api/version")
    assert resp.status_code == 200


def test_http_update_check_ok(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda cur, force=False: {
        "ok": True, "current": cur, "latest": "v1.0.2",
        "update_available": True,
    })
    client = app.test_client()
    resp = client.get("/api/update/check")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["update_available"] is True


def test_http_update_apply_502_when_apply_raises(monkeypatch):
    """apply_update 出错也返回 200 + 结构化 error，不让 5xx 打到前端。"""
    monkeypatch.setattr(
        updater, "apply_update",
        lambda **kw: {"ok": False, "mode": "error", "reason": "boom"},
    )
    client = app.test_client()
    resp = client.post("/api/update/apply", json={})
    assert resp.status_code == 200
    assert resp.get_json()["reason"] == "boom"


def test_http_update_log_endpoint():
    """空日志也要 200。"""
    client = app.test_client()
    resp = client.get("/api/update/log")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "log" in data and "done" in data
