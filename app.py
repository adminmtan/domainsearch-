#!/usr/bin/env python3
import json
import threading
import time

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import os

from openai import OpenAI
from openai import AuthenticationError as OpenAIAuthenticationError
from openai import APIConnectionError as OpenAIAPIConnectionError

from generator import OpenAIGenerator
from checker import check_domains

app = Flask(__name__, static_folder="static", static_url_path="/static")


# Disable HTTP caching for all responses during development.
# 防止浏览器缓存旧版 static 资源导致按钮事件未绑定等问题。
@app.after_request
def add_no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


def _bad_request(msg: str):
    return jsonify({"success": False, "error": msg}), 400


DEFAULT_TLDS = [
    "com", "io", "ai", "dev", "app", "net", "org",
    "co", "me", "xyz", "tech", "cloud", "studio", "lab",
    "tools", "site", "online", "store", "info", "biz",
]


@app.route("/api/tlds", methods=["GET"])
def api_tlds():
    return jsonify({"tlds": DEFAULT_TLDS})


@app.route("/api/validate-key", methods=["POST"])
def api_validate_key():
    """轻量验证 OpenAI API Key 是否有效。

    通过 GET /v1/models 实现：
    - 不消耗 token
    - 兼容任何 OpenAI 协议代理
    - 返回 {success, model_count, sample_models} 或 {success: False, error}
    """
    data = request.get_json(silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    base_url = (data.get("base_url") or "https://api.openai.com/v1").strip()
    model = (data.get("model") or "gpt-4o-mini").strip()

    if not api_key:
        return jsonify({"success": False, "error": "API Key 不能为空"}), 400

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        # openai SDK: models.list() 在 1.x 是方法；保守处理：先按方法调
        try:
            models = client.models.list()
            data_attr = models.data or []
        except AttributeError:
            # 退化：可能是属性访问或返回 SyncPage
            models = getattr(client.models, "data", None)
            data_attr = models or []
        ids = [m.id for m in data_attr][:5]
        return jsonify({
            "success": True,
            "model_count": len(data_attr),
            "sample_models": ids,
            "requested_model_available": (model in ids) if ids else None,
        })
    except OpenAIAuthenticationError as e:
        return jsonify({
            "success": False,
            "error": f"API Key 无效或未授权：{getattr(e, 'message', '401 Unauthorized')}",
        })
    except OpenAIAPIConnectionError:
        return jsonify({
            "success": False,
            "error": f"无法连接到 {base_url}，请检查网络或 Base URL",
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"验证失败：{type(e).__name__}: {e}",
        })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    min_len = data.get("min_len")
    max_len = data.get("max_len")
    tlds = data.get("tlds") or []
    count = data.get("count")
    api_key = (data.get("api_key") or "").strip()
    base_url = (data.get("base_url") or "https://api.openai.com/v1").strip()
    model = (data.get("model") or "gpt-4o-mini").strip()

    # Validation
    if not description:
        return _bad_request("描述内容不能为空")
    if len(description) > 2000:
        return _bad_request("描述内容不能超过 2000 字符")
    if not api_key:
        return _bad_request("请先在设置中填入 OpenAI API Key")
    if not isinstance(min_len, int) or not isinstance(max_len, int):
        return _bad_request("长度范围必须为整数")
    if min_len < 2 or max_len > 20 or min_len > max_len:
        return _bad_request("长度范围非法（2-20，且 min <= max）")
    if not isinstance(count, int) or count < 1 or count > 50:
        return _bad_request("数量必须为 1-50 的整数")
    if not isinstance(tlds, list) or not tlds or not all(isinstance(t, str) for t in tlds):
        return _bad_request("TLD 列表非法")

    try:
        gen = OpenAIGenerator(api_key=api_key, base_url=base_url, model=model)
        # Generate 2x candidates to give us filter headroom
        candidates = gen.generate(description, min_len, max_len, count * 2)
    except Exception as e:
        return jsonify({"success": False, "error": f"OpenAI 调用失败：{e}"}), 500

    # Build full domains across all TLDs
    full_domains: list[str] = []
    domain_to_candidate: dict[str, dict] = {}
    for cand in candidates:
        for tld in tlds:
            full = f"{cand['domain']}.{tld}"
            full_domains.append(full)
            domain_to_candidate[full] = cand

    statuses = check_domains(full_domains, tlds, timeout=5.0)

    available: list[dict] = []
    for full, status in statuses.items():
        if status != "available":
            continue
        cand = domain_to_candidate[full]
        available.append({
            "domain": full,
            "reason": cand["reason"],
            "length": len(cand["domain"]),
            "tld": full.split(".", 1)[1],
            "status": "available",
        })

    # Trim to requested count
    available = available[:count]

    response = {
        "success": True,
        "domains": available,
        "stats": {
            "generated": len(candidates),
            "available": len(available),
            "registered": len(full_domains) - len(available),
            "requested": count,
        },
    }

    if len(available) < count:
        response["warning"] = (
            f"仅生成 {len(available)} 个可注册域名（请求 {count} 个）。"
            f"可尝试增加 TLD 选项、放宽长度范围或调整措辞。"
        )

    return jsonify(response)


# ---------------------------------------------------------------------------
# 流式生成：SSE 实时推送进度；后台循环重试直到达 count 或用户停止。
# ---------------------------------------------------------------------------

# 用 job_id 持有"停止事件"，前端通过 POST /api/stop/<job_id> 触发停止。
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, threading.Event] = {}


def _sse(event: str, data: dict) -> str:
    """格式化为单条 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/api/generate-stream", methods=["POST"])
def api_generate_stream():
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    min_len = data.get("min_len")
    max_len = data.get("max_len")
    tlds = data.get("tlds") or []
    count = data.get("count")
    api_key = (data.get("api_key") or "").strip()
    base_url = (data.get("base_url") or "https://api.openai.com/v1").strip()
    model = (data.get("model") or "gpt-4o-mini").strip()

    # 复用 /api/generate 的校验
    if not description:
        return _bad_request("描述内容不能为空")
    if len(description) > 2000:
        return _bad_request("描述内容不能超过 2000 字符")
    if not api_key:
        return _bad_request("请先在设置中填入 OpenAI API Key")
    if not isinstance(min_len, int) or not isinstance(max_len, int):
        return _bad_request("长度范围必须为整数")
    if min_len < 2 or max_len > 20 or min_len > max_len:
        return _bad_request("长度范围非法（2-20，且 min <= max）")
    if not isinstance(count, int) or count < 1 or count > 50:
        return _bad_request("数量必须为 1-50 的整数")
    if not isinstance(tlds, list) or not tlds or not all(isinstance(t, str) for t in tlds):
        return _bad_request("TLD 列表非法")

    # 为本次任务创建 stop 事件
    job_id = f"job-{int(time.time()*1000)}-{os.urandom(4).hex()}"
    stop_event = threading.Event()
    with _JOBS_LOCK:
        _JOBS[job_id] = stop_event

    def generate():
        # 释放 job 注册（无论是否异常）
        try:
            yield _sse("start", {
                "job_id": job_id,
                "requested": count,
                "tlds": tlds,
                "min_len": min_len,
                "max_len": max_len,
                "ts": time.time(),
            })

            try:
                gen = OpenAIGenerator(api_key=api_key, base_url=base_url, model=model)
            except Exception as e:
                yield _sse("error", {"msg": f"初始化 OpenAI 客户端失败：{e}"})
                return

            # 累计：已用 candidate name -> candidate dict
            # 已用 full domain -> True（去重）
            seen_names: set[str] = set()
            seen_full: set[str] = set()
            available: list[dict] = []
            batch_no = 0
            t_start = time.time()

            # 每批生成数 = max(count, 4)，保证至少有进展
            BATCH_SIZE = max(count, 4)

            while len(available) < count:
                if stop_event.is_set():
                    yield _sse("stopped", {
                        "reason": "user",
                        "available": len(available),
                        "elapsed": round(time.time() - t_start, 2),
                    })
                    return

                batch_no += 1
                batch_t0 = time.time()
                yield _sse("batch_start", {
                    "n": batch_no,
                    "ts": time.time(),
                    "api": {
                        "name": "openai chat.completions",
                        "url": base_url.rstrip("/") + "/chat/completions",
                        "model": model,
                        "params": {
                            "description_chars": len(description),
                            "min_len": min_len,
                            "max_len": max_len,
                            "n": BATCH_SIZE,
                        },
                    },
                })

                try:
                    new_candidates = gen.generate(
                        description, min_len, max_len, BATCH_SIZE
                    )
                except Exception as e:
                    yield _sse("error", {
                        "msg": f"批次 {batch_no} OpenAI 调用失败：{e}",
                        "batch": batch_no,
                        "api": {
                            "name": "openai chat.completions",
                            "url": base_url.rstrip("/") + "/chat/completions",
                            "model": model,
                        },
                    })
                    # 失败不要立即退出；给用户看到错误，但继续下一批
                    # 避免单次抖动让任务死掉
                    time.sleep(1)
                    continue

                # 去重
                fresh = [c for c in new_candidates if c["domain"] not in seen_names]
                for c in new_candidates:
                    seen_names.add(c["domain"])

                # 拼 full domain
                full_domains: list[str] = []
                full_to_cand: dict[str, dict] = {}
                for cand in fresh:
                    for tld in tlds:
                        full = f"{cand['domain']}.{tld}"
                        if full in seen_full:
                            continue
                        seen_full.add(full)
                        full_domains.append(full)
                        full_to_cand[full] = cand

                yield _sse("api_call", {
                    "phase": "dmcheck",
                    "n": batch_no,
                    "api": {
                        "name": "dmcheck.app availability",
                        "url": "https://dmcheck.app/api/check",
                        "method": "GET",
                        "params": {
                            "domains": ",".join(full_domains),
                            "count": len(full_domains),
                        },
                        "timeout_s": 5.0,
                    },
                })
                dmcheck_t0 = time.time()
                statuses = check_domains(full_domains, tlds, timeout=5.0)
                dmcheck_took = round((time.time() - dmcheck_t0) * 1000, 1)
                # 给前端看每个候选的状态
                domain_status_list = [
                    {"domain": d, "status": statuses.get(d, "unknown")}
                    for d in full_domains
                ]
                yield _sse("api_result", {
                    "phase": "dmcheck",
                    "n": batch_no,
                    "took_ms": dmcheck_took,
                    "summary": {
                        "checked": len(full_domains),
                        "available": sum(
                            1 for s in statuses.values() if s == "available"
                        ),
                        "registered": sum(
                            1 for s in statuses.values() if s == "registered"
                        ),
                        "other": sum(
                            1 for s in statuses.values()
                            if s not in ("available", "registered")
                        ),
                    },
                    "items": domain_status_list,
                })

                if not full_domains:
                    yield _sse("batch_done", {
                        "n": batch_no,
                        "available_this_batch": 0,
                        "total_available": len(available),
                        "available_domains": [],
                        "elapsed": round(time.time() - batch_t0, 2),
                    })
                    continue

                batch_available = 0
                batch_available_domains: list[str] = []
                for full, status in statuses.items():
                    if status != "available":
                        continue
                    cand = full_to_cand[full]
                    available.append({
                        "domain": full,
                        "reason": cand["reason"],
                        "length": len(cand["domain"]),
                        "tld": full.split(".", 1)[1],
                        "status": "available",
                    })
                    batch_available_domains.append(full)
                    batch_available += 1
                    if len(available) >= count:
                        break

                yield _sse("batch_done", {
                    "n": batch_no,
                    "available_this_batch": batch_available,
                    "total_available": len(available),
                    "available_domains": batch_available_domains,
                    "elapsed": round(time.time() - batch_t0, 2),
                })

            # 截断（理论上不会超，但保险）
            available = available[:count]

            yield _sse("done", {
                "domains": available,
                "stats": {
                    "batches": batch_no,
                    "generated": len(seen_names),
                    "available": len(available),
                    "requested": count,
                },
                "elapsed": round(time.time() - t_start, 2),
            })
        finally:
            with _JOBS_LOCK:
                _JOBS.pop(job_id, None)

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )
    # SSE 不应被代理/CDN 缓冲
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@app.route("/api/stop/<job_id>", methods=["POST"])
def api_stop(job_id: str):
    """前端点"停止"时调用，触发对应 job 的 stop_event。"""
    with _JOBS_LOCK:
        evt = _JOBS.get(job_id)
    if evt is None:
        return jsonify({"success": False, "error": "job 不存在或已结束"}), 404
    evt.set()
    return jsonify({"success": True})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "5001"))
    # threaded=True 让 SSE 长连接不阻塞其它请求
    app.run(host="127.0.0.1", port=port, debug=True, threaded=True)