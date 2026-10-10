// 智能域名生成器 - 前端逻辑

const STORAGE_KEY = "yuming_config";

// ── Animation helpers ─────────────────────────────────────
const prefersReducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * 点击波纹效果：给按钮添加 .ripple 子元素
 */
function attachRipple(btn) {
  if (!btn) return;
  btn.addEventListener('click', (e) => {
    if (prefersReducedMotion()) return;
    const rect = btn.getBoundingClientRect();
    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    const size = Math.max(rect.width, rect.height) * 0.6;
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
    ripple.style.top  = (e.clientY - rect.top  - size / 2) + 'px';
    btn.appendChild(ripple);
    setTimeout(() => ripple.remove(), 550);
  });
}

/**
 * 滚动进入视口的入场动画（仅用于 JS 动态插入的元素，如 TLD chips、域名卡、联系人）
 * - 已经在视口内的：直接 visible，立即播放
 * - 还没进视口的：IntersectionObserver 等待
 * - reduced-motion / 不支持 IO：直接可见，不动画
 * - 兜底：1.2s 强制显示（防 IO 不触发）
 */
function observeEntrance(elements, baseDelay = 0) {
  if (!Array.isArray(elements) || !elements.length) return;
  const reduce = prefersReducedMotion() || !('IntersectionObserver' in window);
  if (reduce) {
    elements.forEach((el) => el.classList.add('visible'));
    return;
  }
  const vh = window.innerHeight || 800;
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const idx = Number(el.dataset.idx || 0);
        el.style.animationDelay = (baseDelay + idx * 0.06) + 's';
        el.classList.add('visible');
        io.unobserve(el);
      }
    });
  }, { threshold: 0.01 });
  elements.forEach((el, i) => {
    el.dataset.idx = i;
    const rect = el.getBoundingClientRect();
    if (rect.top < vh && rect.bottom > 0) {
      el.style.animationDelay = (baseDelay + i * 0.06) + 's';
      el.classList.add('visible');
    } else {
      io.observe(el);
    }
    setTimeout(() => el.classList.add('visible'), 1200);
  });
}

/**
 * 按钮 loading 状态
 */
function setButtonLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn.dataset.label = btn.dataset.label || btn.querySelector('.btn-label')?.textContent || btn.textContent;
    btn.classList.add('loading');
    btn.disabled = true;
    const label = btn.querySelector('.btn-label');
    if (label) {
      label.textContent = '生成中';
    }
    if (!btn.querySelector('.spinner')) {
      const sp = document.createElement('span');
      sp.className = 'spinner';
      btn.insertBefore(sp, btn.firstChild);
    }
  } else {
    btn.classList.remove('loading');
    btn.disabled = false;
    const sp = btn.querySelector('.spinner');
    if (sp) sp.remove();
    const label = btn.querySelector('.btn-label');
    if (label && btn.dataset.label) label.textContent = btn.dataset.label;
  }
}

// DOM refs
const $ = (id) => document.getElementById(id);
const $description = $("description");
const $tldList = $("tld-list");
const $minLen = $("min-len");
const $maxLen = $("max-len");
const $count = $("count");
const $domainStyle = $("domain-style");
const $generateBtn = $("generate-btn");
const $status = $("status");
const $results = $("results");
const $settingsBtn = $("settings-btn");
const $settingsModal = $("settings-modal");
const $settingsSave = $("settings-save");
const $settingsCancel = $("settings-cancel");
const $testConn = $("test-conn");
const $testResult = $("test-result");
const $apiKey = $("api-key");
const $baseUrl = $("base-url");
const $model = $("model");
const $stopBtn = $("stop-btn");
const $logList = $("log-list");
const $clearLog = $("clear-log");

// 微信 UI 元素
const $wechatBtn = $("wechat-btn");
const $wechatStatusDot = $("wechat-status-dot");
const $wechatModal = $("wechat-modal");
const $wechatBotState = $("wechat-bot-state");
const $wechatLoginState = $("wechat-login-state");
const $wechatAccount = $("wechat-account");
const $wechatRefresh = $("wechat-refresh");
const $wechatLogin = $("wechat-login");
const $wechatLogout = $("wechat-logout");
const $wechatHint = $("wechat-hint");
const $wechatQrcode = $("wechat-qrcode");
const $wechatQrcodeImg = $("wechat-qrcode-img");
const $wechatQrcodeUrl = $("wechat-qrcode-url");
const $wechatQrcodeLink = $("wechat-qrcode-link");
const $wechatContactList = $("wechat-contact-list");
const $wechatContactCount = $("wechat-contact-count");
const $wechatAutoPush = $("wechat-auto-push");
const $wechatTest = $("wechat-test");
const $wechatCancel = $("wechat-cancel");
const $wechatSave = $("wechat-save");

let availableTlds = [];
const selectedTlds = new Set();
let currentJobId = null;
let currentEs = null;

// 微信状态
let wechatState = {
  botReachable: false,
  status: "unknown",          // disconnected | logging_in | connected | session_expired
  accountId: null,
  qrcodeUrl: null,           // 当前二维码 URL
  awaitingFirstMessage: false, // 刚连上、等待对方发第一条消息
  firstMessageArrived: false,  // 一次性：收到第一条消息，等待 auto-refresh
  contacts: [],               // [{peerId, displayName, lastText, lastTs, ...}]
  selectedPeerIds: new Set(), // 用户勾选的推送目标
  autoPush: true,             // 生成完成后是否自动推
  lastResult: null,           // 缓存最近一次生成结果用于"重推"
};

// ---- Config persistence ----
function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const cfg = JSON.parse(raw);
    if (cfg.api_key) $apiKey.value = cfg.api_key;
    if (cfg.base_url) $baseUrl.value = cfg.base_url;
    if (cfg.model) $model.value = cfg.model;
  } catch (e) {
    console.warn("load config failed", e);
  }
}

function saveConfig() {
  const cfg = {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim(),
    model: $model.value.trim(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

/**
 * 输入变化即持久化（用户上一版反馈"AI 设置未保存在本地，禁止每次去设置"）。
 * 实现策略：
 *   1) input 失焦 / change 时自动写
 *   2) 关闭 modal 任何路径都写（hook 唯一出口 hideSettings）
 *   3) 即使用户忘了点保存按钮，下一次刷新配置仍在
 */
function bindAutoSave() {
  [$apiKey, $baseUrl, $model].forEach(($el) => {
    if (!$el) return;
    $el.addEventListener("change", () => saveConfig());
    $el.addEventListener("blur", () => saveConfig());
  });
}

function getConfig() {
  return {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim() || "https://api.openai.com/v1",
    model: $model.value.trim() || "gpt-4o-mini",
  };
}

function hasConfig() {
  return $apiKey.value.trim().length > 0;
}

// ---- TLD loading ----
async function fetchJson(url, options) {
  try {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      let body = "";
      try { body = await resp.text(); } catch (_) {}
      throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200) || resp.statusText}`);
    }
    return await resp.json();
  } catch (e) {
    if (e instanceof TypeError && /fetch|network|abort/i.test(e.message)) {
      throw new Error("无法连接到后端（127.0.0.1:5001）。请确认已运行 ./run.sh");
    }
    throw e;
  }
}

// ---- 运行日志（倒序：最新在最上面） ----
function logLine(text, level = "info") {
  const li = document.createElement("li");
  li.className = "log-level-" + level;
  const t = new Date();
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const ss = String(t.getSeconds()).padStart(2, "0");
  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = `[${hh}:${mm}:${ss}]`;
  const msg = document.createElement("span");
  msg.textContent = " " + text;
  li.appendChild(time);
  li.appendChild(msg);
  // 倒序：插到最前
  $logList.insertBefore(li, $logList.firstChild);
}

async function loadTlds() {
  try {
    const data = await fetchJson("/api/tlds");
    availableTlds = data.tlds || [];
    // Default: select first 5
    availableTlds.slice(0, 5).forEach((t) => selectedTlds.add(t));
    renderTlds();
  } catch (e) {
    $status.textContent = "TLD 列表加载失败：" + e.message;
    $status.classList.add("error");
  }
}

function renderTlds() {
  $tldList.innerHTML = "";
  availableTlds.forEach((tld) => {
    const chip = document.createElement("span");
    chip.className = "tld-chip" + (selectedTlds.has(tld) ? " selected" : "");
    chip.innerHTML = '<span class="chip-dot"></span>.' + tld;
    chip.addEventListener("click", () => {
      const wasSelected = selectedTlds.has(tld);
      if (wasSelected) selectedTlds.delete(tld);
      else selectedTlds.add(tld);
      chip.classList.toggle("selected");
      // 微缩放反馈
      if (!prefersReducedMotion()) {
        chip.style.transform = "scale(0.92)";
        setTimeout(() => { chip.style.transform = ""; }, 120);
      }
    });
    $tldList.appendChild(chip);
  });
  // TLD 入场 stagger
  observeEntrance(Array.from($tldList.children));
}

// ---- Generation flow ----

// 推送事件日志（最近 20 条），用于前端"推送事件"面板
const pushEventLog = [];

function addPushEvent(evt) {
  pushEventLog.unshift(evt);
  if (pushEventLog.length > 20) pushEventLog.length = 20;
  renderPushEventLog();
  // 更新面板标题计数
  const $count = document.getElementById("push-event-count");
  if ($count) {
    $count.textContent = pushEventLog.length;
    $count.classList.add("bump");
    setTimeout(() => $count.classList.remove("bump"), 600);
  }
  // 自动展开（如果之前是收起）
  const $panel = document.getElementById("push-event-panel");
  if ($panel && $panel.classList.contains("collapsed")) {
    $panel.classList.remove("collapsed");
  }
}

function renderPushEventLog() {
  const $panel = document.getElementById("push-event-log");
  if (!$panel) return;
  if (!pushEventLog.length) {
    $panel.innerHTML = '<div class="push-event-empty">尚未推送任何消息</div>';
    return;
  }
  $panel.innerHTML = pushEventLog.map((e) => {
    const time = new Date(e.ts).toLocaleTimeString("zh-CN", { hour12: false });
    if (e.kind === "realtime") {
      return `<div class="push-event-row realtime">
        <div class="push-event-time">${time}</div>
        <div class="push-event-icon">🆕</div>
        <div class="push-event-body">
          <div class="push-event-title">推送可注册域名 <code>${escapeHtml(e.domain)}</code></div>
          <div class="push-event-meta">${e.peerCount} 个目标 · ${e.ok ? "✅ 成功" : "❌ " + escapeHtml(e.error || "失败")}</div>
        </div>
      </div>`;
    }
    if (e.kind === "report") {
      return `<div class="push-event-row report">
        <div class="push-event-time">${time}</div>
        <div class="push-event-icon">📄</div>
        <div class="push-event-body">
          <div class="push-event-title">生成完整报告 <a href="${e.url}" target="_blank">${e.url}</a></div>
          <div class="push-event-meta">${e.peerCount} 个目标 · ${e.ok ? "✅ 已推送链接" : "❌ " + escapeHtml(e.error || "失败")}</div>
        </div>
      </div>`;
    }
    if (e.kind === "stopped") {
      return `<div class="push-event-row stopped">
        <div class="push-event-time">${time}</div>
        <div class="push-event-icon">${e.reason === "user" ? "🛑" : "💥"}</div>
        <div class="push-event-body">
          <div class="push-event-title">${e.reason === "user" ? "用户停止" : "系统异常"} 推送停止消息</div>
          <div class="push-event-meta">${e.peerCount} 个目标 · ${e.ok ? "✅" : "❌ " + escapeHtml(e.error || "失败")}</div>
        </div>
      </div>`;
    }
    return "";
  }).join("");
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function handleWechatPushed(dataObj) {
  if (!dataObj) return;
  const phase = dataObj.phase;
  const peers = (dataObj.peer_ids || []).length || 1;
  const ok = !!dataObj.ok;
  const error = dataObj.error || null;
  const ts = Date.now();
  if (phase === "realtime") {
    logLine(
      `🆕 推送新域名 ${dataObj.domain} → ${peers} 个目标 ${ok ? "✓" : "✗ " + error}`,
      ok ? "info" : "warn"
    );
    addPushEvent({ kind: "realtime", domain: dataObj.domain, peerCount: peers, ok, error, ts });
  } else if (phase === "final") {
    logLine(
      `📄 报告已推 ${peers} 个目标 ${ok ? "✓" : "✗ " + error}\n      └ 链接：${dataObj.report_url || ""}`,
      ok ? "info" : "warn"
    );
    addPushEvent({ kind: "report", url: dataObj.report_url, peerCount: peers, ok, error, ts });
  } else if (phase === "stopped") {
    logLine(
      `🛑 停止消息已推 ${peers} 个目标 ${ok ? "✓" : "✗ " + error}`,
      ok ? "info" : "warn"
    );
    addPushEvent({ kind: "stopped", reason: dataObj.reason || "user", peerCount: peers, ok, error, ts });
  } else {
    // 兼容老格式（仅 ok 字段）
    if (ok) {
      logLine(`微信推送 ✓ ${dataObj.peer_id || ""}`.trim(), "info");
    } else if (dataObj.needs_target) {
      logLine("微信推送：未选择目标，已在弹窗里选", "warn");
    } else {
      logLine(`微信推送失败：${error}`, "error");
    }
  }
}

function setStatus(msg, type) {
  $status.textContent = msg || "";
  $status.classList.remove("error", "success");
  if (type) $status.classList.add(type);
}

async function generate() {
  const description = $description.value.trim();
  if (!description) {
    setStatus("请输入描述", "error");
    return;
  }
  if (!hasConfig()) {
    setStatus("请先在设置中填入 OpenAI API Key", "error");
    openSettings();
    return;
  }
  if (selectedTlds.size === 0) {
    setStatus("请至少选择一个 TLD 后缀", "error");
    return;
  }

  const minLen = parseInt($minLen.value, 10);
  const maxLen = parseInt($maxLen.value, 10);
  const count = parseInt($count.value, 10);
  const domainStyle = $domainStyle.value || "letters";

  if (isNaN(minLen) || isNaN(maxLen) || minLen > maxLen) {
    setStatus("长度范围非法", "error");
    return;
  }
  if (isNaN(count) || count < 1) {
    setStatus("数量非法", "error");
    return;
  }
  if (domainStyle !== "letters" && domainStyle !== "letters_and_digits") {
    setStatus("字符风格非法", "error");
    return;
  }

  const cfg = getConfig();
  setButtonLoading($generateBtn, true);
  $stopBtn.classList.remove("hidden");
  $results.innerHTML = "";
  setStatus("生成中…", "loading");
  logLine(
    `开始生成：请求 ${count} 个，TLD=[${Array.from(selectedTlds).join(", ")}]，长度 ${minLen}-${maxLen}，风格 ${domainStyle === "letters" ? "纯字母" : "字母+数字"}`,
    "info"
  );

  // EventSource 不支持 POST + body；先 POST /api/generate-stream 启动任务，
  // 然后让后端在第一次 yield 时返回 job_id，前端再 EventSource 连 /api/generate-stream/<job_id>
  // —— 但这样会复杂。简化：直接用 fetch + ReadableStream 读 SSE，兼容 POST。
  let resp;
  try {
    resp = await fetch("/api/generate-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        min_len: minLen,
        max_len: maxLen,
        tlds: Array.from(selectedTlds),
        count,
        domain_style: domainStyle,
        api_key: cfg.api_key,
        base_url: cfg.base_url,
        model: cfg.model,
        // 微信推送目标（前端勾选的 peerId 列表）
        push_peer_ids: Array.from(wechatState.selectedPeerIds || []),
      }),
    });
  } catch (e) {
    setStatus("网络错误：" + e.message, "error");
    logLine("网络错误：" + e.message, "error");
    finishGenerate();
    return;
  }

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch (_) {}
    setStatus(`请求失败 (${resp.status})：${body.slice(0, 200)}`, "error");
    logLine(`请求失败 HTTP ${resp.status}：${body.slice(0, 200)}`, "error");
    finishGenerate();
    return;
  }

  if (!resp.body) {
    setStatus("浏览器不支持流式响应", "error");
    logLine("浏览器不支持流式响应", "error");
    finishGenerate();
    return;
  }

  // 解析 SSE
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let finalDomains = null;
  let finalStats = null;
  let shouldStop = false;

  /**
   * 把 API 元数据格式化为单行可读文本。
   * 例：POST https://api.openai.com/v1/chat/completions · model=gpt-4o-mini · n=10
   */
  function formatApi(api) {
    if (!api) return "";
    const parts = [];
    if (api.method) parts.push(api.method);
    if (api.url) parts.push(api.url);
    const tail = [];
    if (api.model) tail.push(`model=${api.model}`);
    if (api.params) {
      for (const [k, v] of Object.entries(api.params)) {
        if (v === null || v === undefined) continue;
        // 大段文本截断
        const sv = typeof v === "string" && v.length > 60 ? v.slice(0, 60) + "…" : v;
        tail.push(`${k}=${sv}`);
      }
    }
    if (api.timeout_s) tail.push(`timeout=${api.timeout_s}s`);
    const main = parts.join(" ");
    return main + (tail.length ? " · " + tail.join(" · ") : "");
  }

  /**
   * 渲染多行日志：一行总览 + N 行域名明细
   */
  function logBlock(header, items, opts = {}) {
    logLine(header, opts.level || "info");
    if (!items || !items.length) return;
    const indent = "    ";  // 4 空格的视觉缩进
    for (const it of items) {
      let dot, cls;
      if (it.status === "available") {
        dot = "✓"; cls = "info";
      } else if (it.status === "registered") {
        dot = "✗"; cls = "warn";
      } else {
        // unknown / reserved / anything else
        dot = "?"; cls = "error";
      }
      const tail = it.error ? `  (${it.error})` : "";
      logLine(`${indent}${dot} ${it.domain}  [${it.status}]${tail}`, cls);
    }
  }

  function handleEvent(eventName, dataObj) {
    switch (eventName) {
      case "start":
        currentJobId = dataObj.job_id;
        logLine(`任务 ${currentJobId} 启动（请求 ${dataObj.requested} 个）`, "info");
        break;
      case "batch_start":
        logLine(
          `批次 ${dataObj.n}：调用 OpenAI…\n      └ ${formatApi(dataObj.api)}`,
          "info"
        );
        break;
      case "api_call":
        logLine(
          `批次 ${dataObj.n}：${dataObj.phase} API 调用\n      └ ${formatApi(dataObj.api)}`,
          "info"
        );
        break;
      case "api_result": {
        const s = dataObj.summary || {};
        const head = dataObj.phase === "dmcheck"
          ? `批次 ${dataObj.n}：dmcheck 返回（${dataObj.took_ms}ms）— 可注册 ${s.available} / 已注册 ${s.registered} / 其他 ${s.other}`
          : `批次 ${dataObj.n}：${dataObj.phase} 返回（${dataObj.took_ms}ms）`;
        logBlock(head, dataObj.items);
        break;
      }
      case "batch_check":
        // 旧事件名保留兼容（虽然新版后端用 api_call/api_result）
        logLine(`批次 ${dataObj.n}：生成 ${dataObj.generated} 个候选，去重后 ${dataObj.fresh} 个，待查 ${dataObj.to_check} 个`, "info");
        break;
      case "batch_done": {
        const head = `批次 ${dataObj.n} 完成：本批可注册 ${dataObj.available_this_batch} 个，累计 ${dataObj.total_available}/${count}（${dataObj.elapsed}s）`;
        if (dataObj.available_domains && dataObj.available_domains.length) {
          const items = dataObj.available_domains.map((d) => ({ domain: d, status: "available" }));
          logBlock(head, items, { level: dataObj.available_this_batch > 0 ? "info" : "warn" });
        } else {
          logLine(head, dataObj.available_this_batch > 0 ? "info" : "warn");
        }
        break;
      }
      case "stopped":
        logLine(`已停止（用户中止）：累计 ${dataObj.available} 个可注册（${dataObj.elapsed}s）`, "warn");
        shouldStop = true;
        break;
      case "wechat_pushed": handleWechatPushed(dataObj); break;
      case "report_ready":
        if (dataObj.report_url) {
          logLine(`📄 报告已生成：${dataObj.report_url}`, "info");
          addPushEvent({ kind: "report", url: dataObj.report_url, ts: Date.now() });
        }
        break;
      case "error":
        logLine("错误：" + dataObj.msg, "error");
        if (dataObj.api) {
          logLine("      └ 失败接口：" + formatApi(dataObj.api), "error");
        }
        break;
      case "done":
        finalDomains = dataObj.domains || [];
        finalStats = dataObj.stats || {};
        logLine(
          `完成：共 ${finalStats.batches} 批次，累计 ${finalStats.available} 个可注册，耗时 ${dataObj.elapsed}s`,
          "done"
        );
        // 处理后端同流推送的 wechat_pushed 事件结果
        if (dataObj.wechat_pushed) {
          const wp = dataObj.wechat_pushed;
          if (wp.ok) {
            logLine(`微信推送 ✓ ${wp.peer_id || ""}`.trim(), "info");
          } else if (wp.needs_target) {
            logLine("微信推送：未选择目标，已在弹窗里选", "warn");
          } else {
            logLine(`微信推送失败：${wp.error}`, "error");
          }
        }
        shouldStop = true;
        break;
    }
  }

  try {
    while (!shouldStop) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 事件以 \n\n 分隔
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        // 解析 event: / data: 行
        let eventName = "message";
        const dataLines = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
        }
        if (!dataLines.length) continue;
        const dataStr = dataLines.join("\n");
        let dataObj = {};
        try { dataObj = JSON.parse(dataStr); } catch (_) { dataObj = { raw: dataStr }; }
        handleEvent(eventName, dataObj);
      }
      if (shouldStop) {
        try { await reader.cancel(); } catch (_) {}
        break;
      }
    }
  } catch (e) {
    if (!shouldStop) {
      logLine("读取日志流异常：" + e.message, "error");
    }
  }

  if (finalDomains !== null) {
    renderResults(finalDomains, finalStats || {});
    setStatus(
      `已生成 ${finalDomains.length} 个可注册域名${finalDomains.length < count ? `（请求 ${count} 个）` : ""}`,
      finalDomains.length > 0 ? "success" : "error"
    );
    // 缓存最近一次结果，供"重推"使用；同时触发自动推送
    wechatState.lastResult = { description, domains: finalDomains, stats: finalStats };
    autoPushWechat(description, finalDomains, finalStats);
  } else {
    // stopped 事件路径：finalDomains 仍为 null
    setStatus("已手动停止", "error");
  }

  finishGenerate();
}

function finishGenerate() {
  setButtonLoading($generateBtn, false);
  $stopBtn.classList.add("hidden");
  currentJobId = null;
  if (currentEs) { try { currentEs.close(); } catch (_) {} currentEs = null; }
}

async function stopGenerate() {
  if (!currentJobId) return;
  logLine(`请求停止任务 ${currentJobId}…`, "warn");
  try {
    await fetch(`/api/stop/${encodeURIComponent(currentJobId)}`, { method: "POST" });
  } catch (e) {
    logLine("停止请求失败：" + e.message, "error");
  }
}

function renderResults(domains, stats) {
  $results.innerHTML = "";
  if (!domains.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = `
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/>
        <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
        <line x1="9" y1="9" x2="9.01" y2="9"/>
        <line x1="15" y1="9" x2="15.01" y2="9"/>
      </svg>
      <div>未找到符合要求且可注册的域名。</div>
      <div style="margin-top: 6px; font-size: 12px;">可尝试增加 TLD 选项、放宽长度范围或调整措辞。</div>
    `;
    $results.appendChild(empty);
    return;
  }

  const header = document.createElement("div");
  header.className = "results-header";
  header.innerHTML = `
    <h2>结果</h2>
    <span class="results-count">${domains.length} available</span>
  `;
  $results.appendChild(header);

  const cards = [];
  domains.forEach((d) => {
    const card = document.createElement("div");
    card.className = "domain-card anim-fade-up";
    card.style.opacity = "0";
    card.innerHTML = `
      <div class="domain-card-head">
        <div class="domain-name">${d.domain}</div>
        <span class="badge ${d.status === "available" ? "available" : "unknown"}">${d.status === "available" ? "✓ 可注册" : "? 状态未知"}</span>
      </div>
      <p class="domain-reason">${escapeHtml(d.reason || "")}</p>
      <div class="domain-meta">
        <span>length: ${d.length}</span>
        <span>tld: ${d.tld}</span>
      </div>
    `;
    $results.appendChild(card);
    cards.push(card);
  });

  // Stagger 入场
  observeEntrance(cards);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ---- Modal ----
function openSettings() {
  $settingsModal.classList.remove("hidden");
  $settingsModal.classList.add("open");
  $testResult.textContent = "";
  $testResult.className = "test-result";
}
function hideSettings() {
  // 关闭 modal 是"提交"语义：自动保存当前输入。
  // 用户上一版反馈"AI 设置未保存在本地，禁止每次去设置"——根因是
  // 改完 input 直接点 modal 外部 / 取消，没走"保存"按钮。
  // 这里把 hideSettings 变成唯一关闭入口并自带 save。
  saveConfig();
  $settingsModal.classList.add("hidden");
  $settingsModal.classList.remove("open");
}

function setTestResult(msg, type) {
  $testResult.textContent = msg || "";
  $testResult.className = "test-result" + (type ? " " + type : "");
}

async function testConnection() {
  const apiKey = $apiKey.value.trim();
  if (!apiKey) {
    setTestResult("请先填写 API Key", "error");
    return;
  }
  $testConn.disabled = true;
  setTestResult("测试中…", "loading");
  try {
    const data = await fetchJson("/api/validate-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey,
        base_url: $baseUrl.value.trim() || "https://api.openai.com/v1",
        model: $model.value.trim() || "gpt-4o-mini",
      }),
    });
    if (data.success) {
      const sample = (data.sample_models || []).slice(0, 3).join(", ");
      const available = data.requested_model_available;
      let msg = `✓ 连接成功（可用模型数：${data.model_count}）`;
      if (sample) msg += `，示例：${sample}`;
      if (available === false) msg += `。注意：模型 "${$model.value.trim()}" 不在示例模型中，请确认。`;
      setTestResult(msg, "success");
    } else {
      setTestResult("✗ " + (data.error || "连接失败"), "error");
    }
  } catch (e) {
    setTestResult("✗ 网络错误：" + e.message, "error");
  } finally {
    $testConn.disabled = false;
  }
}

// ---- 微信推送模块 ----

const WECHAT_STORAGE_KEY = "yuming_wechat_config";

function loadWechatConfig() {
  try {
    const raw = localStorage.getItem(WECHAT_STORAGE_KEY);
    if (!raw) return;
    const cfg = JSON.parse(raw);
    if (Array.isArray(cfg.selectedPeerIds)) {
      wechatState.selectedPeerIds = new Set(cfg.selectedPeerIds);
    }
    if (typeof cfg.autoPush === "boolean") {
      wechatState.autoPush = cfg.autoPush;
      $wechatAutoPush.checked = cfg.autoPush;
    }
  } catch (e) {
    console.warn("load wechat config failed", e);
  }
}

function saveWechatConfig() {
  try {
    localStorage.setItem(WECHAT_STORAGE_KEY, JSON.stringify({
      selectedPeerIds: Array.from(wechatState.selectedPeerIds),
      autoPush: wechatState.autoPush,
    }));
  } catch (e) {
    console.warn("save wechat config failed", e);
  }
}

function setWechatHint(text, type) {
  $wechatHint.textContent = text || "";
  $wechatHint.className = "wechat-hint-text" + (type === "success" ? " success" : type === "error" ? " error" : "");
}

// 用 Google Chart API 渲染二维码图片（轻量、无依赖；可降级为显示 URL）
function renderQrcode(url) {
  if (!url) {
    $wechatQrcode.hidden = true;
    $wechatQrcodeImg.innerHTML = "";
    $wechatQrcodeUrl.textContent = "";
    $wechatQrcodeLink.href = "#";
    return;
  }
  $wechatQrcode.hidden = false;
  // 用 api.qrserver.com 备选 — 都比 Google 稳
  // 主：Google Chart API；备：手画点阵
  const chartUrl = "https://chart.googleapis.com/chart?cht=qr&chs=240x240&chld=M|0&chl=" + encodeURIComponent(url);
  const fallbackUrl = "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=" + encodeURIComponent(url);
  // 先试 Google Chart，失败回落到 qrserver
  $wechatQrcodeImg.innerHTML = "";
  const img = new Image();
  img.alt = "微信登录二维码";
  img.style.width = "240px";
  img.style.height = "240px";
  img.style.background = "#fff";
  img.style.borderRadius = "8px";
  img.onerror = () => {
    img.onerror = null;
    img.src = fallbackUrl;
  };
  img.src = chartUrl;
  $wechatQrcodeImg.appendChild(img);
  $wechatQrcodeUrl.textContent = url;
  $wechatQrcodeLink.href = url;
}

// 收到第一条消息后：弹出倒计时刷新提示
function triggerFirstMessageRefresh() {
  // 弹一个 toast overlay 盖在 modal 上
  let overlay = document.getElementById("wechat-first-msg-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "wechat-first-msg-overlay";
    document.body.appendChild(overlay);
  }
  let seconds = 3;
  overlay.innerHTML = `
    <div class="wechat-first-msg-box">
      <div class="wechat-first-msg-icon">✅</div>
      <div class="wechat-first-msg-title">已收到微信消息</div>
      <div class="wechat-first-msg-sub">正在刷新联系人列表…</div>
      <div class="wechat-first-msg-countdown" id="wechat-first-msg-countdown">${seconds}</div>
    </div>
  `;
  overlay.className = "wechat-first-msg-overlay";
  const tick = setInterval(() => {
    seconds--;
    const el = document.getElementById("wechat-first-msg-countdown");
    if (el) el.textContent = seconds;
    if (seconds <= 0) {
      clearInterval(tick);
      overlay.className = "";
      setTimeout(() => {
        overlay.remove();
        wechatFetchStatus(); // 刷新一次获取最新联系人
      }, 300);
    }
  }, 1000);
}

// 刚登录后等待第一条消息的引导 UI（替换整个 modal 中下部内容）
function renderAwaitingFirstMessage() {
  // 隐藏二维码区
  renderQrcode(null);

  // 替换 wechat-hint 和 contact-area 为引导卡片
  $wechatHint.textContent = "";
  $wechatHint.className = "wechat-hint-text";

  const msgBox = document.getElementById("wechat-awaiting-box");
  if (msgBox) {
    // 已存在则只更新脉冲动画时间戳
    return;
  }

  const guide = document.createElement("div");
  guide.id = "wechat-awaiting-box";
  guide.className = "wechat-awaiting-box";
  guide.innerHTML = `
    <div class="wechat-awaiting-icon-wrap">
      <div class="wechat-awaiting-icon">💬</div>
      <div class="wechat-awaiting-ring"></div>
    </div>
    <div class="wechat-awaiting-title">微信已连接 ✓</div>
    <div class="wechat-awaiting-step">
      <span class="wechat-awaiting-num">1</span>
      <span>打开微信，搜索或找到你的 Bot 账号</span>
    </div>
    <div class="wechat-awaiting-step">
      <span class="wechat-awaiting-num">2</span>
      <span>给 Bot 发送任意消息（如"你好"）</span>
    </div>
    <div class="wechat-awaiting-step">
      <span class="wechat-awaiting-num">3</span>
      <span>收到消息后，联系人自动出现，推送功能即可用</span>
    </div>
    <div class="wechat-awaiting-tip">💡 只需发送一次，之后都可以向该联系人推送</div>
  `;

  // 插入到 $wechatHint 之后
  $wechatHint.parentNode.insertBefore(guide, $wechatHint.nextSibling);
}

function updateWechatDot() {
  const dot = $wechatStatusDot;
  dot.className = "status-dot";
  if (!wechatState.botReachable) {
    dot.classList.add("status-dot-disconnected");
    return;
  }
  if (wechatState.status === "connected") {
    dot.classList.add("status-dot-connected");
  } else if (wechatState.status === "logging_in") {
    dot.classList.add("status-dot-logging_in");
  } else if (wechatState.status === "session_expired") {
    dot.classList.add("status-dot-disconnected");
  } else {
    dot.classList.add("status-dot-unknown");
  }
}

function updateWechatUI() {
  // 清理引导卡片（下次 render 会根据状态决定是否重新显示）
  const guide = document.getElementById("wechat-awaiting-box");
  if (guide) guide.remove();

  updateWechatDot();

  if (!wechatState.botReachable) {
    $wechatBotState.textContent = "未连接";
    $wechatBotState.className = "wechat-status-value disconnected";
    $wechatLoginState.textContent = "—";
    $wechatLoginState.className = "wechat-status-value";
    $wechatAccount.textContent = "请先启动 wechat-bot 服务（端口 5002）";
    $wechatLogin.disabled = true;
    $wechatLogout.disabled = true;
    $wechatTest.disabled = true;
    setWechatHint("Bot 服务不可达。检查：5002 端口上是否运行了 wechat-bot 服务（本地 npm start 或 docker compose up yuming-bot）", "error");
    renderQrcode(null);
    return;
  }

  $wechatBotState.textContent = "在线";
  $wechatBotState.className = "wechat-status-value connected";

  const status = wechatState.status;
  $wechatLoginState.textContent = ({
    connected: "已登录",
    logging_in: "扫码中…",
    session_expired: "会话已过期",
    disconnected: "未登录",
  })[status] || status;
  $wechatLoginState.className = "wechat-status-value " + ({
    connected: "connected",
    logging_in: "logging-in",
    session_expired: "disconnected",
    disconnected: "disconnected",
  })[status] || "";

  $wechatAccount.textContent = wechatState.accountId || "—";
  $wechatLogin.disabled = status === "connected" || status === "logging_in";
  $wechatLogout.disabled = status !== "connected";
  $wechatTest.disabled = wechatState.selectedPeerIds.size === 0 || status !== "connected";

  if (status === "logging_in") {
    setWechatHint("请用手机微信扫一扫下方二维码。登录成功后状态会自动更新。", "");
    renderQrcode(wechatState.qrcodeUrl);
  } else if (status === "connected") {
    if (wechatState.awaitingFirstMessage) {
      // 刚连接上，等对方发第一条消息
      setWechatHint("", "");
      renderAwaitingFirstMessage();
    } else if ((wechatState.contacts || []).length === 0) {
      // 连接了一段时间但没有消息（可能对方已发过消息被清掉了）
      setWechatHint("联系人列表为空 — 让任意好友给你发一条消息（24h 内），即可向其推送。", "");
      renderQrcode(null);
    } else {
      setWechatHint("已登录，勾选联系人后可在生成域名时自动推送。", "");
      renderQrcode(null);
    }
  } else if (status === "session_expired") {
    setWechatHint("会话已过期，请重新扫码登录。", "error");
    renderQrcode(null);
  } else if (status === "disconnected") {
    setWechatHint("点击「扫码登录」启动 Bot 端登录流程。", "");
    renderQrcode(null);
  } else {
    setWechatHint("", "");
    renderQrcode(null);
  }

  renderContactList();
}

function renderContactList() {
  const list = wechatState.contacts || [];
  $wechatContactCount.textContent = `// ${list.length} 个联系人`;

  if (!list.length) {
    $wechatContactList.innerHTML = '<div class="wechat-empty">未发现联系人。<br>请先让目标用户在 24 小时内主动给你发一条消息。</div>';
    return;
  }

  $wechatContactList.innerHTML = "";
  const rows = [];
  for (const c of list) {
    const row = document.createElement("label");
    row.className = "wechat-contact-item";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = wechatState.selectedPeerIds.has(c.peerId);
    cb.addEventListener("change", () => {
      if (cb.checked) wechatState.selectedPeerIds.add(c.peerId);
      else wechatState.selectedPeerIds.delete(c.peerId);
      $wechatTest.disabled = wechatState.selectedPeerIds.size === 0 || wechatState.status !== "connected";
    });

    const info = document.createElement("div");
    info.className = "wechat-contact-info";
    const name = document.createElement("div");
    name.className = "wechat-contact-name";
    name.textContent = c.displayName || c.peerId;
    const preview = document.createElement("div");
    preview.className = "wechat-contact-preview";
    const ago = formatTimeAgo(c.lastTs);
    preview.textContent = (c.lastText ? c.lastText.slice(0, 40) : "[媒体]") + (ago ? ` · ${ago}` : "");
    info.appendChild(name);
    info.appendChild(preview);

    const testBtn = document.createElement("button");
    testBtn.type = "button";
    testBtn.className = "wechat-contact-test-btn";
    testBtn.textContent = "测试";
    testBtn.disabled = wechatState.status !== "connected";
    testBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      wechatTestSend(c.peerId, c.displayName || c.peerId);
    });

    row.appendChild(cb);
    row.appendChild(info);
    row.appendChild(testBtn);
    $wechatContactList.appendChild(row);
    rows.push(row);
  }
  // Stagger 入场
  observeEntrance(rows);
}

function formatTimeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() - ts;
  if (diff < 0) return "刚刚";
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  const d = Math.floor(hr / 24);
  return `${d}天前`;
}

async function wechatFetchStatus() {
  try {
    const data = await fetchJson("/api/wechat/status");
    wechatState.botReachable = !!data.bot_reachable;
    wechatState.status = data.status || "unknown";
    wechatState.accountId = data.accountId || null;
    wechatState.contacts = data.contacts || [];
    wechatState.qrcodeUrl = data.qrcodeUrl || null;
    wechatState.awaitingFirstMessage = !!data.awaitingFirstMessage;
    updateWechatUI();

    // 检测第一条消息到达：自动刷新界面
    if (data.firstMessageArrived && !wechatState.firstMessageArrived) {
      wechatState.firstMessageArrived = true;
      triggerFirstMessageRefresh();
    }
  } catch (e) {
    wechatState.botReachable = false;
    wechatState.status = "unknown";
    wechatState.contacts = [];
    wechatState.qrcodeUrl = null;
    wechatState.awaitingFirstMessage = false;
    updateWechatUI();
    setWechatHint("查询状态失败：" + e.message, "error");
  }
}

let wechatLoginPollTimer = null;

async function wechatDoLogin() {
  $wechatLogin.disabled = true;
  setWechatHint("正在启动扫码流程…", "");
  try {
    const data = await fetchJson("/api/wechat/login", { method: "POST" });
    if (data.ok) {
      setWechatHint("登录已启动，请在弹出的二维码上扫描。", "");
      // 立即拉一次状态（modal 打开时已有轮询在跑，这里只 fetch 一次）
      await wechatFetchStatus();
    } else {
      setWechatHint("登录失败：" + (data.error || "未知错误"), "error");
      $wechatLogin.disabled = false;
    }
  } catch (e) {
    setWechatHint("登录请求失败：" + e.message, "error");
    $wechatLogin.disabled = false;
  }
}

async function wechatDoLogout() {
  if (!confirm("确认登出微信？登出后需重新扫码。")) return;
  try {
    await fetchJson("/api/wechat/logout", { method: "POST" });
    wechatState.selectedPeerIds.clear();
    saveWechatConfig();
    await wechatFetchStatus();
  } catch (e) {
    setWechatHint("登出失败：" + e.message, "error");
  }
}

async function wechatTestSend(peerId, displayName) {
  try {
    const data = await fetchJson("/api/wechat/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ peer_id: peerId }),
    });
    if (data.ok) {
      setWechatHint(`已给 ${displayName} 发送测试消息`, "success");
    } else {
      setWechatHint(`发送失败：${data.error || "未知错误"}`, "error");
    }
  } catch (e) {
    setWechatHint("测试发送失败：" + e.message, "error");
  }
}

function openWechatModal() {
  $wechatModal.classList.remove("hidden");
  $wechatModal.classList.add("open");
  $wechatAutoPush.checked = wechatState.autoPush;
  wechatFetchStatus();
  // 启动轮询（无论登录中还是已登录都跑，关掉 modal 时停）
  if (wechatLoginPollTimer) clearInterval(wechatLoginPollTimer);
  wechatLoginPollTimer = setInterval(() => {
    wechatFetchStatus();
  }, 2000);
}

function hideWechatModal() {
  $wechatModal.classList.add("hidden");
  $wechatModal.classList.remove("open");
  // 关闭 modal 时停轮询
  if (wechatLoginPollTimer) {
    clearInterval(wechatLoginPollTimer);
    wechatLoginPollTimer = null;
  }
}

/**
 * 在生成完成时调用：自动把结果推送到所有勾选的联系人。
 * 失败不阻塞，仅写日志。
 */
async function autoPushWechat(description, domains, stats) {
  if (!wechatState.autoPush) return;
  if (wechatState.status !== "connected") return;
  if (wechatState.selectedPeerIds.size === 0) {
    logLine("微信推送：未勾选任何目标，跳过", "warn");
    return;
  }
  if (!domains || !domains.length) {
    logLine("微信推送：无结果可推", "warn");
    return;
  }

  let okCount = 0;
  let failCount = 0;
  for (const peerId of wechatState.selectedPeerIds) {
    try {
      const data = await fetchJson("/api/wechat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peer_id: peerId, description, domains, stats }),
      });
      if (data.ok) {
        okCount++;
        logLine(`微信推送 ✓ ${peerId}`, "info");
      } else {
        failCount++;
        logLine(`微信推送 ✗ ${peerId}：${data.error}`, "error");
      }
    } catch (e) {
      failCount++;
      logLine(`微信推送 ✗ ${peerId}：${e.message}`, "error");
    }
  }
  logLine(`微信推送完成：成功 ${okCount}，失败 ${failCount}`, okCount > 0 ? "info" : "warn");
}

// ---- Init ----
function init() {
  try {
    loadConfig();
    // 初始 main section 走 CSS-only 入场动画（不依赖 JS）
    // Ripple effect for all .btn / .header-btn
    document.querySelectorAll('.btn, .header-btn').forEach(attachRipple);
    $settingsBtn.addEventListener("click", openSettings);
    $settingsCancel.addEventListener("click", hideSettings);
    $settingsSave.addEventListener("click", () => {
      saveConfig();
      hideSettings();
      setStatus("设置已保存", "success");
    });
    bindAutoSave();
    $testConn.addEventListener("click", testConnection);
    $settingsModal.addEventListener("click", (e) => {
      if (e.target === $settingsModal) hideSettings();
    });
    $generateBtn.addEventListener("click", generate);
    $stopBtn.addEventListener("click", stopGenerate);
    $clearLog.addEventListener("click", () => { $logList.innerHTML = ""; });
    // 微信推送
    $wechatBtn.addEventListener("click", openWechatModal);
    $wechatCancel.addEventListener("click", hideWechatModal);
    $wechatModal.addEventListener("click", (e) => {
      if (e.target === $wechatModal) hideWechatModal();
    });
    $wechatRefresh.addEventListener("click", wechatFetchStatus);
    $wechatLogin.addEventListener("click", wechatDoLogin);
    $wechatLogout.addEventListener("click", wechatDoLogout);
    $wechatAutoPush.addEventListener("change", () => {
      wechatState.autoPush = $wechatAutoPush.checked;
      saveWechatConfig();
    });
    $wechatTest.addEventListener("click", () => {
      const first = Array.from(wechatState.selectedPeerIds)[0];
      if (first) wechatTestSend(first, first);
    });
    $wechatSave.addEventListener("click", () => {
      saveWechatConfig();
      hideWechatModal();
      setStatus("已保存微信推送设置", "success");
    });
    // 推送事件面板折叠
    const $pushPanel = document.getElementById("push-event-panel");
    const $pushToggle = document.getElementById("push-event-toggle");
    if ($pushToggle && $pushPanel) {
      $pushToggle.addEventListener("click", () => {
        $pushPanel.classList.toggle("collapsed");
        $pushToggle.textContent = $pushPanel.classList.contains("collapsed") ? "▴" : "▾";
      });
    }
    loadWechatConfig();
    wechatFetchStatus();
    loadTlds();
    console.log("[yuming] init OK");
  } catch (e) {
    console.error("[yuming] init failed:", e);
    $status.textContent = "前端初始化失败：" + e.message;
    $status.classList.add("error");
    throw e;
  }
}

try {
  init();
} catch (e) {
  // init 内部已打印并显示错误；这里再保险一次
  console.error("[yuming] init outer catch:", e);
}