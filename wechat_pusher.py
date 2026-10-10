"""微信推送模块（对接 wechat-bot 服务）。

设计：Flask 后端通过 HTTP 调用同机器上的微信 Bot 服务（Node.js + wechat-channel），
Bot 负责扫码登录、收消息、主动发消息（限制：只能发给 24h 内联系过你的人）。

推送策略（2026-10 重构）：
- 实时推送：每发现 1 个可注册域名 → 立即推一条到所有目标联系人
- 报告推送：满足生成数量后 → 生成 MD + HTML 报告，推链接
- 异常推送：用户停止 / 系统异常 → 推停止通知

环境变量：
- WECHAT_BOT_URL      : Bot 服务地址，默认 http://127.0.0.1:5002
- WECHAT_BOT_TOKEN    : 鉴权 token（必须与 Bot 端一致）
- WECHAT_DEFAULT_PEER : 可选，默认推送目标 peerId（多个用逗号分隔；如未设置则用前端传入的）
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0


def _bot_url(path: str) -> str:
    base = os.environ.get("WECHAT_BOT_URL", "http://127.0.0.1:5002")
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _headers() -> dict:
    token = os.environ.get("WECHAT_BOT_TOKEN", os.environ.get("BOT_API_TOKEN", ""))
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Bot-Token"] = token
    return h


def _bot_get(path: str) -> dict:
    try:
        resp = requests.get(
            _bot_url(path),
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT_S,
        )
        return resp.json() if resp.ok else {"ok": False, "error": f"HTTP {resp.status_code}"}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}


def _bot_post(path: str, data: dict) -> dict:
    try:
        resp = requests.post(
            _bot_url(path),
            json=data,
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT_S,
        )
        return resp.json() if resp.ok else {"ok": False, "error": f"HTTP {resp.status_code}"}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}


# ── 对外 API ──────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Bot 服务可达即认为已配置（用户登录状态由 /status 端点单独告知）。"""
    r = _bot_get("/health")
    return r.get("ok", False)


def get_status() -> dict:
    """获取 Bot 登录状态和联系人列表。"""
    return _bot_get("/status")


def login() -> dict:
    """触发扫码登录（异步，Bot 端会生成二维码）。"""
    return _bot_post("/login", {})


def logout() -> dict:
    """登出微信。"""
    return _bot_post("/logout", {})


def send_message(peer_id: str, text: str) -> dict:
    """给指定联系人发消息（peerId 来自 get_status 里的 contacts）。"""
    return _bot_post("/send", {"peerId": peer_id, "text": text})


# ── 目标联系人解析 ─────────────────────────────────────────────────────────

def get_target_peers(explicit: Iterable[str] | None = None) -> list[str]:
    """解析推送目标联系人列表。

    优先级：explicit（前端传入） > WECHAT_DEFAULT_PEER 环境变量（逗号分隔）。
    返回去重后的 peerId 列表。
    """
    if explicit:
        peers = [p.strip() for p in explicit if p and p.strip()]
    else:
        env = os.environ.get("WECHAT_DEFAULT_PEER", "")
        peers = [p.strip() for p in env.split(",") if p.strip()]
    # 去重并保持顺序
    seen = set()
    out = []
    for p in peers:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _broadcast(peers: list[str], text: str) -> list[dict]:
    """向多个联系人广播同一文本，返回每个目标的结果。

    失败不抛异常，逐个返回结构化结果。
    """
    results = []
    for p in peers:
        r = send_message(p, text)
        r["peer_id"] = p
        results.append(r)
    return results


# ── 消息格式化 ─────────────────────────────────────────────────────────────

def _format_domain_block(domain: dict) -> str:
    """单条可注册域名的美化块。"""
    name = domain.get("domain", "")
    reason = (domain.get("reason") or "").replace("\n", " ").strip()
    if len(reason) > 160:
        reason = reason[:160] + "…"
    length = domain.get("length", len(name.split(".", 1)[0]))
    tld = domain.get("tld", name.split(".", 1)[-1] if "." in name else "")
    return f"  🌐 **{name}**  ·  {length} 字符  ·  .{tld}\n  💡 {reason}"


def _format_new_domain_message(domain: dict, total_now: int, requested: int) -> str:
    """实时推送：单条可注册域名发现。"""
    return (
        f"🆕 **新发现可注册域名** ({total_now}/{requested})\n"
        f"\n"
        f"{_format_domain_block(domain)}"
    )


def _format_completion_message(domains: list[dict], stats: dict, report_url: str | None) -> str:
    """最终完成推送：汇总 + 报告链接。"""
    elapsed = stats.get("elapsed", 0)
    lines = [
        f"✅ **域名生成完成**（{len(domains)} 个可注册）",
        f"",
        f"📊 批次 {stats.get('batches', 0)} · 生成 {stats.get('generated', 0)} · "
        f"用时 {elapsed}s",
        f"",
    ]
    for i, d in enumerate(domains, 1):
        lines.append(f"{i}. {d.get('domain', '')}")
    if report_url:
        lines.extend([
            f"",
            f"📄 完整报告（含理由、长度、TLD）：",
            f"{report_url}",
        ])
    return "\n".join(lines)


def _format_stopped_message(
    description: str,
    found: list[dict],
    requested: int,
    elapsed: float,
    reason: str,
) -> str:
    """停止/异常推送。"""
    reason_emoji = {
        "user": "🛑",
        "error": "💥",
        "timeout": "⏱",
    }.get(reason, "⚠️")
    reason_text = {
        "user": "用户手动停止",
        "error": "系统异常退出",
        "timeout": "生成超时",
    }.get(reason, reason)

    desc_short = description[:120].replace("\n", " ")
    lines = [
        f"{reason_emoji} **域名生成已停止**",
        f"",
        f"📝 描述：{desc_short}",
        f"📊 进展：{len(found)}/{requested} 个可注册（用时 {elapsed}s）",
        f"🔖 原因：{reason_text}",
    ]
    if found:
        lines.append(f"")
        lines.append(f"**已找到的域名**：")
        for i, d in enumerate(found, 1):
            lines.append(f"{i}. {d.get('domain', '')}")
    return "\n".join(lines)


# ── 主推送入口 ─────────────────────────────────────────────────────────────

def _precheck(peer_ids: list[str]) -> dict | None:
    """推送前的健康检查。返回 None 表示通过；返回 dict 表示错误。"""
    if not peer_ids:
        return {
            "configured": True,
            "ok": False,
            "error": "未指定推送目标，请先在页面选择微信联系人",
            "needs_target": True,
        }
    status = get_status()
    if status.get("status") != "connected":
        return {
            "configured": True,
            "ok": False,
            "error": f"微信未连接（状态：{status.get('status', 'unknown')}），无法推送",
            "status": status.get("status"),
        }
    return None


def push_new_domain(
    domain: dict,
    total_now: int,
    requested: int,
    peer_ids: list[str] | None = None,
) -> dict:
    """实时推送：单个新可注册域名发现。"""
    peers = get_target_peers(peer_ids)
    err = _precheck(peers)
    if err:
        return {**err, "skipped": True}

    text = _format_new_domain_message(domain, total_now, requested)
    results = _broadcast(peers, text)
    ok = any(r.get("ok") for r in results)
    return {
        "configured": True,
        "ok": ok,
        "kind": "new_domain",
        "peer_ids": peers,
        "results": results,
        "domain": domain.get("domain"),
        "payload_size": len(text.encode("utf-8")),
    }


def push_report(
    description: str,
    domains: list[dict],
    stats: dict,
    report_url: str | None,
    peer_ids: list[str] | None = None,
) -> dict:
    """最终报告推送。"""
    peers = get_target_peers(peer_ids)
    err = _precheck(peers)
    if err:
        return {**err, "skipped": True}

    text = _format_completion_message(domains, stats, report_url)
    results = _broadcast(peers, text)
    ok = any(r.get("ok") for r in results)
    return {
        "configured": True,
        "ok": ok,
        "kind": "report",
        "peer_ids": peers,
        "results": results,
        "payload_size": len(text.encode("utf-8")),
        "report_url": report_url,
    }


def push_stopped(
    description: str,
    found: list[dict],
    requested: int,
    elapsed: float,
    reason: str,
    peer_ids: list[str] | None = None,
) -> dict:
    """停止/异常推送。"""
    peers = get_target_peers(peer_ids)
    err = _precheck(peers)
    if err:
        return {**err, "skipped": True}

    text = _format_stopped_message(description, found, requested, elapsed, reason)
    results = _broadcast(peers, text)
    ok = any(r.get("ok") for r in results)
    return {
        "configured": True,
        "ok": ok,
        "kind": "stopped",
        "peer_ids": peers,
        "results": results,
        "payload_size": len(text.encode("utf-8")),
        "reason": reason,
    }


# ── 兼容旧接口 ─────────────────────────────────────────────────────────────

def push_result(description: str, domains: list[dict], stats: dict,
                peer_id: str | None = None) -> dict:
    """兼容旧调用：等价于 push_report。"""
    peers = get_target_peers([peer_id] if peer_id else None)
    return push_report(description, domains, stats, None, peer_ids=peers)


def push_test(peer_id: str) -> dict:
    """发一条测试消息到指定联系人。"""
    text = "✅ 智能域名生成器推送连通性测试成功！"
    return send_message(peer_id, text)
