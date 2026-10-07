#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_from_directory
import os

from openai import OpenAI
from openai import AuthenticationError as OpenAIAuthenticationError
from openai import APIConnectionError as OpenAIAPIConnectionError

from generator import OpenAIGenerator
from checker import check_domains

app = Flask(__name__, static_folder="static", static_url_path="/static")


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)