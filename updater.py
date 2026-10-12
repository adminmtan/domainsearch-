"""在线更新逻辑：检测环境、拉 GitHub Release、执行自更新。

设计约束：
  1. 默认部署（容器内 / 宿主机源码）都不一定能"一键更新"——会按能力返回
     不同的 result，前端按需展示 toast / 手动步骤。
  2. 失败永远不抛异常到外层：返回结构化 result 给 HTTP handler。
  3. 主版本（第一位）从不允许被自动更新脚本触碰——前端 / 流程都按"小版本
     自动、大版本手动"约束走。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from typing import Any

from version import (
    get_version,
    is_newer,
    GITHUB_OWNER,
    GITHUB_REPO,
    DOCKER_IMAGE,
)

# GitHub API endpoint（不带 token，60 req/h 限流，足够家庭部署）
_GH_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# 进程内缓存（避免前端轮询打爆 GitHub）
_CACHE_TTL_SEC = 300
_cache: dict[str, Any] = {"ts": 0.0, "result": None}

# 后台更新脚本路径（容器内写脚本 + 哨兵文件）
_UPDATE_SCRIPT = "/tmp/yuming-self-update.sh"
_UPDATE_LOG = "/tmp/yuming-self-update.log"
_UPDATE_DONE = "/tmp/yuming-self-update.done"


# ── 环境检测 ───────────────────────────────────────────────────────────

def detect_environment() -> dict[str, Any]:
    """识别当前运行环境，供前端展示 + 更新逻辑判断走哪条路径。"""
    in_docker = os.path.isfile("/.dockerenv")
    has_docker_sock = os.path.isfile("/var/run/docker.sock")
    compose_file = _find_compose_file()
    return {
        "in_docker": in_docker,
        "has_docker_sock": has_docker_sock,
        "compose_file": compose_file,
        "can_self_update_docker": bool(in_docker and has_docker_sock and compose_file),
        "image": DOCKER_IMAGE,
    }


def _find_compose_file() -> str | None:
    """在常见路径里找 docker-compose.yml（容器内 / 宿主机都能用）。"""
    candidates = [
        "/app/docker-compose.yml",
        "/app/../docker-compose.yml",
        "/docker-compose.yml",
        os.path.expanduser("~/docker-compose.yml"),
        "./docker-compose.yml",
    ]
    for p in candidates:
        try:
            real = os.path.realpath(p)
        except OSError:
            continue
        if os.path.isfile(real):
            return real
    return None


# ── 查新版本 ───────────────────────────────────────────────────────────

def check_for_update(current: str, force: bool = False) -> dict[str, Any]:
    """查 GitHub Releases/latest，与 current 比较。

    失败返回 {ok: False, reason: ...}；成功返回完整字段。
    """
    now = time.time()
    if not force and _cache["result"] is not None and now - _cache["ts"] < _CACHE_TTL_SEC:
        return _cache["result"]

    try:
        req = urllib.request.Request(
            _GH_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"yuming-app/{current}",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        result = {
            "ok": False,
            "reason": f"GitHub API HTTP {e.code}",
            "current": current,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        result = {
            "ok": False,
            "reason": f"无法访问 GitHub：{type(e).__name__}: {e}",
            "current": current,
        }
    else:
        latest_tag = (data.get("tag_name") or "").strip()
        html_url = data.get("html_url") or ""
        body = data.get("body") or ""
        published_at = data.get("published_at") or ""
        result = {
            "ok": True,
            "current": current,
            "latest": latest_tag,
            "update_available": bool(latest_tag and is_newer(latest_tag, current)),
            "url": html_url,
            "notes": body[:1500],
            "published_at": published_at,
        }

    _cache["result"] = result
    _cache["ts"] = now
    return result


# ── 执行更新 ───────────────────────────────────────────────────────────

def apply_update(target: str | None = None) -> dict[str, Any]:
    """根据环境执行更新。

    策略：
      - Docker + 挂载 docker.sock + 找到 compose 文件 → 后台跑
        `docker compose pull && docker compose up -d`，前端轮询直至服务恢复。
      - 宿主机源码部署 → 引导用户手动 git pull + 重启。
      - 其它（容器内但没 socket 等）→ 返回手动步骤。
    """
    env = detect_environment()
    if not env["can_self_update_docker"]:
        return {
            "ok": False,
            "mode": "manual_required",
            "reason": "当前部署不支持自更新",
            "steps": _manual_steps(env, target),
        }

    compose_file = env["compose_file"]
    image = env["image"]
    image_ref = f"{image}:{target}" if target else f"{image}:latest"

    try:
        with open(_UPDATE_SCRIPT, "w", encoding="utf-8") as f:
            f.write(_compose_update_script(compose_file, image_ref))
        os.chmod(_UPDATE_SCRIPT, 0o755)
    except OSError as e:
        return {
            "ok": False,
            "mode": "error",
            "reason": f"无法写更新脚本：{e}",
        }

    try:
        subprocess.Popen(
            ["setsid", "bash", _UPDATE_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        return {
            "ok": False,
            "mode": "error",
            "reason": f"无法启动更新进程：{e}",
        }

    return {
        "ok": True,
        "mode": "background",
        "image": image_ref,
        "compose_file": compose_file,
        "message": "后台更新已启动；服务将在数秒内重启，请稍候刷新页面。",
    }


def _compose_update_script(compose_file: str, image_ref: str) -> str:
    """容器内执行的实际脚本。

    关键点：
      1. pull 之前 cd 到 compose 所在目录，否则 docker compose 找不到 project name。
      2. up -d 后容器会被替换（image 变了），旧容器结束 → 我们的脚本也死掉。
    """
    compose_dir = os.path.dirname(compose_file)
    return f"""#!/bin/bash
# 自动生成的更新脚本（不要手动编辑）
set -u
cd {compose_dir}
echo "[update] pull {image_ref}" > {_UPDATE_LOG}
docker compose pull yuming >> {_UPDATE_LOG} 2>&1
echo "[update] up -d" >> {_UPDATE_LOG}
docker compose up -d yuming >> {_UPDATE_LOG} 2>&1
echo "[update] done $(date -Iseconds)" > {_UPDATE_DONE}
"""


def get_update_log_tail(max_bytes: int = 4000) -> str:
    """前端轮询时调，看后台脚本进度。"""
    try:
        with open(_UPDATE_LOG, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = "…(truncated)…\n" + data[-max_bytes:]
    return data


def is_update_done() -> bool:
    return os.path.isfile(_UPDATE_DONE)


def _manual_steps(env: dict[str, Any], target: str | None) -> list[str]:
    """手动更新步骤（无 socket 时引导用户）。"""
    image = env["image"]
    tag = target or "latest"
    if env["in_docker"]:
        return [
            "当前在容器内运行，但未挂载 docker socket（无法自更新）。",
            "在宿主机执行：",
            "  cd <项目目录>",
            "  docker compose pull yuming",
            "  docker compose up -d yuming",
        ]
    return [
        "当前为源码部署。在项目目录执行：",
        "  git pull",
        "  .venv/bin/pip install -r requirements.txt  # 如有依赖变更",
        "  # 重启服务（按你当前的进程管理方式）：",
        "  systemctl --user restart yuming  # 或 supervisorctl restart yuming",
        "",
        "如改为 Docker 部署，可获得自更新能力：",
        f"  docker compose pull yuming  # 拉取 {image}:{tag}",
        "  docker compose up -d yuming",
    ]
