#!/usr/bin/env python3
import json
import threading
import time
import html as html_lib

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import os

from openai import OpenAI
from openai import AuthenticationError as OpenAIAuthenticationError
from openai import APIConnectionError as OpenAIAPIConnectionError

from generator import OpenAIGenerator
from checker import check_domains, check_domains_with_errors
import wechat_pusher

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
    push_peer_ids = data.get("push_peer_ids") or []

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
    push_peer_ids = data.get("push_peer_ids") or []

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


# ── 报告渲染 ──────────────────────────────────────────────────────────────

REPORTS_DIR = os.path.join("static", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _slugify_for_anchor(name: str) -> str:
    """生成 GitHub 兼容的锚点（小写、点转 dash、移除非字母数字）。"""
    import re
    s = name.lower().replace(".", "-")
    s = re.sub(r"[^a-z0-9\-_]", "", s)
    return s


def _specific_advice_for(domain: dict) -> str:
    """针对单个域名的具体建议（一句话）。"""
    name = domain.get("domain", "")
    length = domain.get("length", 0)
    tld = (domain.get("tld") or "").lower()
    if length <= 4:
        return f"【短域名】仅 {length} 字符，流通性高、抢注风险大，建议首批注册"
    if tld in ("io", "ai", "co"):
        return f"【热门后缀】.{tld} 在科技/AI 圈溢价高，估值更高"
    if tld in ("app", "dev", "cloud", "tech"):
        return f"【新顶级】.{tld} 适合技术产品定位，首年成本通常低于 .com"
    if length <= 6:
        return f"【中等长度】{length} 字符易记，建议与同前缀其他 TLD 联动注册防抢注"
    return f"建议在浏览器访问验证可访问性，优先选 5 年以上注册期降低续费风险"


def _ascii_bar(value: int, max_value: int, width: int = 16) -> str:
    """ASCII 横向条形图。"""
    if max_value <= 0:
        return " " * width
    filled = round(value / max_value * width)
    return "█" * filled + "·" * (width - filled)


def _render_markdown_report(description: str, domains: list[dict], stats: dict, job_id: str) -> str:
    """生成可读 MD 报告（极简版：聚焦"为什么要选这个域名"）。

    每个域名只展示三件事：
    - 【寓意】字面意思 + 象征
    - 【适合场景】品牌定位
    - 【调性】3-5 个关键词

    报告结构：
    1. 标题 + 需求描述（2 行）
    2. 推荐域名（N 个）+ 快速跳转
    3. 详细域名（前 10）
    4. 附录紧凑表（11+）
    5. 后续建议 Checklist
    """
    elapsed = stats.get("elapsed", 0)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats.get("ts", time.time())))
    n = len(domains)

    lines: list[str] = [
        f"# 智能域名生成报告",
        f"",
        f"**生成时间** {ts} · **耗时** {elapsed}s · **找到** {n} 个可注册",
        f"",
        f"## 需求",
        f"",
        f"> {description}",
        f"",
        f"---",
        f"",
    ]

    # ── 推荐域名 + 快速跳转 ──
    if n > 0:
        lines.append(f"## 推荐域名（{n} 个）")
        lines.append(f"")
        if n <= 10:
            toc_items = [f"[{i}. {d.get('domain', '')}](#{i}-{_slugify_for_anchor(d.get('domain', ''))})"
                         for i, d in enumerate(domains, 1)]
            lines.append("> 快速跳转：" + " · ".join(toc_items))
        else:
            toc_items = [f"[{i}. {d.get('domain', '')}](#{i}-{_slugify_for_anchor(d.get('domain', ''))})"
                         for i, d in enumerate(domains[:10], 1)]
            lines.append("> 【前 10 详细】" + " · ".join(toc_items))
            lines.append(">")
            lines.append("> 其余 " + str(n - 10) + " 个见文末【附录】")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    # ── 详细域名（前 10）──
    detailed = domains[:10] if n > 10 else domains
    for i, d in enumerate(detailed, 1):
        name = d.get("domain", "")
        meaning = (d.get("meaning") or "").strip()
        suitable_for = (d.get("suitable_for") or "").strip()
        vibe = (d.get("vibe") or "").strip()
        # 兼容老 reason 字段：用作 "一句话" 替代
        reason = (d.get("reason") or "").strip()
        length = d.get("length", len(name.split(".", 1)[0]))
        tld = d.get("tld", name.split(".", 1)[-1] if "." in name else "")

        lines.append(f"### {i}. {name}")
        lines.append(f"")
        # 三个核心段
        if meaning:
            lines.append(f"**【寓意】** {meaning}")
            lines.append(f"")
        if suitable_for:
            lines.append(f"**【适合场景】** {suitable_for}")
            lines.append(f"")
        if vibe:
            lines.append(f"**【调性】** {vibe}")
            lines.append(f"")
        # reason 字段如果只是非空就放最后（多数情况会是空，因为新 prompt 强制用其他字段）
        if reason and not (meaning and suitable_for and vibe):
            lines.append(f"**【一句话理由】** {reason}")
            lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    # ── 附录：紧凑列表（11 个之后）──
    if n > 10:
        rest = domains[10:]
        lines.extend([
            f"## 附录：其余 {len(rest)} 个域名",
            f"",
            f"| # | 域名 | 寓意 | 调性 |",
            f"|---|------|------|------|",
        ])
        for i, d in enumerate(rest, 11):
            name = d.get("domain", "")
            meaning = (d.get("meaning") or "").replace("|", "/").replace("\n", " ").strip()
            vibe = (d.get("vibe") or "").replace("|", "/").replace("\n", " ").strip()
            if len(meaning) > 60:
                meaning = meaning[:60] + "…"
            if len(vibe) > 40:
                vibe = vibe[:40] + "…"
            lines.append(f"| {i} | `{name}` | {meaning} | {vibe} |")
        lines.extend([
            f"",
            f"---",
            f"",
        ])

    # ── 后续建议 Checklist ──
    lines.extend([
        f"## 后续建议",
        f"",
        f"- [ ] 浏览器逐个打开验证可访问性",
        f"- [ ] 同前缀多 TLD 联动注册（防抢注）",
        f"- [ ] 优先注册 5 字符以内的短域名",
        f"- [ ] 注册商：Cloudflare Registrar / Namecheap / Porkbun",
        f"- [ ] 社交媒体账号同步注册（GitHub / X / 小红书）",
        f"- [ ] WHOIS Privacy 开启",
        f"",
        f"**【针对本次】**",
        f"",
    ])
    for i, d in enumerate(domains[:3], 1):
        name = d.get("domain", "")
        advice = _specific_advice_for(d)
        lines.append(f"- [ ] **{name}** — {advice}")
    if n > 3:
        lines.append(f"- [ ] 其余 {n - 3} 个域名按上文【寓意 / 适合场景 / 调性】逐个评估")

    lines.extend([
        f"",
        f"---",
        f"",
        f"_本报告由 智能域名生成器 自动生成 · {ts}_",
    ])
    return "\n".join(lines)


def _render_html_report(description: str, domains: list[dict], stats: dict, job_id: str) -> str:
    """生成浏览器可看的 HTML 预览。"""
    elapsed = stats.get("elapsed", 0)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats.get("ts", time.time())))
    desc_esc = html_lib.escape(description).replace("\n", "<br>")
    cards = []
    for i, d in enumerate(domains, 1):
        name = d.get("domain", "")
        reason = (d.get("reason") or "").replace("\n", " ").strip()
        if len(reason) > 300:
            reason = reason[:300] + "…"
        length = d.get("length", len(name.split(".", 1)[0]))
        tld = d.get("tld", name.split(".", 1)[-1] if "." in name else "")
        cards.append(f"""
        <div class="domain-card">
          <div class="domain-card-head">
            <span class="domain-num">{i}</span>
            <span class="domain-name">{html_lib.escape(name)}</span>
            <span class="domain-badge">. {html_lib.escape(tld)}</span>
            <span class="domain-len">{length}字符</span>
          </div>
          <div class="domain-reason">💡 {html_lib.escape(reason)}</div>
        </div>""")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>域名生成报告 · {job_id}</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #1c1f26; --border: #2a2f3a;
    --text: #e6e8ee; --muted: #8b94a3; --accent: #4f9dff;
    --good: #00c896;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 16px; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
    line-height: 1.6;
  }}
  .container {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin: 0 0 8px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  .meta code {{ background: var(--panel); padding: 2px 6px; border-radius: 4px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; margin-bottom: 20px;
  }}
  .panel h2 {{ margin-top: 0; font-size: 18px; }}
  .desc {{ white-space: pre-wrap; color: #c8ced9; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }}
  .stat {{ background: #15181f; border-radius: 8px; padding: 12px; text-align: center; }}
  .stat-num {{ font-size: 24px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .domain-card {{
    background: #15181f; border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
    transition: border-color .15s;
  }}
  .domain-card:hover {{ border-color: var(--good); }}
  .domain-card-head {{
    display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
  }}
  .domain-num {{
    background: var(--accent); color: #0f1115; border-radius: 50%;
    width: 22px; height: 22px; display: inline-flex; align-items: center;
    justify-content: center; font-size: 12px; font-weight: 700; flex-shrink: 0;
  }}
  .domain-name {{ font-size: 16px; font-weight: 600; color: var(--good); }}
  .domain-badge {{
    font-size: 11px; color: var(--muted); background: #20242c;
    padding: 2px 8px; border-radius: 999px;
  }}
  .domain-len {{ margin-left: auto; font-size: 12px; color: var(--muted); }}
  .domain-reason {{ color: #c8ced9; font-size: 13px; padding-left: 32px; }}
  footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🎯 智能域名生成报告</h1>
  <div class="meta">
    任务 ID：<code>{html_lib.escape(job_id)}</code> · {ts} · 用时 {elapsed}s
  </div>

  <div class="panel">
    <h2>📝 需求描述</h2>
    <div class="desc">{desc_esc}</div>
  </div>

  <div class="panel">
    <h2>📊 统计概览</h2>
    <div class="stats">
      <div class="stat"><div class="stat-num">{stats.get('requested', 0)}</div><div class="stat-label">请求</div></div>
      <div class="stat"><div class="stat-num">{stats.get('generated', 0)}</div><div class="stat-label">AI 生成</div></div>
      <div class="stat"><div class="stat-num">{len(domains)}</div><div class="stat-label">可注册</div></div>
      <div class="stat"><div class="stat-num">{stats.get('batches', 0)}</div><div class="stat-label">批次</div></div>
      <div class="stat"><div class="stat-num">{elapsed}s</div><div class="stat-label">耗时</div></div>
    </div>
  </div>

  <div class="panel">
    <h2>✅ 推荐域名（{len(domains)} 个）</h2>
    {"".join(cards)}
  </div>

  <footer>由 智能域名生成器 自动生成 · {ts}</footer>
</div>
</body>
</html>"""


def _save_report(job_id: str, description: str, domains: list[dict], stats: dict) -> dict:
    """写 MD + HTML，返回可用 URL。"""
    md = _render_markdown_report(description, domains, stats, job_id)
    html_doc = _render_html_report(description, domains, stats, job_id)
    md_path = os.path.join(REPORTS_DIR, f"{job_id}.md")
    html_path = os.path.join(REPORTS_DIR, f"{job_id}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return {
        "md_path": md_path,
        "html_path": html_path,
        "md_url": f"/reports/{job_id}.md",
        "html_url": f"/reports/{job_id}",
        "size_bytes": len(md.encode("utf-8")),
    }


@app.route("/reports/<path:fname>")
def reports_handler(fname: str):
    """统一处理 /reports/<file>。

    - `xxx.md`  → 服务端渲染为 HTML 返回（让浏览器直接看渲染后的报告）
                  ?raw=1 走 raw 文本下载（Content-Disposition: attachment）
    - `xxx.html` → 返回原始 HTML 报告（Content-Type: text/html）
    - 不含后缀的 job_id 自动补 .html

    防止路径穿越：fname 中不能含 / 或 .. 。
    """
    if "/" in fname or ".." in fname:
        return jsonify({"error": "invalid path"}), 400

    # 没有后缀 → 当作 job_id，补 .html
    if "." not in fname:
        fname = fname + ".html"

    full = os.path.join(REPORTS_DIR, fname)
    if not os.path.exists(full):
        return jsonify({"error": "report not found"}), 404

    if fname.endswith(".md"):
        # raw=1 走原始下载（供拷贝 / 二次处理）
        if request.args.get("raw") == "1":
            return send_from_directory(
                REPORTS_DIR, fname,
                as_attachment=True,
                download_name=fname,
                mimetype="text/markdown; charset=utf-8",
            )
        # 默认：服务端把 MD 渲染成 HTML 展示
        with open(full, "r", encoding="utf-8") as f:
            md_text = f.read()
        import markdown  # 延迟导入，避免无关路径开销
        body_html = markdown.markdown(
            md_text,
            extensions=["extra", "sane_lists", "tables", "fenced_code", "toc"],
        )
        return _render_report_shell(fname, body_html, md_text)

    return send_from_directory(REPORTS_DIR, fname)


def _render_report_shell(fname: str, body_html: str, md_source: str) -> Response:
    """报告页外壳：复用现有 style.css，左侧是渲染后的 HTML，顶部工具条。"""
    title = fname.rsplit(".", 1)[0]
    raw_url = f"/reports/{fname}?raw=1"
    # html 报告的链接（同名 .html）
    html_peer = fname[:-3]  # 去掉 .md

    shell = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title} · 智能域名生成报告</title>
<link rel="stylesheet" href="/static/style.css">
<style>
  .report-shell {{ max-width: 860px; margin: 32px auto; padding: 0 24px; }}
  .report-toolbar {{
    position: sticky; top: 0; z-index: 10;
    background: var(--bg, #fff); border-bottom: 1px solid #e5e5e5;
    padding: 12px 0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    margin-bottom: 24px;
  }}
  .report-toolbar a {{
    text-decoration: none; color: #2563eb; font-size: 14px;
    padding: 6px 12px; border: 1px solid #e5e5e5; border-radius: 6px;
  }}
  .report-toolbar a:hover {{ background: #f5f5f5; }}
  .report-toolbar .title {{ font-weight: 600; color: #333; margin-right: auto; }}
  .report-body {{ line-height: 1.7; }}
  .report-body h1 {{ font-size: 28px; margin-top: 0; }}
  .report-body h2 {{ font-size: 22px; border-bottom: 1px solid #e5e5e5; padding-bottom: 6px; margin-top: 36px; }}
  .report-body h3 {{ font-size: 18px; margin-top: 28px; }}
  .report-body blockquote {{
    border-left: 4px solid #2563eb; padding: 8px 16px;
    color: #555; background: #f8fafc; margin: 16px 0;
  }}
  .report-body code {{ background: #f1f5f9; padding: 1px 6px; border-radius: 3px; font-size: 0.9em; }}
  .report-body pre {{ background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 6px; overflow-x: auto; }}
  .report-body pre code {{ background: transparent; color: inherit; padding: 0; }}
  .report-body table {{ border-collapse: collapse; margin: 16px 0; width: 100%; }}
  .report-body th, .report-body td {{
    border: 1px solid #e5e5e5; padding: 8px 12px; text-align: left;
  }}
  .report-body th {{ background: #f8fafc; font-weight: 600; }}
  .report-body ul li {{ list-style: none; }}
  .report-body ul li::before {{ content: "☐ "; color: #94a3b8; }}
  .report-body hr {{ border: none; border-top: 1px solid #e5e5e5; margin: 28px 0; }}
</style>
</head>
<body>
<div class="report-shell">
  <div class="report-toolbar">
    <span class="title">{fname}</span>
    <a href="{raw_url}">下载 .md</a>
    <a href="/reports/{html_peer}">HTML 预览版</a>
    <a href="/">← 返回首页</a>
  </div>
  <article class="report-body">
{body_html}
  </article>
</div>
</body>
</html>"""
    return Response(shell, mimetype="text/html; charset=utf-8")


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
    push_peer_ids = data.get("push_peer_ids") or []

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
                    elapsed = round(time.time() - t_start, 2)
                    yield _sse("stopped", {
                        "reason": "user",
                        "available": len(available),
                        "elapsed": elapsed,
                    })
                    if wechat_pusher.is_configured():
                        push_data = wechat_pusher.push_stopped(
                            description, available, count, elapsed,
                            reason="user",
                            peer_ids=push_peer_ids,
                        )
                        yield _sse("wechat_pushed", {**push_data, "phase": "stopped"})
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
                        "name": "dmcheck.app whois",
                        "url": "https://dmcheck.app/api/whois/<domain>",
                        "method": "GET",
                        "params": {
                            "domains": full_domains,
                            "count": len(full_domains),
                            "concurrency": 8,
                        },
                        "timeout_s_per_req": 5.0,
                    },
                })
                dmcheck_t0 = time.time()
                statuses, errors = check_domains_with_errors(
                    full_domains, tlds, timeout=5.0
                )
                dmcheck_took = round((time.time() - dmcheck_t0) * 1000, 1)
                # 给前端看每个候选的状态 + 错误原因
                domain_status_list = []
                for d in full_domains:
                    item = {
                        "domain": d,
                        "status": statuses.get(d, "unknown"),
                    }
                    err = errors.get(d)
                    if err:
                        item["error"] = err
                    domain_status_list.append(item)
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
                    domain_entry = {
                        "domain": full,
                        "reason": cand["reason"],
                        "length": len(cand["domain"]),
                        "tld": full.split(".", 1)[1],
                        "status": "available",
                    }
                    available.append(domain_entry)
                    batch_available_domains.append(full)
                    batch_available += 1

                    # 实时推送：每发现 1 个可注册域名 → 立即推一条
                    if wechat_pusher.is_configured():
                        push_data = wechat_pusher.push_new_domain(
                            domain_entry,
                            total_now=len(available),
                            requested=count,
                            peer_ids=push_peer_ids,
                        )
                        yield _sse("wechat_pushed", {
                            **push_data,
                            "phase": "realtime",
                            "domain": domain_entry["domain"],
                        })

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

            stats = {
                "batches": batch_no,
                "generated": len(seen_names),
                "available": len(available),
                "requested": count,
                "elapsed": round(time.time() - t_start, 2),
                "ts": time.time(),
            }
            yield _sse("done", {
                "domains": available,
                "stats": stats,
                "elapsed": stats["elapsed"],
            })

            # 微信最终推送：写 MD + HTML 报告 + 推链接到所有目标联系人
            if wechat_pusher.is_configured():
                report_info = _save_report(job_id, description, available, stats)
                report_url = request.host_url.rstrip("/") + report_info["html_url"]
                push_data = wechat_pusher.push_report(
                    description, available, stats,
                    report_url=report_url,
                    peer_ids=push_peer_ids,
                )
                yield _sse("report_ready", {
                    "job_id": job_id,
                    "report_url": report_info["html_url"],
                    "md_url": report_info["md_url"],
                    "size_bytes": report_info["size_bytes"],
                })
                yield _sse("wechat_pushed", {
                    **push_data,
                    "phase": "final",
                    "report_url": report_url,
                })
        except Exception as e:
            # 系统异常退出推送
            elapsed = round(time.time() - t_start, 2) if 't_start' in locals() else 0
            yield _sse("error", {
                "msg": f"生成异常：{e}",
                "available": len(available) if 'available' in locals() else 0,
                "elapsed": elapsed,
            })
            if wechat_pusher.is_configured():
                _avail = available if 'available' in locals() else []
                push_data = wechat_pusher.push_stopped(
                    description, _avail, count, elapsed,
                    reason="error",
                    peer_ids=push_peer_ids,
                )
                yield _sse("wechat_pushed", {**push_data, "phase": "stopped"})
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


@app.route("/api/wechat/status", methods=["GET"])
def api_wechat_status():
    """查询微信 Bot 状态、登录状态、联系人列表。"""
    status = wechat_pusher.get_status()
    status["bot_reachable"] = wechat_pusher.is_configured()
    return jsonify(status)


@app.route("/api/wechat/login", methods=["POST"])
def api_wechat_login():
    """触发扫码登录（Bot 端会返回 qrcode）。"""
    result = wechat_pusher.login()
    return jsonify(result), 200


@app.route("/api/wechat/logout", methods=["POST"])
def api_wechat_logout():
    """登出微信。"""
    result = wechat_pusher.logout()
    return jsonify(result), 200


@app.route("/api/wechat/test", methods=["POST"])
def api_wechat_test():
    """给指定联系人发测试消息。body: {peer_id}"""
    data = request.get_json(silent=True) or {}
    peer_id = data.get("peer_id")
    if not peer_id:
        return jsonify({"ok": False, "error": "peer_id 必填"}), 400
    result = wechat_pusher.push_test(peer_id)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/wechat/send", methods=["POST"])
def api_wechat_send():
    """给指定联系人发送消息（用于前端手动触发推送）。"""
    data = request.get_json(silent=True) or {}
    peer_id = data.get("peer_id")
    text = data.get("text")
    if not peer_id or not text:
        return jsonify({"ok": False, "error": "peer_id 和 text 必填"}), 400
    result = wechat_pusher.send_message(peer_id, text)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "5001"))
    # threaded=True 让 SSE 长连接不阻塞其它请求
    # debug=False + use_reloader=False 避免开发时 reloader 进程偶发死掉
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)